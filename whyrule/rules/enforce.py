"""Can the instruction be acted on?

CLAUDE.md "content is delivered as a user message after the system prompt, not
as part of the system prompt itself. Claude reads it and tries to follow it, but
there's no guarantee of strict compliance, especially for vague or conflicting
instructions."

So an instruction written as a guarantee is not one, and an instruction with
nothing verifiable in it cannot be complied with in any checkable sense. Both
are the everyday shape of "Claude ignores my CLAUDE.md", and both have a
documented answer that is not "write it more forcefully".
"""

from __future__ import annotations

import re
from pathlib import Path

from ..instructions import extract
from ..markdown import mask_code
from ..model import Finding, MemoryFile, Severity
from ..spec import (
    CONSEQUENTIAL_PATTERN,
    LIFECYCLE_PATTERN,
    PROHIBITION_PATTERN,
    VAGUE_PHRASES,
)
from . import Context, per_file

#: Findings of one kind per file, past which the report stops being read. The
#: count of what was left out goes on the last one, so nothing is hidden.
MAX_PER_FILE = 3

#: Something concrete enough to check: a backticked token, a path, a number, or
#: a quoted string. An instruction with none of these has nothing to verify.
CONCRETE = re.compile(r"`[^`]+`|\b\d+\b|[\w.-]+/[\w./-]+|\"[^\"]+\"")

_RUNNER = re.compile(
    r"\b(?:(npm|pnpm|yarn|bun)\s+run\s+([\w:.-]+)|(make)\s+([\w:.-]+)|(npm|pnpm|yarn|bun)\s+([\w:.-]+))\b"
)
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://|^www\.", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"[<>{}*?\[\]$]|\.\.\.")

#: Package-manager subcommands that are built in rather than project-defined,
#: so naming one is never a reference to a missing script.
BUILTIN_SUBCOMMANDS = frozenset(
    """
    install i add remove rm uninstall update upgrade outdated audit ci init
    exec dlx create publish pack link unlink list ls why view info run test
    start build config cache clean version login logout whoami help
    """.split()
)


#: Suffixes common enough in a repository that a token carrying one is a file
#: reference rather than an identifier that happens to contain a slash.
SOURCE_SUFFIXES = frozenset(
    """
    .ts .tsx .js .jsx .mjs .cjs .py .rb .go .rs .java .kt .swift .c .h .cc .cpp
    .cs .php .sh .bash .zsh .sql .md .mdx .txt .json .yaml .yml .toml .ini .env
    .css .scss .html .vue .svelte .astro .lock .cfg .conf .xml .proto .graphql
    """.split()
)


def _is_repo_path(token: str, ctx: Context) -> bool:
    """True when a backticked token is a claim about a file in this repository.

    Plenty of identifiers contain a slash without being paths - model ids like
    `black-forest-labs/flux-2-max`, repository slugs, image tags. Reporting
    those as missing files is how a linter earns its `--disable` flag, so a
    token qualifies only when it carries a source-file suffix, is written as a
    directory, or starts inside a directory the project actually has.
    """
    if "/" not in token or " " in token or ":" in token:
        return False
    if token.startswith(("/", "~", "-", ".")):
        return False
    if token.endswith("/"):
        return True
    if Path(token).suffix.lower() in SOURCE_SUFFIXES:
        return True
    # `src/api/handlers` with no trailing slash is still a path claim when
    # `src/` is right there in the repository.
    first = token.split("/", 1)[0]
    return bool(first) and ctx.project is not None and (ctx.project / first).exists()


def _truncate(findings: list[Finding]) -> list[Finding]:
    """Keep the first few, and say how many were dropped."""
    if len(findings) <= MAX_PER_FILE:
        return findings
    kept = findings[:MAX_PER_FILE]
    dropped = len(findings) - MAX_PER_FILE
    last = kept[-1]
    last.message = f"{last.message} (+{dropped} more like this in the file)"
    return kept


@per_file
def unenforceable(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """ENFORCE001-003 - instructions CLAUDE.md is the wrong mechanism for."""
    if not memo.scope.loads_at_launch:
        return []

    lifecycle: list[Finding] = []
    prohibitions: list[Finding] = []
    vague: list[Finding] = []

    for directive in extract(memo):
        text = directive.text

        if LIFECYCLE_PATTERN.search(text):
            lifecycle.append(
                memo.finding(
                    "ENFORCE001",
                    Severity.WARNING,
                    f"Promises to run at a fixed point, which CLAUDE.md cannot "
                    f"guarantee: {text[:70]!r}",
                    line=directive.line,
                    mechanic=(
                        "CLAUDE.md is context, not enforced configuration. The "
                        "documentation's own answer for this shape of instruction is a "
                        "hook: if the instruction is something that must run at a "
                        "specific point, such as before every commit or after each file "
                        "edit, write it as a hook instead. Hooks execute as shell "
                        "commands at fixed lifecycle events and apply regardless of what "
                        "Claude decides."
                    ),
                    fix=(
                        "Move it to a hook - a PostToolUse hook on Edit|Write for "
                        "after-edit work, or a PreToolUse hook on Bash for pre-commit "
                        "work. Leave the reasoning here if it is worth the context."
                    ),
                )
            )
            continue

        if PROHIBITION_PATTERN.search(text) and CONSEQUENTIAL_PATTERN.search(text):
            prohibitions.append(
                memo.finding(
                    "ENFORCE002",
                    Severity.WARNING,
                    f"Forbids something with real consequences, which only permissions "
                    f"can block: {text[:70]!r}",
                    line=directive.line,
                    mechanic=(
                        "To block an action regardless of what Claude decides, use a "
                        "PreToolUse hook instead. Settings rules are enforced by the "
                        "client; CLAUDE.md instructions shape behaviour but are not a "
                        "hard enforcement layer, so this holds only as long as the model "
                        "attends to it."
                    ),
                    fix=(
                        "Add the matching entry to `permissions.deny` in settings, or a "
                        "PreToolUse hook that exits non-zero. Keep the line here as the "
                        "explanation for why the block exists."
                    ),
                )
            )
            continue

        lowered = text.lower()
        hit = next((p for p in VAGUE_PHRASES if p in lowered), None)
        if hit and not CONCRETE.search(text):
            vague.append(
                memo.finding(
                    "ENFORCE003",
                    Severity.NOTE,
                    f"Nothing here is checkable - {hit!r} in {text[:60]!r}",
                    line=directive.line,
                    mechanic=(
                        "Because CLAUDE.md is context rather than configuration, how you "
                        "write an instruction decides how reliably it is followed, and "
                        "vague instructions are named as the ones that are not. The "
                        "documented contrast: \"Use 2-space indentation\" instead of "
                        "\"Format code properly\"."
                    ),
                    fix=(
                        "Replace the adjective with the test. What would you point at in "
                        "review to say this was not done? Write that instead."
                    ),
                )
            )

    return _truncate(lifecycle) + _truncate(prohibitions) + _truncate(vague)


def _backticked(text: str) -> list[tuple[str, int]]:
    """Backticked tokens with their line numbers, code fences excluded."""
    masked = mask_code(text)
    out = []
    for index, (raw, blanked) in enumerate(zip(text.splitlines(), masked.splitlines()), start=1):
        # A line blanked by the mask is inside a fence; its contents are an
        # example, not a claim about this repository.
        if blanked.strip() == "" and raw.strip() != "":
            continue
        for token in re.findall(r"`([^`\n]+)`", raw):
            out.append((token.strip(), index))
    return out


@per_file
def dead_references(memo: MemoryFile, ctx: Context) -> list[Finding]:
    """ENFORCE004-005 - the instruction names a path or command that is not there."""
    if ctx.project is None or not memo.scope.loads_at_launch:
        return []
    # A user-scope file describes every project you work in, so a path it names
    # being absent from this one is expected, not a defect.
    if memo.scope.value.startswith("user") or memo.scope.value == "managed":
        return []

    paths: list[Finding] = []
    commands: list[Finding] = []

    for token, line in _backticked(memo.text):
        if _URL.search(token) or _PLACEHOLDER.search(token):
            continue

        runner = _RUNNER.search(token)
        if runner:
            tool = runner.group(1) or runner.group(3) or runner.group(5)
            script = runner.group(2) or runner.group(4) or runner.group(6)
            if script in BUILTIN_SUBCOMMANDS and not runner.group(2):
                continue
            known = ctx.project_scripts
            source = "package.json" if tool != "make" else "the Makefile"
            relevant = ctx.has_package_json if tool != "make" else ctx.has_makefile
            if relevant and known and script not in known:
                commands.append(
                    memo.finding(
                        "ENFORCE005",
                        Severity.WARNING,
                        f"`{token}` cannot run - {source} defines no {script!r}",
                        line=line,
                        mechanic=(
                            "An instruction naming a command that does not exist is "
                            "followed by running it and watching it fail, which costs a "
                            "turn every session. These usually date from a rename that "
                            "updated the scripts and not the CLAUDE.md."
                        ),
                        fix=f"Update the command, or add the script to {source}.",
                    )
                )
            continue

        if not _is_repo_path(token, ctx):
            continue
        candidate = ctx.project / token.rstrip("/")
        if candidate.exists():
            continue
        paths.append(
            memo.finding(
                "ENFORCE004",
                Severity.WARNING,
                f"`{token}` does not exist in the project",
                line=line,
                mechanic=(
                    "A path that has moved makes the instruction around it wrong without "
                    "making it look wrong. Claude follows it to a file that is not there "
                    "and improvises from whatever it finds instead."
                ),
                fix="Point it at the current location, or drop the instruction.",
            )
        )

    return _truncate(paths) + _truncate(commands)
