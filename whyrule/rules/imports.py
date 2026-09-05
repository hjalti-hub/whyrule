"""Do the `@` references resolve?

Imports are the quietest failure in a memory file. A broken one is not an error
and not a warning - the text simply is not there, and the CLAUDE.md around it
reads exactly as it did when it worked.
"""

from __future__ import annotations

from pathlib import Path

from ..discover import resolve_import
from ..markdown import find_imports
from ..model import Finding, MemoryFile, Scope, Severity
from ..spec import MAX_IMPORT_HOPS, NPM_SCOPE_PATTERN
from . import Context, corpus, per_file

#: File extensions an import is plausibly meant to name. Used only to tell a
#: mistyped path from prose that was never meant to be an import at all.
DOCUMENT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".mdx"})


def _short(path: Path, ctx: Context) -> str:
    """A path the reader can place at a glance.

    Absolute paths in a message push the part that matters off the line, and
    every import in a project resolves under the project root anyway.
    """
    if ctx.project is not None:
        try:
            return str(path.resolve().relative_to(ctx.project.resolve()))
        except ValueError:
            pass
    return str(path)


def _looks_like_prose(target: str) -> str | None:
    """Name what a non-resolving import actually is, when it is not a path.

    Returns a human description, or None when the text really does look like a
    file someone meant to import.
    """
    if Path(target).suffix.lower() in DOCUMENT_SUFFIXES:
        return None
    if "/" not in target and "." not in target:
        return "a handle or a mention"
    if NPM_SCOPE_PATTERN.match(target) and Path(target).suffix == "":
        return "a package scope"
    return None


@per_file
def unresolved_import(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """IMPORT001 and IMPORT004 - the target is not a file that can be read."""
    if not memo.scope.loads_at_launch and memo.scope is not Scope.IMPORT:
        return []

    findings = []
    for ref in find_imports(memo.text):
        resolved = resolve_import(ref.target, memo.path)
        if resolved.is_file():
            continue

        prose = _looks_like_prose(ref.target)
        if prose:
            findings.append(
                memo.finding(
                    "IMPORT004",
                    Severity.WARNING,
                    f"`{ref.raw}` reads as {prose}, but is parsed as an import of "
                    f"a file that does not exist",
                    line=ref.line,
                    mechanic=(
                        "Import parsing skips Markdown code spans and fenced code blocks, "
                        "and nothing else. Any `@word` in prose is treated as an import "
                        "path, so a package name or a person's handle becomes an import "
                        "attempt that resolves to nothing."
                    ),
                    fix=(
                        f"Wrap it in backticks - `` `{ref.raw}` `` keeps the text literal "
                        "and stops it being read as an import."
                    ),
                )
            )
            continue

        findings.append(
            memo.finding(
                "IMPORT001",
                Severity.ERROR,
                f"`{ref.raw}` imports {_short(resolved, ctx)}, which does not exist "
                f"- nothing is loaded",
                line=ref.line,
                mechanic=(
                    "Relative import paths resolve relative to the file containing the "
                    "import, not the working directory. An import that resolves to no "
                    "file contributes nothing and reports nothing; the CLAUDE.md around "
                    "it looks unchanged."
                ),
                fix=(
                    "Point it at a file that exists. Relative paths resolve against "
                    f"{_short(memo.path.parent, ctx) or '.'}/, the directory of the file "
                    "the import is written in - not the working directory."
                ),
            )
        )
    return findings


@per_file
def import_too_deep(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """IMPORT002 - past four hops the chain stops, and the tail never loads."""
    if memo.scope is not Scope.IMPORT or memo.depth < MAX_IMPORT_HOPS:
        return []

    refs = find_imports(memo.text)
    if not refs:
        return []

    targets = ", ".join(sorted({r.raw for r in refs})[:3])
    return [
        memo.finding(
            "IMPORT002",
            Severity.ERROR,
            f"This file is {memo.depth} import hops deep, so its own imports "
            f"({targets}) are never followed",
            line=refs[0].line,
            mechanic=(
                "Imported files can recursively import other files, with a maximum "
                "depth of four hops. Anything past that is not loaded, and the chain "
                "stops without an error."
            ),
            fix=(
                "Flatten the chain: import these files directly from the CLAUDE.md at "
                "the top of it, rather than through intermediate files."
            ),
            related=[str(memo.imported_by)] if memo.imported_by else [],
        )
    ]


@corpus
def import_cycle(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """IMPORT003 - a cycle is cut somewhere, and which side gets cut is not obvious."""
    graph: dict[Path, list[tuple[Path, int]]] = {}
    known = {memo.path.resolve(): memo for memo in files}
    for memo in files:
        edges = []
        for ref in find_imports(memo.text):
            edges.append((resolve_import(ref.target, memo.path), ref.line))
        graph[memo.path.resolve()] = edges

    findings = []
    reported: set[frozenset] = set()

    def walk(node: Path, stack: list[Path], lines: list[int]) -> None:
        for target, line in graph.get(node, []):
            if target in stack:
                cycle = stack[stack.index(target) :] + [target]
                key = frozenset(cycle)
                if key in reported:
                    continue
                reported.add(key)
                memo = known.get(node)
                if memo is None:
                    continue
                names = " -> ".join(p.name for p in cycle)
                findings.append(
                    memo.finding(
                        "IMPORT003",
                        Severity.WARNING,
                        f"Import cycle: {names}",
                        line=line,
                        mechanic=(
                            "A file already expanded is not expanded again, so the cycle "
                            "terminates - but where it terminates depends on which file "
                            "was reached first, and that is not something you control."
                        ),
                        fix="Break the cycle so each file is imported from one place.",
                        related=[str(p) for p in cycle if p != node],
                    )
                )
                continue
            if target in graph and target not in stack:
                walk(target, stack + [target], lines + [line])

    for start in list(graph):
        walk(start, [start], [])
    return findings


@per_file
def external_import(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """IMPORT005 - an import outside the project needs a one-time approval."""
    if ctx.project is None or memo.scope not in (Scope.PROJECT, Scope.LOCAL, Scope.PROJECT_RULE):
        return []

    # Both sides are resolved before comparing. A project root reached through
    # a symlink - /tmp on macOS is one - otherwise fails every containment
    # check, and every import in the project looks external.
    root = ctx.project.resolve()

    findings = []
    for ref in find_imports(memo.text):
        resolved = resolve_import(ref.target, memo.path).resolve()
        try:
            resolved.relative_to(root)
            continue
        except ValueError:
            pass
        findings.append(
            memo.finding(
                "IMPORT005",
                Severity.NOTE,
                f"`{ref.raw}` resolves outside the project, so it loads only "
                f"after you approve it once",
                line=ref.line,
                mechanic=(
                    "An import in a project-level memory file is external when its path "
                    "resolves outside your working directory. Claude Code shows an "
                    "approval dialog the first time. If you decline, the imports stay "
                    "disabled and the dialog does not appear again - so a decline you "
                    "made months ago is indistinguishable from an import that works."
                ),
                fix=(
                    "Nothing to fix if you approved it. If this file is committed, "
                    "expect every teammate to see the dialog too."
                ),
            )
        )
    return findings
