"""Hook handlers, so nobody has to remember to run whyrule.

Hooks are executed by the Claude Code harness, not chosen by the model. That
distinction matters more here than anywhere else in this project: the failure
whyrule reports is Claude not receiving an instruction, and asking Claude to
notice that would be asking it to detect its own blind spot. A hook fires
whether or not anyone thought about it.

Two events carry the work:

``PostToolUse`` (matcher ``Edit|Write``)
    Fires the moment a CLAUDE.md or a rules file is written. Exiting 2 puts
    stderr in front of Claude, so an instruction written into an HTML comment,
    or contradicting one three files away, is reported in the same turn that
    wrote it.

``SessionStart``
    Fires when a session opens. Plain stdout is injected as context, so Claude
    is told which of its own instructions never arrived - the one moment where
    that information is worth its tokens.

Three rules govern everything here, because a misbehaving hook is worse than no
hook at all:

1. **Never break the session.** Any unexpected failure exits 0 silently.
2. **Never speak unless something is wrong.** A clean run prints nothing, so it
   costs no context.
3. **Be cheap on the common path.** Most edits are not memory files, so that
   case returns before any heavy import happens.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: Severity gate for each event. SessionStart reports only what is definitely
#: broken - a warning on every session opening is noise, and noise is how a
#: useful signal gets ignored.
DEFAULT_GATES = {
    "SessionStart": "error",
    "PostToolUse": "warning",
}

_RANK = {"error": 3, "warning": 2, "note": 1}


def looks_like_memory_file(path_text: str) -> bool:
    """True for files that carry instructions into a session.

    Kept deliberately cheap: this runs after every single Edit and Write, and
    the answer is almost always no.
    """
    if not path_text:
        return False
    path = Path(path_text)
    if path.name in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"):
        return True
    return path.suffix == ".md" and "rules" in path.parts and ".claude" in path.parts


def _read_event() -> dict:
    """Parse the hook payload from stdin, tolerating anything malformed."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _project_root(event: dict) -> Path:
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path.cwd()


def _format(findings, root: Path, *, limit: int = 10) -> str:
    """Render findings as compact plain text for another model to read.

    No colour and no box drawing: the audience is Claude, and every character
    costs context.
    """
    lines: list[str] = []
    for finding in findings[:limit]:
        try:
            location = finding.path.relative_to(root)
        except ValueError:
            location = finding.path
        lines.append(f"  {location}:{finding.line}")
        lines.append(f"    {finding.rule} ({finding.severity.value}): {finding.message}")
        if finding.fix:
            lines.append(f"    fix: {finding.fix}")
    if len(findings) > limit:
        lines.append(f"  ... and {len(findings) - limit} more")
    return "\n".join(lines)


def _analyse(root: Path, *, only_path: Path | None = None):
    """Run every rule, optionally narrowing the result to one file.

    Discovery always covers the whole loaded set even when reporting on a single
    file, because a contradiction is a fact about two files and cannot be seen
    from either one alone.
    """
    # Imported here rather than at module scope so the "not a memory file" path
    # costs nothing but interpreter startup.
    from .discover import discover
    from .rules import Context, run_all
    from .settings import load as load_settings

    files = discover(root)
    findings = run_all(files, Context(project=root, settings=load_settings(root)))

    if only_path is not None:
        target = only_path.resolve()
        findings = [f for f in findings if f.path.resolve() == target or str(target) in f.related]
    return files, findings


def _gate(findings, minimum: str):
    threshold = _RANK.get(minimum, 3)
    return [f for f in findings if f.severity.rank >= threshold]


def handle_post_tool_use(event: dict, minimum: str) -> int:
    """Report on a memory file the moment it is written."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not looks_like_memory_file(file_path):
        return 0

    path = Path(file_path)
    if not path.is_file():
        return 0

    root = _project_root(event)
    _, findings = _analyse(root, only_path=path)
    findings = _gate(findings, minimum)
    if not findings:
        return 0

    body = _format(findings, root)
    errors = [f for f in findings if f.severity.value == "error"]

    if errors:
        # Exit 2 routes stderr to Claude, which is the whole point: an
        # instruction that will never be delivered was just written, and the
        # turn that wrote it is the cheapest possible moment to say so.
        sys.stderr.write(
            f"whyrule: {path.name} was written with {len(errors)} error(s) - "
            "instructions in it will not reach a session.\n"
            f"{body}\n"
            "Fix these before moving on; none of them produce an error anywhere else.\n"
        )
        return 2

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"whyrule checked {path.name} and found {len(findings)} issue(s) "
                        f"affecting whether its instructions can be followed:\n{body}"
                    ),
                }
            }
        )
    )
    return 0


def handle_session_start(event: dict, minimum: str) -> int:
    """Surface instructions that were already being dropped when the session opened."""
    root = _project_root(event)
    files, findings = _analyse(root)
    findings = _gate(findings, minimum)
    if not findings:
        return 0  # Silence is the correct output for a healthy setup.

    affected = len({f.path for f in findings})
    loaded = sum(1 for f in files if f.scope.loads_at_launch)
    # SessionStart is one of the events whose plain stdout is given to Claude as
    # context, so no JSON envelope is needed.
    print(
        f"whyrule: {affected} of {loaded} loaded memory file(s) contain instructions "
        "that cannot reach you or cannot be followed as written. These failures "
        "produce no error message anywhere.\n"
        f"{_format(findings, root)}\n"
        "Mention this to the user if it is relevant to what they ask for; "
        "`whyrule --explain` gives the full reasoning."
    )
    return 0


HANDLERS = {
    "PostToolUse": handle_post_tool_use,
    "SessionStart": handle_session_start,
}


def run(event_name: str | None = None, minimum: str | None = None) -> int:
    """Entry point for ``whyrule hook``.

    Any unexpected failure exits 0. A linter that breaks the tool it is meant to
    protect has negative value, and there is no output worth that risk.
    """
    event = _read_event()
    name = event_name or event.get("hook_event_name") or ""

    handler = HANDLERS.get(name)
    if handler is None:
        return 0

    gate = minimum or DEFAULT_GATES.get(name, "error")
    try:
        return handler(event, gate)
    except Exception as exc:  # noqa: BLE001 - deliberately total
        if os.environ.get("WHYRULE_HOOK_DEBUG"):
            sys.stderr.write(f"whyrule hook error: {exc!r}\n")
        return 0
