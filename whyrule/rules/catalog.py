"""One-line summary of every rule, for ``whyrule rules`` and the README."""

from __future__ import annotations

CATALOG: dict[str, str] = {
    # Does the file reach Claude at all?
    "LOAD000": "Memory file cannot be read",
    "LOAD001": "File is over the 4 MiB limit, so Claude Code skips it whole",
    "LOAD002": "A `claudeMdExcludes` pattern in settings quietly excludes this file",
    "LOAD003": "An instruction file Claude Code does not read, with no CLAUDE.md importing it",
    "LOAD004": "`claudeMd` is set in a settings layer where the key has no effect",
    # Does the text inside it reach Claude?
    "REACH001": "An instruction sits in an HTML comment, which is stripped before injection",
    # Do the imports resolve?
    "IMPORT001": "`@import` target does not exist, so it contributes nothing",
    "IMPORT002": "Import sits deeper than four hops and never enters context",
    "IMPORT003": "Imports form a cycle",
    "IMPORT004": "Prose that reads as a package scope or handle is parsed as an import",
    "IMPORT005": "A project import resolves outside the working directory and needs approval",
    # Does a path-scoped rule ever match?
    "SCOPE001": "`paths:` globs match no file in the project, so the rule never loads",
    "SCOPE002": "`paths:` brace expansion exceeds its 1,000-pattern budget and matches nothing",
    "SCOPE003": "A `paths:` pattern has an unclosed `[`, so it matches nothing",
    # Do two instructions fight?
    "CONFLICT001": "Two loaded instructions about one subject contradict each other",
    "CONFLICT002": "One setting is given two different values",
    "CONFLICT003": "The same instruction is repeated in two loaded files",
    # Can the instruction be acted on?
    "ENFORCE001": "A guarantee about when something runs, which only a hook can make",
    "ENFORCE002": "An absolute prohibition, which only permissions or a hook can enforce",
    "ENFORCE003": "An instruction with nothing concrete enough to verify",
    "ENFORCE004": "References a path that does not exist",
    "ENFORCE005": "Tells Claude to run a command the project does not define",
    # Is there too much of it?
    "WEIGHT001": "File is over the documented 200-line target, which reduces adherence",
    "WEIGHT002": "Launch-loaded memory is large enough to compete with itself",
    "WEIGHT003": "Imports load at launch too, so splitting the file did not reduce context",
}

#: Grouping used by ``whyrule rules`` output.
GROUPS: dict[str, str] = {
    "LOAD": "Loading - does the file reach Claude at all?",
    "REACH": "Reach - does the text inside it survive to context?",
    "IMPORT": "Imports - do the `@` references resolve?",
    "SCOPE": "Scoping - does a path-scoped rule ever match?",
    "CONFLICT": "Conflict - do two instructions fight each other?",
    "ENFORCE": "Enforceability - can the instruction be acted on?",
    "WEIGHT": "Weight - is there too much of it to follow?",
}
