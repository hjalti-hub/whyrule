"""whyrule - find the CLAUDE.md instructions Claude never receives.

A memory file fails quietly. It loads or it does not, its imports resolve or
they do not, and its instructions agree with each other or they do not - and in
every case the session looks identical. This package reads the same files Claude
Code reads, in the same order, and reports only differences that are provable
from the file and its surroundings.

Public API::

    from whyrule import check
    files, findings = check(project=Path("."))
"""

from __future__ import annotations

from pathlib import Path

from .discover import discover
from .model import Finding, MemoryFile, Scope, Severity
from .report import VERSION
from .rules import Context, run_all
from .settings import load as load_settings

__version__ = VERSION
__all__ = [
    "Context",
    "Finding",
    "MemoryFile",
    "Scope",
    "Severity",
    "check",
    "discover",
    "run_all",
    "__version__",
]


def check(project: Path | None = None, **kwargs) -> tuple[list[MemoryFile], list[Finding]]:
    """Discover the memory files for ``project`` and run every rule.

    Returns both halves because a finding count means little without knowing
    what was searched: zero findings over zero files is not a clean setup.
    """
    root = (Path(project) if project is not None else Path.cwd()).resolve()
    files = discover(root, **kwargs)
    ctx = Context(project=root, settings=load_settings(root))
    return files, run_all(files, ctx)
