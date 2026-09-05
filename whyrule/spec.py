"""Constants taken from Claude Code's documented memory behaviour.

Everything in this module is a fact from the official documentation, not a
preference. If a number here is wrong, every rule built on it is wrong, so each
one records the sentence it comes from.

Source: https://code.claude.com/docs/en/memory
"""

from __future__ import annotations

import re

#: "Claude Code loads a CLAUDE.md file of up to 4 MiB in full and skips a larger
#: file." Past this size the file contributes nothing and nothing says so.
MAX_FILE_BYTES = 4 * 1024 * 1024

#: "target under 200 lines per CLAUDE.md file. Longer files consume more context
#: and reduce adherence." A target rather than a limit, so it is a warning.
LINE_TARGET = 200

#: "Imported files can recursively import other files, with a maximum depth of
#: four hops." Hop 1 is the import written in a loaded CLAUDE.md, so a file
#: reached by a fifth hop never enters context.
MAX_IMPORT_HOPS = 4

#: A `paths:` list in a `.claude/rules/` file shares one expansion budget of
#: 1,000 patterns and 4 MiB. "Claude Code uses any pattern that would exceed the
#: budget unexpanded, and its literal braces match no files."
PATHS_PATTERN_BUDGET = 1000

#: The file names Claude Code loads as memory, in the order it concatenates them
#: within a single directory: CLAUDE.local.md is appended after CLAUDE.md.
MEMORY_FILENAMES = ("CLAUDE.md", "CLAUDE.local.md")

#: "Claude Code reads `CLAUDE.md`, not `AGENTS.md`." An AGENTS.md alone is
#: invisible; it reaches Claude only via an import or a symlink.
FOREIGN_INSTRUCTION_FILES = (
    "AGENTS.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".github/copilot-instructions.md",
)

#: Managed-policy CLAUDE.md locations, by platform. This file cannot be excluded
#: by `claudeMdExcludes` and loads before user and project files.
MANAGED_POLICY_PATHS = {
    "darwin": "/Library/Application Support/ClaudeCode/CLAUDE.md",
    "linux": "/etc/claude-code/CLAUDE.md",
    "win32": r"C:\Program Files\ClaudeCode\CLAUDE.md",
}

#: "`claudeMd` ... Where it's honored: managed and policy settings only. Setting
#: `claudeMd` in user, project, or local settings has no effect."
CLAUDE_MD_SETTING_HONOURED_IN = frozenset({"managed", "policy"})

# ---------------------------------------------------------------------------
# Import syntax
# ---------------------------------------------------------------------------

#: An `@path` import. Import parsing "skips Markdown code spans and fenced code
#: blocks", which is handled by the scanner rather than by this pattern - a
#: regex cannot see whether it is inside a fence.
#:
#: The trailing character class deliberately excludes `,` `;` `:` and a final
#: `.` so that prose like "see @docs/setup.md, then ..." resolves the path a
#: reader would expect.
IMPORT_PATTERN = re.compile(r"(?<![\w`/])@(~?[\w./\-]*[\w/\-])")

#: Import-looking text that is almost never a file: npm scopes, email addresses
#: and decorators. These still parse as imports, so they are reported, but with
#: a message that names what they actually are.
NPM_SCOPE_PATTERN = re.compile(r"^[a-z0-9][\w.-]*/[\w.-]+$")

# ---------------------------------------------------------------------------
# Instruction shape
# ---------------------------------------------------------------------------

#: Words that flip an instruction's polarity. Two instructions about the same
#: subject with opposite polarity are the contradiction the documentation warns
#: about: "if two rules contradict each other, Claude may pick one arbitrarily."
NEGATIONS = frozenset(
    """
    never no not dont don't doesnt doesn't cannot cant can't avoid without
    skip omit refuse stop prohibited forbidden disallowed banned exclude
    """.split()
)

#: Modal cues that mark a line as an instruction rather than a description.
#: Without one of these a bullet is documentation, and judging it as a rule
#: produces noise.
DIRECTIVE_PATTERN = re.compile(
    r"""
      \b(?:always|never|must|should|shall|need\s+to|have\s+to)\b
    | \b(?:do\s+not|don't|dont|avoid|prefer|only\s+use|use\s+only)\b
    | \b(?:use|run|write|keep|make\s+sure|ensure|require[sd]?)\b
    | ^\s*(?:no|never)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Instructions that promise to fire at a fixed point in the session. CLAUDE.md
#: "is context, not enforced configuration"; the documentation's own answer for
#: these is a hook: "If the instruction is something that must run at a specific
#: point, such as before every commit or after each file edit, write it as a
#: hook instead."
LIFECYCLE_PATTERN = re.compile(
    r"""
      \b(?:before|after)\s+(?:every|each|any|all)\b
    | \bbefore\s+(?:you\s+)?(?:commit|committing|push|pushing|merge|merging)\b
    | \bafter\s+(?:you\s+)?(?:edit|editing|writ\w+|chang\w+|sav\w+)\b
    | \bon\s+(?:every|each)\s+\w+
    | \bevery\s+time\s+you\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Absolute prohibitions. The documentation is explicit that CLAUDE.md cannot
#: enforce one: "To block an action regardless of what Claude decides, use a
#: PreToolUse hook instead."
PROHIBITION_PATTERN = re.compile(
    r"\b(?:never|do\s+not|don't|dont|under\s+no\s+circumstances)\b", re.IGNORECASE
)

#: Verbs that make a prohibition worth enforcing mechanically rather than
#: asking for it. Prohibiting a *style* is fine in prose; prohibiting an action
#: with consequences is what `permissions.deny` and hooks exist for.
CONSEQUENTIAL_PATTERN = re.compile(
    r"""
      \b(?:rm\s+-rf|force\s*-?push|push\s+(?:to\s+)?(?:main|master|prod\w*))\b
    | \b(?:drop\s+(?:the\s+)?(?:table|database)|truncate)\b
    | \b(?:deploy|migrat\w+|delete|destroy)\b[^.]{0,40}\b(?:prod\w*|live|production)\b
    | \b(?:commit|push|leak|expose|hardcode)\b[^.]{0,30}\b(?:secret|credential|token|api\s*key|password)\w*
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Instructions with no verifiable content. The documentation asks for the
#: opposite: "write instructions that are concrete enough to verify" - "Use
#: 2-space indentation" instead of "Format code properly".
#:
#: Matching is deliberately anchored on the whole line being one of these
#: phrases plus filler, so "write clean shutdown handlers in `src/daemon/`"
#: does not trip it.
VAGUE_PHRASES = (
    "best practices",
    "clean code",
    "good code",
    "high quality code",
    "quality code",
    "properly",
    "correctly",
    "appropriately",
    "as needed",
    "when appropriate",
    "if necessary",
    "be careful",
    "be smart",
    "be thorough",
    "use common sense",
    "think carefully",
    "do your best",
    "follow conventions",
    "follow the conventions",
    "idiomatic",
    "readable code",
    "maintainable code",
    "well organized",
    "well-organized",
    "sensible",
    "reasonable",
)

#: Words too common in instructions to distinguish one from another. Shared with
#: the contradiction detector, where a match on filler is a false positive.
STOPWORDS = frozenset(
    """
    a an and are as at be been being but by for from has have had how in into is
    it its of on or that the this to was were what when where which who will
    with you your please always never must should shall need needs to do does
    doing dont don't not no use used uses using make makes making keep keeps
    ensure ensures require requires all any every each only just also than then
    there their they them these those we our us i me my if unless while so such
    can could would may might will shall about after before during over under
    claude code file files line lines
    """.split()
)
