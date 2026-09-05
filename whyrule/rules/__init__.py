"""Rule registry.

Rules come in two shapes:

* **per-file** - judged from one memory file in isolation.
* **corpus** - judged from every loaded file at once. These are the rules a
  per-file linter structurally cannot implement, because whether an instruction
  survives depends on what *else* is in context beside it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable

from ..model import Finding, MemoryFile
from ..settings import Settings


@dataclass
class Context:
    """Everything a rule may need beyond the files themselves."""

    project: Path | None = None
    settings: Settings = field(default_factory=Settings)
    #: Threshold for reporting two instructions as being about one subject, 0..1.
    overlap_threshold: float = 0.45
    #: Rule ids to suppress.
    disabled: frozenset[str] = field(default_factory=frozenset)

    def enabled(self, rule: str) -> bool:
        return rule not in self.disabled

    @cached_property
    def project_scripts(self) -> frozenset[str]:
        """Runnable names the project defines: npm scripts and make targets.

        Used to tell an instruction that names a real command from one that
        names a command nobody can run. Absent files simply contribute nothing,
        so a project with neither is never reported against.
        """
        if self.project is None:
            return frozenset()
        names: set[str] = set()

        package = self.project / "package.json"
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                names.update(str(k) for k in scripts)
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

        for makefile in ("Makefile", "makefile", "GNUmakefile"):
            try:
                text = (self.project / makefile).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if line[:1].isalnum() and ":" in line and "=" not in line.split(":", 1)[0]:
                    names.add(line.split(":", 1)[0].strip())
        return frozenset(names)

    @cached_property
    def has_package_json(self) -> bool:
        return self.project is not None and (self.project / "package.json").is_file()

    @cached_property
    def has_makefile(self) -> bool:
        if self.project is None:
            return False
        return any((self.project / n).is_file() for n in ("Makefile", "makefile", "GNUmakefile"))


PerFileRule = Callable[[MemoryFile, Context], list[Finding]]
CorpusRule = Callable[[list[MemoryFile], Context], list[Finding]]

_PER_FILE: list[PerFileRule] = []
_CORPUS: list[CorpusRule] = []


def per_file(fn: PerFileRule) -> PerFileRule:
    _PER_FILE.append(fn)
    return fn


def corpus(fn: CorpusRule) -> CorpusRule:
    _CORPUS.append(fn)
    return fn


def run_all(files: list[MemoryFile], ctx: Context) -> list[Finding]:
    """Run every registered rule and return findings sorted by severity."""
    # Import for side effects: each module registers its rules on import.
    from . import conflict, enforce, imports, loading, scoping, weight  # noqa: F401

    findings: list[Finding] = []

    for memo in files:
        findings.extend(f for f in memo.parse_findings if ctx.enabled(f.rule))

    for memo in files:
        for rule in _PER_FILE:
            findings.extend(f for f in rule(memo, ctx) if ctx.enabled(f.rule))

    for rule in _CORPUS:
        findings.extend(f for f in rule(files, ctx) if ctx.enabled(f.rule))

    findings.sort(key=lambda f: f.sort_key())
    return findings


def rule_catalog() -> dict[str, str]:
    """Every rule id with a one-line summary, for ``whyrule rules``."""
    from .catalog import CATALOG

    return CATALOG
