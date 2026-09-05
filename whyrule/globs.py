"""Glob handling for `paths:` patterns and `claudeMdExcludes`.

`fnmatch` is not enough: it gives `*` the power to cross directory separators,
so `src/*.ts` would match `src/deep/nested.ts` and a rule that never fires would
look like it fires everywhere. These patterns are matched the way the
documentation describes them, with `**` crossing separators and `*` not.

The brace budget is a documented behaviour rather than a nicety: "a rule's whole
`paths` list shares one budget of 1,000 expanded patterns and 4 MiB, and
patterns without braces don't count against it. Claude Code uses any pattern
that would exceed the budget unexpanded, and its literal braces match no files."
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .spec import PATHS_PATTERN_BUDGET

_BRACE = re.compile(r"\{([^{}]*)\}")


class InvalidPattern(ValueError):
    """A pattern that cannot be read as a glob, and so matches nothing."""


def expand_braces(pattern: str, budget: int) -> tuple[list[str], int]:
    """Expand `{a,b}` groups, returning the expansions and the budget left.

    Returns the pattern unexpanded when it would exceed ``budget``, mirroring
    what Claude Code does - and the literal braces then match no file.
    """
    if "{" not in pattern:
        return [pattern], budget

    results = [pattern]
    while True:
        match = next((_BRACE.search(p) for p in results if _BRACE.search(p)), None)
        if match is None:
            break
        grown: list[str] = []
        for candidate in results:
            found = _BRACE.search(candidate)
            if found is None:
                grown.append(candidate)
                continue
            for option in found.group(1).split(","):
                grown.append(candidate[: found.start()] + option + candidate[found.end() :])
        if len(grown) > budget:
            return [pattern], budget
        results = grown
    return results, budget - len(results)


def translate(pattern: str) -> re.Pattern:
    """Compile one glob into a regex anchored at both ends.

    Raises ``InvalidPattern`` for a `[` that cannot be read as a bracket
    expression. That is not a crash case: such a pattern "matches nothing, and
    the rule's other patterns keep working", which is exactly what a caller
    needs to be told.
    """
    out = ["(?s:"]
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                # `**/` may also match zero directories, so `**/*.ts` matches
                # `a.ts` at the root as well as `src/a.ts`.
                if pattern[i : i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            close = pattern.find("]", i + 1)
            if close == -1:
                raise InvalidPattern(pattern)
            inner = pattern[i + 1 : close]
            if not inner:
                raise InvalidPattern(pattern)
            if inner[0] in "!^":
                inner = "^" + inner[1:]
            out.append(f"[{inner}]")
            i = close + 1
        elif ch == "\\" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(ch))
            i += 1
    out.append(")\\Z")
    return re.compile("".join(out))


def compile_all(patterns: list[str]) -> tuple[list[re.Pattern], list[str], list[str]]:
    """Compile a `paths:` list under its shared expansion budget.

    Returns the usable matchers, the patterns that blew the budget, and the
    patterns that are not valid globs.
    """
    budget = PATHS_PATTERN_BUDGET
    matchers: list[re.Pattern] = []
    over_budget: list[str] = []
    invalid: list[str] = []

    for pattern in patterns:
        expansions, remaining = expand_braces(pattern, budget)
        if "{" in pattern and expansions == [pattern]:
            over_budget.append(pattern)
            continue
        budget = remaining
        for expansion in expansions:
            try:
                matchers.append(translate(expansion))
            except InvalidPattern:
                invalid.append(expansion)
    return matchers, over_budget, invalid


def matches(path: str, matchers: list[re.Pattern]) -> bool:
    return any(m.match(path) for m in matchers)


#: Cap on files examined when asking whether a `paths:` list matches anything.
#: The answer is almost always found in the first handful; the cap exists so a
#: monorepo cannot turn a lint into a filesystem crawl.
MATCH_SCAN_LIMIT = 40_000


def any_project_file_matches(project: Path, matchers: list[re.Pattern]) -> bool:
    """True when at least one file under ``project`` matches any pattern.

    Paths are tested relative to the project root and with forward slashes, so
    the same rule behaves identically on Windows.
    """
    if not matchers:
        return False
    from .discover import PRUNE

    seen = 0
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in PRUNE]
        rel_dir = os.path.relpath(dirpath, project)
        prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
        for name in filenames:
            seen += 1
            if seen > MATCH_SCAN_LIMIT:
                # Unknown rather than "no match": returning False here would
                # report a rule as dead on the strength of not having looked.
                raise TimeoutError("scan limit reached")
            if matches(prefix + name, matchers):
                return True
    return False
