"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .discover import discover
from .instructions import extract_all
from .markdown import subject_words
from .model import Finding, MemoryFile
from .report import (
    VERSION,
    Style,
    rel,
    render_file_list,
    render_human,
    render_json,
    render_sarif,
    wrap_text,
)
from .rules import Context, run_all
from .rules.catalog import CATALOG, GROUPS
from .settings import load as load_settings

EPILOG = """\
examples:
  whyrule install                 let Claude check its own instructions
  whyrule                         check this project plus your personal memory
  whyrule list                    show what loads at launch, in order
  whyrule why "run npm test"      explain why one instruction is not landing
  whyrule --explain               show the documented behaviour behind each finding
  whyrule --sarif > out.sarif     emit SARIF for CI annotations
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whyrule",
        description=(
            "Find the CLAUDE.md instructions Claude never receives - files that do "
            "not load, imports that resolve to nothing, text stripped before it "
            "arrives, and rules that contradict each other once they do."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"whyrule {VERSION}")

    sub = parser.add_subparsers(dest="command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "paths",
            nargs="*",
            type=Path,
            help="CLAUDE.md files or directories. Defaults to the current project.",
        )
        p.add_argument(
            "--project",
            type=Path,
            default=None,
            help="Project root to resolve memory files and `paths:` globs against.",
        )
        p.add_argument(
            "--no-user",
            action="store_true",
            help="Skip ~/.claude. Contradictions with your personal rules go undetected.",
        )
        p.add_argument(
            "--no-subdirs",
            action="store_true",
            help="Skip CLAUDE.md files in subdirectories.",
        )
        p.add_argument(
            "--overlap",
            type=float,
            default=0.45,
            metavar="N",
            help="Similarity threshold for the CONFLICT rules, 0..1 (default: 0.45).",
        )
        p.add_argument(
            "--disable",
            default="",
            metavar="IDS",
            help="Comma-separated rule ids to suppress, e.g. WEIGHT002,ENFORCE003.",
        )
        p.add_argument(
            "--fail-on",
            choices=("error", "warning", "note", "never"),
            default="error",
            help="Lowest severity that exits non-zero (default: error).",
        )
        p.add_argument(
            "--explain", action="store_true", help="Show the mechanic behind each finding."
        )
        group = p.add_mutually_exclusive_group()
        group.add_argument("--json", action="store_true", help="Emit JSON.")
        group.add_argument("--sarif", action="store_true", help="Emit SARIF 2.1.0.")

    check = sub.add_parser("check", help="Check memory files (default).")
    add_common(check)

    why = sub.add_parser("why", help="Explain why one instruction is not being followed.")
    why.add_argument("instruction", help="Some words from the instruction, quoted.")
    add_common(why)

    sub.add_parser("rules", help="List every rule.")

    listing = sub.add_parser("list", help="Show what loads, in the order it is concatenated.")
    add_common(listing)

    installer = sub.add_parser(
        "install",
        help="Install the hooks so Claude checks its own instructions.",
        description=(
            "Register whyrule as a Claude Code hook. Once installed, memory files "
            "are checked when a session starts and whenever one is written - the "
            "harness runs it, so nobody has to remember to."
        ),
    )
    installer.add_argument(
        "--user",
        action="store_true",
        help="Install into ~/.claude/settings.json instead of this project.",
    )
    installer.add_argument(
        "--local",
        action="store_true",
        help="Use .claude/settings.local.json (not shared with the repository).",
    )
    installer.add_argument(
        "--project", type=Path, default=None, help="Project root (default: cwd)."
    )
    installer.add_argument("--uninstall", action="store_true", help="Remove the hooks.")
    installer.add_argument(
        "--status", action="store_true", help="Report whether the hooks are installed."
    )
    installer.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the resulting settings.json without writing it.",
    )

    # Invoked by Claude Code, not by people: reads the hook payload on stdin.
    hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("--event", default=None, help="Override the hook event name.")
    hook.add_argument(
        "--fail-on",
        dest="minimum",
        choices=("error", "warning", "note"),
        default=None,
        help="Lowest severity worth reporting for this event.",
    )

    return parser


#: Subcommand names, so a bare `whyrule ./docs` can default to `check`.
COMMANDS = ("check", "why", "rules", "list", "install", "hook")


def _with_default_command(argv: list[str]) -> list[str]:
    """Insert the implicit `check` subcommand.

    Positionals cannot live on both the top-level parser and its subparsers
    without the top-level one swallowing subcommand names, so the default is
    applied here rather than in argparse. Bare `whyrule` is the most common
    invocation there is, so it gets the default like everything else.
    """
    if argv and argv[0] in ("-h", "--help", "--version"):
        return argv
    first_positional = next((a for a in argv if not a.startswith("-")), None)
    if first_positional in COMMANDS:
        return argv
    return ["check", *argv]


class UsageError(Exception):
    """A bad invocation, reported without a stack trace."""


def _collect(args: argparse.Namespace) -> tuple[list[MemoryFile], Context, Path]:
    explicit = list(args.paths or [])

    # A path that does not exist is a mistake, not an empty result. Without this
    # check a mistyped subcommand is silently treated as a directory to scan and
    # reports "no memory files found" with a success exit code.
    missing = [p for p in explicit if not p.expanduser().exists()]
    if missing:
        listed = ", ".join(str(p) for p in missing)
        raise UsageError(
            f"no such file or directory: {listed}\n"
            "Run `whyrule --help` for usage, or `whyrule list` to see what is discoverable."
        )

    project = (args.project or Path.cwd()).resolve()

    files = discover(
        project=None if explicit else project,
        include_user=not args.no_user,
        include_subdirs=not args.no_subdirs,
        explicit=explicit or None,
    )

    disabled = frozenset(part.strip().upper() for part in args.disable.split(",") if part.strip())
    ctx = Context(
        project=project,
        settings=load_settings(project),
        overlap_threshold=args.overlap,
        disabled=disabled,
    )
    return files, ctx, project


def _exit_code(findings: list[Finding], fail_on: str) -> int:
    if fail_on == "never":
        return 0
    threshold = {"error": 3, "warning": 2, "note": 1}[fail_on]
    return 1 if any(f.severity.rank >= threshold for f in findings) else 0


def _emit(args, findings: list[Finding], files: list[MemoryFile], root: Path) -> None:
    if args.json:
        render_json(findings, files)
    elif args.sarif:
        render_sarif(findings, files, root=root)
    else:
        render_human(findings, files, root=root, verbose=args.explain)


def cmd_check(args: argparse.Namespace) -> int:
    files, ctx, root = _collect(args)
    findings = run_all(files, ctx)
    _emit(args, findings, files, root)
    return _exit_code(findings, args.fail_on)


def cmd_list(args: argparse.Namespace) -> int:
    files, _, root = _collect(args)
    render_file_list(files, root=root)
    return 0


def cmd_rules(_: argparse.Namespace) -> int:
    st = Style(sys.stdout)
    for prefix, heading in GROUPS.items():
        print(f"\n{st.bold(heading)}")
        for rule, summary in CATALOG.items():
            if rule.startswith(prefix):
                print(f"  {st.cyan(rule.ljust(13))}{summary}")
    print()
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    """Explain one instruction: where it lives, and what is happening to it."""
    files, ctx, root = _collect(args)
    st = Style(sys.stdout)

    query = subject_words(args.instruction)
    if not query:
        raise UsageError(
            "give me some words from the instruction, e.g. "
            'whyrule why "run npm test before committing"'
        )

    directives = extract_all(files)
    scored = sorted(
        ((len(query & d.subject) / len(query), d) for d in directives),
        key=lambda pair: -pair[0],
    )
    matches = [d for score, d in scored if score >= 0.5][:5]

    if not matches:
        print(f"No loaded instruction matches {args.instruction!r}.")
        print()
        print("That is itself an answer: if you expected one, it is either in a file")
        print("that does not load, or inside an HTML comment, or in a subdirectory")
        print("CLAUDE.md that only loads on demand. Run `whyrule list` to see what")
        print("is actually in context.")
        return 2

    findings = run_all(files, ctx)

    for directive in matches:
        print(f"\n{st.bold(directive.text)}")
        print(f"  {rel(directive.path, root)}:{directive.line}  ({directive.scope.label})")

        relevant = [
            f
            for f in findings
            if (f.path == directive.path and f.line == directive.line)
            or f"{directive.path}:{directive.line}" in f.related
        ]
        file_level = [
            f
            for f in findings
            if f.path == directive.path
            and f.rule.startswith(("LOAD", "SCOPE"))
            and f not in relevant
        ]
        relevant = file_level + relevant

        if any(f.rule.startswith(("LOAD", "REACH")) for f in relevant):
            print(f"  {st.red('This never reaches Claude.')}")
        elif any(f.rule.startswith("CONFLICT") for f in relevant):
            print(f"  {st.yellow('This arrives, but something else in context disagrees.')}")
        elif any(f.rule.startswith("ENFORCE") for f in relevant):
            print(f"  {st.yellow('This arrives, but CLAUDE.md cannot guarantee it.')}")
        elif not relevant:
            print(f"  {st.blue('Nothing is stopping this from being followed.')}")

        if not relevant:
            print(st.dim("  No findings. CLAUDE.md is context rather than enforced"))
            print(st.dim("  configuration, so if it must happen every time, a hook is"))
            print(st.dim("  the mechanism that guarantees it."))
            continue

        print()
        for finding in relevant:
            print(f"  {st.severity(finding.severity)} {st.dim(finding.rule)}  {finding.message}")
            if finding.mechanic:
                for line in wrap_text(f"why: {finding.mechanic}", 88, "      "):
                    print(st.dim(line))
            if finding.fix:
                for line in wrap_text(f"fix: {finding.fix}", 88, "      "):
                    print(st.cyan(line))
            print()

    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from .install import install, settings_path, status, uninstall

    path = settings_path(user=args.user, project=args.project, local=args.local)

    if args.status:
        code, message = status(path)
        print(message)
        return code
    if args.uninstall:
        code, message = uninstall(path)
        print(message)
        return code

    code, message = install(path, dry_run=args.print_only)
    print(message)
    return code


def cmd_hook(args: argparse.Namespace) -> int:
    from .hooks import run

    return run(event_name=args.event, minimum=args.minimum)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(_with_default_command(raw))

    command = args.command or "check"
    try:
        if command == "hook":
            return cmd_hook(args)
        if command == "install":
            return cmd_install(args)
        if command == "rules":
            return cmd_rules(args)
        if command == "list":
            return cmd_list(args)
        if command == "why":
            return cmd_why(args)
        return cmd_check(args)
    except UsageError as exc:
        print(f"whyrule: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
