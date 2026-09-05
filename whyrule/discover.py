"""Locate every memory file Claude Code would load, and follow the imports.

Cross-file rules are the whole point of this tool, and they are only correct if
we see the same set of files Claude Code sees. Two instructions contradict each
other only if both are in context at once, so scanning `./CLAUDE.md` alone would
miss the case the documentation actually warns about - a project file and a user
file giving different guidance for the same behaviour.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .frontmatter import parse
from .markdown import find_imports
from .model import Finding, MemoryFile, Scope, Severity
from .settings import claude_home
from .spec import FOREIGN_INSTRUCTION_FILES, MANAGED_POLICY_PATHS, MAX_IMPORT_HOPS

#: Directories never worth walking for subdirectory CLAUDE.md files. Claude Code
#: does discover them there, but a vendored dependency's memory file is not
#: something the reader can act on, and one node_modules turns a fast scan slow.
PRUNE = frozenset(
    """
    .git node_modules .venv venv env .tox .mypy_cache .pytest_cache .ruff_cache
    __pycache__ dist build target vendor .next .nuxt .svelte-kit coverage
    site-packages .terraform .gradle Pods DerivedData
    """.split()
)

#: Cap on directories walked when looking for subdirectory memory files. A
#: monorepo can have hundreds of thousands; the rules that use these findings
#: are notes, and no note is worth a minute of walking.
WALK_LIMIT = 20_000


def _read(path: Path, scope: Scope, **kwargs) -> MemoryFile:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        memo = MemoryFile(path=path, scope=scope, text="", **kwargs)
        memo.parse_findings.append(
            Finding(
                rule="LOAD000",
                severity=Severity.ERROR,
                message=f"Cannot read memory file: {exc.strerror or exc}",
                path=path,
                mechanic="A memory file Claude Code cannot read is one that does not exist.",
                fix="Check file permissions.",
            )
        )
        return memo

    text = raw.decode("utf-8", errors="replace")
    memo = MemoryFile(path=path, scope=scope, text=text, size_bytes=len(raw), **kwargs)

    # Only rules files carry frontmatter. Parsing a CLAUDE.md that happens to
    # open with `---` would swallow a horizontal rule and the text under it.
    if scope in (Scope.PROJECT_RULE, Scope.USER_RULE):
        result = parse(text)
        memo.frontmatter = result.data
        memo.key_lines = result.key_lines
        memo.body_line = result.body_line
    return memo


def _rules_dir(root: Path, scope: Scope) -> list[MemoryFile]:
    """Every `.md` under a rules directory, discovered recursively."""
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            found.append(_read(path, scope))
    return found


def _ancestors(project: Path) -> list[Path]:
    """Directories from the filesystem root down to the project, inclusive.

    Ordered root-first because that is the order the contents are concatenated:
    "content is ordered from the filesystem root down to your working directory".
    """
    chain = [project, *project.parents]
    return list(reversed(chain))


def _subdirectory_files(project: Path) -> list[MemoryFile]:
    """CLAUDE.md files below the project, which load on demand rather than at launch."""
    found: list[MemoryFile] = []
    walked = 0
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in sorted(dirnames) if d not in PRUNE and not d.startswith(".")]
        walked += 1
        if walked > WALK_LIMIT:
            break
        here = Path(dirpath)
        if here == project:
            continue
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            if name in filenames:
                found.append(_read(here / name, Scope.SUBDIR))
    return found


def resolve_import(target: str, source: Path) -> Path:
    """Resolve an `@path` the way Claude Code does.

    "Relative paths resolve relative to the file containing the import, not the
    working directory" - resolving against the cwd is the single easiest way to
    report a broken import that works fine.
    """
    if target.startswith("~"):
        return Path(target).expanduser()
    candidate = Path(target)
    if candidate.is_absolute():
        return candidate
    return (source.parent / candidate).resolve()


def _follow_imports(roots: list[MemoryFile]) -> list[MemoryFile]:
    """Expand the import graph, stopping where Claude Code stops.

    Depth counts hops from a file that loads on its own: the import written in a
    CLAUDE.md is hop 1. Files past ``MAX_IMPORT_HOPS`` are still returned, so a
    rule can report that they never enter context, but they are not followed
    further.
    """
    seen = {memo.path.resolve() for memo in roots}
    expanded: list[MemoryFile] = []
    queue = [(memo, 0) for memo in roots]

    while queue:
        memo, depth = queue.pop(0)
        for ref in find_imports(memo.text):
            resolved = resolve_import(ref.target, memo.path)
            if resolved in seen:
                continue
            seen.add(resolved)
            if not resolved.is_file():
                continue  # IMPORT001 reports this; there is nothing to read.
            child = _read(
                resolved,
                Scope.IMPORT,
                imported_by=memo.path,
                depth=depth + 1,
            )
            expanded.append(child)
            if depth + 1 < MAX_IMPORT_HOPS:
                queue.append((child, depth + 1))

    return expanded


def _foreign(project: Path) -> list[MemoryFile]:
    """Instruction files other agents read and Claude Code does not."""
    found = []
    for name in FOREIGN_INSTRUCTION_FILES:
        path = project / name
        if path.is_file():
            found.append(_read(path, Scope.FOREIGN))
    return found


def discover(
    project: Path | None,
    *,
    include_user: bool = True,
    include_subdirs: bool = True,
    explicit: list[Path] | None = None,
) -> list[MemoryFile]:
    """Every memory file in play, ordered as Claude Code concatenates them."""
    found: list[MemoryFile] = []

    if explicit:
        for path in explicit:
            path = path.expanduser()
            if path.is_dir():
                for name in ("CLAUDE.md", "CLAUDE.local.md"):
                    if (path / name).is_file():
                        found.append(_read(path / name, Scope.PROJECT))
                found.extend(_rules_dir(path / ".claude" / "rules", Scope.PROJECT_RULE))
            elif path.is_file():
                scope = (
                    Scope.PROJECT_RULE
                    if ".claude" in path.parts and "rules" in path.parts
                    else Scope.PROJECT
                )
                found.append(_read(path, scope))
        found.extend(_follow_imports(found))
        return found

    if project is None:
        project = Path.cwd()
    project = project.resolve()

    managed = MANAGED_POLICY_PATHS.get(sys.platform)
    if managed and Path(managed).is_file():
        found.append(_read(Path(managed), Scope.MANAGED))

    if include_user:
        home = claude_home()
        if (home / "CLAUDE.md").is_file():
            found.append(_read(home / "CLAUDE.md", Scope.USER))
        found.extend(_rules_dir(home / "rules", Scope.USER_RULE))

    for directory in _ancestors(project):
        at_project = directory == project
        for name, launch_scope in (
            ("CLAUDE.md", Scope.PROJECT if at_project else Scope.ANCESTOR),
            ("CLAUDE.local.md", Scope.LOCAL if at_project else Scope.ANCESTOR),
        ):
            path = directory / name
            if path.is_file():
                found.append(_read(path, launch_scope))
        if at_project and (directory / ".claude" / "CLAUDE.md").is_file():
            found.append(_read(directory / ".claude" / "CLAUDE.md", Scope.PROJECT))

    found.extend(_rules_dir(project / ".claude" / "rules", Scope.PROJECT_RULE))

    if include_subdirs:
        found.extend(_subdirectory_files(project))

    found.extend(_foreign(project))
    found.extend(_follow_imports([f for f in found if f.scope.loads_at_launch]))

    found.sort(key=lambda m: (m.scope.load_order, str(m.path)))
    return found
