"""Does a path-scoped rule ever match?

A `.claude/rules/` file with `paths:` frontmatter loads only when Claude reads a
matching file. If the globs match nothing in the repository - because a
directory was renamed, or a brace group blew its budget - the rule is inert, and
inert looks exactly like "Claude ignored it".
"""

from __future__ import annotations

from ..globs import any_project_file_matches, compile_all
from ..model import Finding, MemoryFile, Scope, Severity
from . import Context, per_file

RULE_SCOPES = (Scope.PROJECT_RULE, Scope.USER_RULE)


@per_file
def path_scope(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """SCOPE001-003 - the three ways a `paths:` list ends up matching nothing."""
    if memo.scope not in RULE_SCOPES:
        return []
    patterns = memo.paths_globs
    if not patterns:
        return []  # No `paths` means loaded unconditionally, which is fine.

    line = memo.key_lines.get("paths", 1)
    matchers, over_budget, invalid = compile_all(patterns)
    findings: list[Finding] = []

    for pattern in over_budget:
        findings.append(
            memo.finding(
                "SCOPE002",
                Severity.ERROR,
                f"`{pattern}` expands past the 1,000-pattern budget, so its braces "
                f"are matched literally and it matches no file",
                line=line,
                mechanic=(
                    "A rule's whole `paths` list shares one budget of 1,000 expanded "
                    "patterns and 4 MiB. Claude Code uses any pattern that would exceed "
                    "the budget unexpanded, and its literal braces match no files. Each "
                    "brace group multiplies the count, so `{a,b}/{c,d}/*.{ts,tsx}` is "
                    "already eight."
                ),
                fix="Split the pattern across several entries instead of nesting brace groups.",
            )
        )

    for pattern in invalid:
        findings.append(
            memo.finding(
                "SCOPE003",
                Severity.ERROR,
                f"`{pattern}` has a `[` that is not a bracket expression, so it matches nothing",
                line=line,
                mechanic=(
                    "Glob syntax treats `[` as the start of a bracket expression such as "
                    "`[abc]`. A pattern with a `[` that cannot be read as one matches "
                    "nothing, while the rule's other patterns keep working - so the rule "
                    "half-fires and looks unreliable rather than broken."
                ),
                fix="Escape the bracket, as in `photos \\[2024/**`.",
            )
        )

    # USER_RULE globs are matched against whatever project you are in, so a
    # personal rule that does not match *this* repository is expected.
    if not matchers or memo.scope is Scope.USER_RULE or ctx.project is None:
        return findings

    try:
        if any_project_file_matches(ctx.project, matchers):
            return findings
    except TimeoutError:
        return findings  # Too large to answer honestly; say nothing.

    listed = ", ".join(f"`{p}`" for p in patterns[:3])
    findings.append(
        memo.finding(
            "SCOPE001",
            Severity.ERROR,
            f"No file in the project matches {listed} - this rule never loads",
            line=line,
            mechanic=(
                "Path-scoped rules trigger when Claude reads files matching the pattern. "
                "With no matching file there is no trigger, so the rule sits on disk and "
                "never enters context. Nothing distinguishes this from a rule Claude "
                "read and disregarded."
            ),
            fix=(
                "Check the pattern against the repository layout. Remember `*` does not "
                "cross directories - `src/*.ts` misses `src/api/handler.ts`, which "
                "`src/**/*.ts` matches."
            ),
        )
    )
    return findings
