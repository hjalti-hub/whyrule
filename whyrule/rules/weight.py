"""Is there too much of it to follow?

"CLAUDE.md files are loaded into the context window at the start of every
session, consuming tokens alongside your conversation ... target under 200 lines
per CLAUDE.md file. Longer files consume more context and reduce adherence."

Everything reported here is measured off the files on disk. Lines and bytes are
counted; nothing is converted into a token estimate, because that number would
be a guess wearing the costume of a measurement.
"""

from __future__ import annotations

from ..model import Finding, MemoryFile, Scope, Severity
from ..spec import LINE_TARGET
from . import Context, corpus, per_file

#: whyrule's own threshold for the *combined* launch context, expressed as a
#: multiple of the documented per-file target. The documentation gives no total,
#: so this multiplier is a judgement call and is reported as one.
TOTAL_TARGET_MULTIPLE = 3


@per_file
def oversized(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """WEIGHT001 - past the documented per-file target, adherence drops."""
    if not memo.scope.loads_at_launch or memo.scope is Scope.IMPORT:
        return []
    lines = memo.line_count
    if lines <= LINE_TARGET:
        return []
    return [
        memo.finding(
            "WEIGHT001",
            Severity.WARNING,
            f"{lines} lines, over the documented 200-line target",
            mechanic=(
                "Target under 200 lines per CLAUDE.md file. Longer files consume more "
                "context and reduce adherence - so past this point, adding an "
                "instruction can make the instructions already there less likely to be "
                "followed."
            ),
            fix=(
                "Move sections into `.claude/rules/` with `paths:` frontmatter, so they "
                "load only when Claude touches matching files. Splitting into `@` "
                "imports organises the text but does not reduce context: imported files "
                "still load at launch."
            ),
        )
    ]


@corpus
def launch_context(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """WEIGHT002-003 - what the whole set costs, and what the imports add."""
    loaded = [m for m in files if m.scope.loads_at_launch]
    if not loaded:
        return []

    total_lines = sum(m.line_count for m in loaded)
    imported = [m for m in loaded if m.scope is Scope.IMPORT]
    threshold = LINE_TARGET * TOTAL_TARGET_MULTIPLE

    findings: list[Finding] = []
    anchor = max(loaded, key=lambda m: m.line_count)

    if total_lines > threshold:
        findings.append(
            anchor.finding(
                "WEIGHT002",
                Severity.NOTE,
                f"{total_lines} lines of memory load at launch across {len(loaded)} files, "
                f"before your first message",
                mechanic=(
                    "Every launch-loaded memory file is concatenated into the same "
                    "context, so the 200-line per-file target is not a per-file budget "
                    "in practice - the instructions compete with each other, not just "
                    "with the conversation. There is no documented total; this is "
                    f"whyrule flagging {TOTAL_TARGET_MULTIPLE}x the per-file target as "
                    "worth a look, not a limit Claude Code enforces."
                ),
                fix=(
                    "Run `/context` to see this measured in the session. The biggest "
                    f"single file is {anchor.path.name} at {anchor.line_count} lines."
                ),
                related=[str(m.path) for m in sorted(loaded, key=lambda m: -m.line_count)[:5]],
            )
        )

    if imported:
        import_lines = sum(m.line_count for m in imported)
        # Only worth saying when the imports are a real share of the total.
        if import_lines >= LINE_TARGET // 2:
            findings.append(
                imported[0].finding(
                    "WEIGHT003",
                    Severity.NOTE,
                    f"{len(imported)} imported file(s) add {import_lines} lines at launch",
                    mechanic=(
                        "Imported files are expanded and loaded into context at launch "
                        "alongside the CLAUDE.md that references them. Splitting content "
                        "into `@` imports helps organisation but does not reduce context."
                    ),
                    fix=(
                        "If the goal was a smaller launch context, `.claude/rules/` with "
                        "`paths:` frontmatter is the mechanism that achieves it - those "
                        "load only when Claude reads a matching file."
                    ),
                    related=[str(m.path) for m in imported[:5]],
                )
            )

    return findings
