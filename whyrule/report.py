"""Rendering findings for humans and for machines."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from .model import Finding, MemoryFile, Severity

VERSION = "0.1.0"


class Style:
    """ANSI colours, switched off when the output is not a terminal."""

    def __init__(self, stream: TextIO, force: bool | None = None) -> None:
        if force is None:
            enabled = (
                hasattr(stream, "isatty")
                and stream.isatty()
                and os.environ.get("NO_COLOR") is None
                and os.environ.get("TERM") != "dumb"
            )
        else:
            enabled = force
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def blue(self, t: str) -> str:
        return self._wrap("34", t)

    def cyan(self, t: str) -> str:
        return self._wrap("36", t)

    def severity(self, sev: Severity) -> str:
        return {
            Severity.ERROR: self.red("error"),
            Severity.WARNING: self.yellow("warning"),
            Severity.NOTE: self.blue("note"),
        }[sev]


def wrap_text(text: str, width: int, indent: str) -> list[str]:
    """Naive word wrap; avoids a textwrap import for two call sites' sake."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else f"{indent}{word}"
        if len(candidate) > width and current:
            lines.append(current)
            current = f"{indent}{word}"
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def rel(path: Path, root: Path | None) -> str:
    """A path relative to the project when it is inside it, absolute otherwise.

    Memory files legitimately live outside the project - `~/.claude/CLAUDE.md`
    is the common case - and shortening those to `../../..` helps nobody.
    """
    if root is None:
        return str(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        home = Path.home()
        try:
            return "~/" + str(path.relative_to(home))
        except ValueError:
            return str(path)


def render_human(
    findings: list[Finding],
    files: list[MemoryFile],
    *,
    stream: TextIO | None = None,
    root: Path | None = None,
    verbose: bool = False,
    width: int = 88,
) -> None:
    stream = stream or sys.stdout
    st = Style(stream)

    if not files:
        stream.write(
            "No memory files found. Run whyrule from a project with a CLAUDE.md, "
            "or point it at one.\n"
        )
        return

    loaded = sum(1 for f in files if f.scope.loads_at_launch)
    if not findings:
        stream.write(
            st.bold(f"✓ {len(files)} memory file{'s' if len(files) != 1 else ''} checked, ")
            + st.bold("nothing silently dropped or contradicted.\n")
        )
        return

    by_file: dict[Path, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_file[finding.path].append(finding)

    #: Worst file first. Alphabetical order buries the file that cannot load
    #: under one whose only complaint is a long line, and the first screen is
    #: the only part of a report most people read.
    order = {memo.path: memo.scope.load_order for memo in files}

    def worst_first(path: Path) -> tuple:
        return (
            -max(f.severity.rank for f in by_file[path]),
            -len(by_file[path]),
            order.get(path, 99),
            str(path),
        )

    for path in sorted(by_file, key=worst_first):
        stream.write(f"\n{st.bold(rel(path, root))}\n")
        for finding in by_file[path]:
            location = st.dim(f"{finding.line}:")
            stream.write(
                f"  {location} {st.severity(finding.severity)} "
                f"{st.dim(finding.rule)}  {finding.message}\n"
            )
            if verbose and finding.mechanic:
                for line in wrap_text(finding.mechanic, width, "      "):
                    stream.write(st.dim(line) + "\n")
            if finding.related:
                for other in finding.related[:3]:
                    stream.write(st.dim(f"      also: {rel(Path(other), root)}\n"))
            if finding.fix:
                for line in wrap_text(f"fix: {finding.fix}", width, "      "):
                    stream.write(st.cyan(line) + "\n")

    counts: dict[Severity, int] = defaultdict(int)
    for finding in findings:
        counts[finding.severity] += 1

    parts = []
    if counts[Severity.ERROR]:
        parts.append(st.red(f"{counts[Severity.ERROR]} error(s)"))
    if counts[Severity.WARNING]:
        parts.append(st.yellow(f"{counts[Severity.WARNING]} warning(s)"))
    if counts[Severity.NOTE]:
        parts.append(st.blue(f"{counts[Severity.NOTE]} note(s)"))

    stream.write(
        f"\n{st.bold(' · '.join(parts))} across {len(files)} memory file"
        f"{'s' if len(files) != 1 else ''} ({loaded} loaded at launch)\n"
    )
    if not verbose:
        stream.write(st.dim("Run with --explain to see why each one matters.\n"))


def render_json(findings: list[Finding], files: list[MemoryFile], stream: TextIO | None = None):
    stream = stream or sys.stdout
    payload = {
        "version": VERSION,
        "summary": {
            "files": len(files),
            "loaded_at_launch": sum(1 for f in files if f.scope.loads_at_launch),
            "lines_at_launch": sum(f.line_count for f in files if f.scope.loads_at_launch),
            "errors": sum(1 for f in findings if f.severity is Severity.ERROR),
            "warnings": sum(1 for f in findings if f.severity is Severity.WARNING),
            "notes": sum(1 for f in findings if f.severity is Severity.NOTE),
        },
        "files": [
            {
                "path": str(f.path),
                "scope": f.scope.value,
                "lines": f.line_count,
                "bytes": f.size_bytes,
                "loads_at_launch": f.scope.loads_at_launch,
                **({"imported_by": str(f.imported_by)} if f.imported_by else {}),
            }
            for f in files
        ],
        "findings": [f.to_dict() for f in findings],
    }
    json.dump(payload, stream, indent=2)
    stream.write("\n")


def render_sarif(
    findings: list[Finding],
    files: list[MemoryFile],
    stream: TextIO | None = None,
    root: Path | None = None,
) -> None:
    """SARIF 2.1.0, so CI can annotate the offending lines in a diff."""
    from .rules.catalog import CATALOG

    stream = stream or sys.stdout
    rules = [
        {
            "id": rule,
            "shortDescription": {"text": CATALOG.get(rule, rule)},
            "helpUri": "https://code.claude.com/docs/en/memory",
        }
        for rule in sorted({f.rule for f in findings})
    ]

    results = []
    for finding in findings:
        text = finding.message
        if finding.fix:
            text += f"\n\nFix: {finding.fix}"
        results.append(
            {
                "ruleId": finding.rule,
                "level": finding.severity.sarif_level,
                "message": {"text": text},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": rel(finding.path, root)},
                            "region": {"startLine": max(1, finding.line)},
                        }
                    }
                ],
            }
        )

    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "whyrule",
                        "version": VERSION,
                        "informationUri": "https://github.com/hjalti-hub/whyrule",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    json.dump(doc, stream, indent=2)
    stream.write("\n")


def render_file_list(
    files: Iterable[MemoryFile], stream: TextIO | None = None, root: Path | None = None
) -> None:
    """What loads, in the order it is concatenated into context."""
    stream = stream or sys.stdout
    st = Style(stream)
    rows = sorted(files, key=lambda m: (m.scope.load_order, str(m.path)))
    if not rows:
        stream.write("No memory files found.\n")
        return

    width = max(len(rel(m.path, root)) for m in rows) + 2
    total = 0
    for memo in rows:
        marker = " " if memo.scope.loads_at_launch else st.dim("·")
        if memo.scope.loads_at_launch:
            total += memo.line_count
        detail = f"{memo.scope.label}"
        if memo.imported_by is not None:
            detail += f" via {memo.imported_by.name}, {memo.depth} hop(s)"
        stream.write(
            f" {marker} {rel(memo.path, root).ljust(width)}"
            f"{st.dim(detail.ljust(30))}{st.dim(str(memo.line_count) + ' lines')}\n"
        )
    stream.write(st.bold(f"\n{total} lines load at launch.\n"))
    stream.write(st.dim("Lines marked · are not in the launch context.\n"))
