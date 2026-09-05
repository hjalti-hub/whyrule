"""Does the file reach Claude at all?

These are the root causes. A file that never loads explains every other
complaint about its contents, which is why the LOAD group sorts first.
"""

from __future__ import annotations

from ..globs import InvalidPattern, translate
from ..markdown import find_imports, find_stripped_comments, is_directive
from ..model import Finding, MemoryFile, Scope, Severity
from ..spec import MAX_FILE_BYTES
from . import Context, corpus, per_file


def _mib(size: int) -> str:
    return f"{size / (1024 * 1024):.2f} MiB"


@per_file
def oversized_file(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """LOAD001 - past 4 MiB the file is skipped whole, not truncated."""
    if not memo.scope.loads_at_launch or memo.size_bytes <= MAX_FILE_BYTES:
        return []
    return [
        memo.finding(
            "LOAD001",
            Severity.ERROR,
            f"File is {_mib(memo.size_bytes)}, over the 4 MiB limit - none of it is loaded",
            mechanic=(
                "Claude Code loads a CLAUDE.md file of up to 4 MiB in full and skips a "
                "larger file. It is skipped whole rather than truncated, so no part of "
                "this file reaches the session and nothing reports that."
            ),
            fix=(
                "Split the file. Move the bulk into `.claude/rules/` with `paths:` "
                "frontmatter so each part loads only when it is relevant."
            ),
        )
    ]


@corpus
def excluded_by_settings(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """LOAD002 - a `claudeMdExcludes` glob silently drops a file that is otherwise correct."""
    excludes = ctx.settings.excludes
    if not excludes:
        return []

    compiled = []
    for pattern, layer in excludes:
        try:
            compiled.append((pattern, layer, translate(pattern)))
        except InvalidPattern:
            continue

    findings = []
    for memo in files:
        # "Managed policy CLAUDE.md files cannot be excluded."
        if memo.scope in (Scope.MANAGED, Scope.FOREIGN):
            continue
        absolute = str(memo.path)
        for pattern, layer, matcher in compiled:
            if matcher.match(absolute):
                findings.append(
                    memo.finding(
                        "LOAD002",
                        Severity.ERROR,
                        f"Excluded by `claudeMdExcludes` pattern {pattern!r} "
                        f"in {layer.scope} settings - this file is never loaded",
                        mechanic=(
                            "`claudeMdExcludes` skips memory files by path or glob, matched "
                            "against absolute paths. Arrays merge across every settings "
                            "layer, so a pattern you did not write can exclude your file, "
                            "and the session gives no sign that it did."
                        ),
                        fix=(
                            f"Narrow or remove the pattern in {layer.path}, or run "
                            "`/context` in a session to confirm which memory files loaded."
                        ),
                        related=[str(layer.path)],
                    )
                )
                break
    return findings


@corpus
def unread_instruction_file(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """LOAD003 - AGENTS.md and friends are read by other agents, not by Claude Code."""
    foreign = [m for m in files if m.scope is Scope.FOREIGN]
    if not foreign:
        return []

    # An import or a symlink is the documented way to make one of these load.
    imported: set[str] = set()
    for memo in files:
        if not memo.scope.loads_at_launch:
            continue
        for ref in find_imports(memo.text):
            imported.add(ref.target.lstrip("./").lower())
    resolved = {m.path.resolve() for m in files if m.scope.loads_at_launch}

    findings = []
    for memo in foreign:
        name = memo.path.name
        if name.lower() in imported or memo.path.resolve() in resolved:
            continue
        findings.append(
            memo.finding(
                "LOAD003",
                Severity.ERROR,
                f"{name} is never read - Claude Code reads CLAUDE.md, and nothing imports this",
                mechanic=(
                    "Claude Code reads `CLAUDE.md`, not `AGENTS.md` or another agent's "
                    "instruction file. Everything written here is invisible to Claude "
                    "unless a loaded CLAUDE.md imports it or CLAUDE.md is a symlink to it."
                ),
                fix=(
                    f"Add `@{name}` as the first line of your CLAUDE.md, so both tools "
                    f"read one file. `ln -s {name} CLAUDE.md` works too when you have no "
                    "Claude-specific content to add underneath."
                ),
            )
        )
    return findings


@corpus
def ineffective_claude_md_setting(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """LOAD004 - `claudeMd` in a settings layer that does not honour it."""
    findings = []
    for layer in ctx.settings.ineffective_claude_md():
        findings.append(
            Finding(
                rule="LOAD004",
                severity=Severity.ERROR,
                message=(
                    f"`claudeMd` is set in {layer.scope} settings, where the key does nothing"
                ),
                path=layer.path,
                mechanic=(
                    "`claudeMd` is honoured in managed and policy settings only. Setting "
                    "it in user, project, or local settings has no effect, and no warning "
                    "is printed - the instructions simply never enter any session."
                ),
                fix=(
                    "Put the text in a CLAUDE.md file instead, or move the key into "
                    "managed settings if you are deploying it organization-wide."
                ),
            )
        )
    return findings


@per_file
def instruction_in_stripped_comment(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """REACH001 - HTML comments are removed before the file becomes context."""
    if not memo.scope.loads_at_launch:
        return []

    findings = []
    for span in find_stripped_comments(memo.text):
        directives = [
            line for line in span.text.splitlines() if is_directive(line) and "<!--" not in line
        ]
        if not directives:
            continue  # A maintainer note is what comments are for.
        sample = directives[0].strip()
        if len(sample) > 60:
            sample = sample[:57] + "..."
        findings.append(
            memo.finding(
                "REACH001",
                Severity.ERROR,
                f"Instruction inside an HTML comment never reaches Claude: {sample!r}",
                line=span.line,
                mechanic=(
                    "Block-level HTML comments in CLAUDE.md files are stripped before the "
                    "content is injected into Claude's context. The file loads and this "
                    "text is silently dropped from it - reading the file yourself is the "
                    "one way you would never catch it."
                ),
                fix=(
                    "Move the instruction outside the comment. Keep comments for notes "
                    "meant only for human maintainers, which is what the stripping is for."
                ),
            )
        )
    return findings
