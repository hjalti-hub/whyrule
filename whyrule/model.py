"""Core data types shared across whyrule.

Every finding whyrule emits must describe a *silent* failure: something that
changes whether an instruction reaches Claude, or whether it can be followed
once it does, without Claude Code printing an error. That constraint is enforced
in review rather than mechanically, which is why each Finding carries a
``mechanic``: the documented behaviour the rule is derived from.

The central difference from a skill linter is that memory files do not override
each other. "All discovered files are concatenated into context rather than
overriding each other" - so the failure mode is not shadowing, it is two
instructions arriving together and disagreeing.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Severity(enum.Enum):
    """How badly the instruction is affected.

    ``ERROR``   the text never reaches Claude, or cannot be acted on at all
    ``WARNING`` it reaches Claude but is unreliable - contradicted, unenforceable
    ``NOTE``    intentional configurations worth surfacing when you are asking
                "why isn't it following this?"
    """

    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "note": 1}[self.value]

    # SARIF only defines error/warning/note/none, which happens to match.
    @property
    def sarif_level(self) -> str:
        return self.value


class Scope(enum.Enum):
    """Where a memory file was found, which determines when it loads.

    Ordered as the documentation orders them, "from broadest scope to most
    specific, so a project instruction appears in context after a user
    instruction". Later text is read last; it does not win automatically.
    """

    MANAGED = "managed"
    USER = "user"
    USER_RULE = "user-rule"
    ANCESTOR = "ancestor"
    PROJECT = "project"
    PROJECT_RULE = "project-rule"
    LOCAL = "local"
    SUBDIR = "subdir"
    IMPORT = "import"
    FOREIGN = "foreign"

    @property
    def load_order(self) -> int:
        """Position in the concatenated context, lowest first."""
        return {
            "managed": 0,
            "user": 10,
            "user-rule": 20,
            "ancestor": 30,
            "project": 40,
            "project-rule": 50,
            "local": 60,
            "import": 70,  # expanded in place; ordered after for reporting only
            "subdir": 80,  # on demand, not at launch
            "foreign": 90,  # not loaded at all
        }[self.value]

    @property
    def loads_at_launch(self) -> bool:
        """True when the file enters context at session start.

        Subdirectory files "are included when Claude reads files in those
        subdirectories", and foreign files are never read, so neither counts
        towards the launch context an instruction has to compete inside.
        """
        return self not in (Scope.SUBDIR, Scope.FOREIGN)

    @property
    def label(self) -> str:
        return {
            "managed": "managed policy",
            "user": "user",
            "user-rule": "user rule",
            "ancestor": "ancestor directory",
            "project": "project",
            "project-rule": "project rule",
            "local": "local",
            "subdir": "subdirectory (on demand)",
            "import": "imported",
            "foreign": "not read by Claude Code",
        }[self.value]


@dataclass
class Finding:
    """One diagnosed silent failure."""

    rule: str
    severity: Severity
    message: str
    path: Path
    line: int = 1
    #: The documented Claude Code behaviour this rule is derived from.
    mechanic: str = ""
    #: Concrete remediation.
    fix: str = ""
    #: Other files implicated, for cross-file rules. Rendered as `path:line`.
    related: list[str] = field(default_factory=list)

    #: Rule groups, ordered so root causes are reported before their symptoms: a
    #: file that never loads explains every other complaint about its contents.
    _GROUP_ORDER = ("LOAD", "REACH", "IMPORT", "SCOPE", "CONFLICT", "ENFORCE", "WEIGHT")

    def sort_key(self) -> tuple:
        group = next(
            (i for i, g in enumerate(self._GROUP_ORDER) if self.rule.startswith(g)),
            len(self._GROUP_ORDER),
        )
        return (-self.severity.rank, str(self.path), group, self.line, self.rule)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "path": str(self.path),
            "line": self.line,
        }
        if self.mechanic:
            out["mechanic"] = self.mechanic
        if self.fix:
            out["fix"] = self.fix
        if self.related:
            out["related"] = list(self.related)
        return out


@dataclass
class Directive:
    """One instruction, extracted from a memory file for comparison.

    ``subject`` is the content-word set the contradiction rules compare on.
    Comparing raw text finds nothing, because two instructions that disagree are
    rarely phrased alike - "always use pnpm" and "never use pnpm, npm only"
    share only the words that matter.
    """

    text: str
    path: Path
    line: int
    scope: Scope
    #: True when the instruction is phrased as a prohibition.
    negated: bool = False
    #: Content words, stopwords removed, used for overlap comparison.
    subject: frozenset[str] = field(default_factory=frozenset)
    #: Numbers and backticked tokens, used to spot two rules setting one knob
    #: to different values.
    values: frozenset[str] = field(default_factory=frozenset)

    def overlap(self, other: Directive) -> float:
        """Jaccard similarity of the two subjects, 0..1."""
        if not self.subject or not other.subject:
            return 0.0
        union = self.subject | other.subject
        return len(self.subject & other.subject) / len(union)


@dataclass
class MemoryFile:
    """A discovered memory file, parsed but not yet judged."""

    path: Path
    scope: Scope
    text: str
    #: Frontmatter, for `.claude/rules/` files. Empty for CLAUDE.md.
    frontmatter: dict[str, Any] = field(default_factory=dict)
    #: Line number of each frontmatter key, for precise reporting.
    key_lines: dict[str, int] = field(default_factory=dict)
    #: Line the body starts on, so reported lines match the file.
    body_line: int = 1
    #: Size on disk. Measured, not estimated - a 4 MiB file is skipped whole.
    size_bytes: int = 0
    #: For imported files: what imported this, and how many hops in it sits.
    imported_by: Path | None = None
    depth: int = 0
    #: Diagnostics raised while reading, promoted to findings later.
    parse_findings: list[Finding] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.text.count("\n") + 1 if self.text else 0

    @property
    def paths_globs(self) -> list[str]:
        """The `paths:` list from a rules file, normalised to a list."""
        value = self.frontmatter.get("paths")
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [v for v in value if isinstance(v, str) and v.strip()]
        return []

    def finding(
        self,
        rule: str,
        severity: Severity,
        message: str,
        *,
        mechanic: str = "",
        fix: str = "",
        line: int = 1,
        related: list[str] | None = None,
    ) -> Finding:
        return Finding(
            rule=rule,
            severity=severity,
            message=message,
            path=self.path,
            line=line,
            mechanic=mechanic,
            fix=fix,
            related=related or [],
        )
