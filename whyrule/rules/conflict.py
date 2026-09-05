"""Do two instructions fight each other?

This is the failure the documentation names outright: "if two rules contradict
each other, Claude may pick one arbitrarily", and again under troubleshooting:
"Look for conflicting instructions across CLAUDE.md files. If two files give
different guidance for the same behavior, Claude may pick one arbitrarily."

Memory files are concatenated rather than overridden, so both instructions are
in context together. Neither one wins by position, and nothing reports the
disagreement.
"""

from __future__ import annotations

from ..instructions import candidate_pairs, extract_all
from ..model import Directive, Finding, Severity
from . import Context, corpus

#: Overlap above which two instructions are treated as saying the same thing
#: rather than merely sharing a topic.
DUPLICATE_THRESHOLD = 0.8

#: Cap on findings per rule. Past a handful the report stops being read, and a
#: memory file with fifty contradictions has one problem, not fifty.
MAX_PER_RULE = 12


def _cite(directive: Directive, root=None) -> str:
    return f"{directive.path}:{directive.line}"


def _quote(text: str, width: int = 64) -> str:
    text = " ".join(text.split())
    return repr(text if len(text) <= width else text[: width - 3] + "...")


def _finding(
    rule: str,
    severity: Severity,
    message: str,
    left: Directive,
    right: Directive,
    mechanic: str,
    fix: str,
) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        message=message,
        path=left.path,
        line=left.line,
        mechanic=mechanic,
        fix=fix,
        related=[_cite(right)],
    )


@corpus
def contradictions(files, ctx: Context) -> list[Finding]:
    """CONFLICT001-003 - one pass over the pairs worth comparing."""
    directives = extract_all(files)
    if len(directives) < 2:
        return []

    conflicts: list[Finding] = []
    value_clashes: list[Finding] = []
    duplicates: list[Finding] = []

    for left, right in candidate_pairs(directives):
        # Order the pair by position so the report reads top to bottom.
        if (str(right.path), right.line) < (str(left.path), left.line):
            left, right = right, left

        overlap = left.overlap(right)
        if overlap < ctx.overlap_threshold:
            continue

        if left.negated != right.negated:
            same_file = left.path == right.path
            where = "in this file" if same_file else f"in {right.path.name}"
            conflicts.append(
                _finding(
                    "CONFLICT001",
                    Severity.WARNING,
                    f"Contradicts an instruction {where}: {_quote(left.text)} "
                    f"against {_quote(right.text)}",
                    left,
                    right,
                    mechanic=(
                        "All discovered memory files are concatenated into context rather "
                        "than overriding each other, so both of these arrive together. "
                        "The documentation is explicit about what happens next: if two "
                        "rules contradict each other, Claude may pick one arbitrarily."
                    ),
                    fix=(
                        "Delete one, or scope them apart so only one applies at a time - "
                        "state the condition each holds under, or move the narrower one "
                        "into a path-scoped `.claude/rules/` file."
                    ),
                )
            )
            continue

        differing = left.values.symmetric_difference(right.values)
        if left.values and right.values and not (left.values & right.values) and differing:
            values = ", ".join(sorted(f"`{v}`" for v in differing)[:4])
            value_clashes.append(
                _finding(
                    "CONFLICT002",
                    Severity.WARNING,
                    f"Same instruction, different values ({values}): {_quote(left.text)} "
                    f"against {_quote(right.text)}",
                    left,
                    right,
                    mechanic=(
                        "Both instructions set the same knob and set it differently. "
                        "Neither is overridden - they are concatenated, so Claude is left "
                        "to choose, and it may choose either one."
                    ),
                    fix="Decide the value once and remove the other instruction.",
                )
            )
            continue

        if overlap >= DUPLICATE_THRESHOLD and left.path != right.path:
            duplicates.append(
                _finding(
                    "CONFLICT003",
                    Severity.NOTE,
                    f"Repeats an instruction in {right.path.name}: {_quote(left.text)}",
                    left,
                    right,
                    mechanic=(
                        "Both files load at launch, so the instruction occupies context "
                        "twice. Duplication is harmless until the two copies drift, at "
                        "which point it becomes a contradiction nobody edited into place."
                    ),
                    fix="Keep it in one file and let the other import that one.",
                )
            )

    return conflicts[:MAX_PER_RULE] + value_clashes[:MAX_PER_RULE] + duplicates[:MAX_PER_RULE]
