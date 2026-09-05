"""Reading the settings that decide which memory files load.

Two keys matter:

* ``claudeMdExcludes`` - "lets you skip specific files by path or glob pattern".
  A file matched here is not loaded, and nothing in the session says so. This is
  the only way a correctly-placed CLAUDE.md can silently contribute nothing.
* ``claudeMd`` - honoured in "managed and policy settings only. Setting
  `claudeMd` in user, project, or local settings has no effect."
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Settings files, from broadest to most specific. Arrays merge across layers,
#: so every one of these can contribute a `claudeMdExcludes` pattern.
MANAGED_SETTINGS = {
    "darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
    "linux": "/etc/claude-code/managed-settings.json",
    "win32": r"C:\ProgramData\ClaudeCode\managed-settings.json",
}


def claude_home() -> Path:
    """The personal Claude Code directory, honouring ``CLAUDE_CONFIG_DIR``."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


@dataclass
class Layer:
    """One settings file that was actually present."""

    scope: str
    path: Path
    data: dict


@dataclass
class Settings:
    layers: list[Layer] = field(default_factory=list)

    @property
    def excludes(self) -> list[tuple[str, Layer]]:
        """Every `claudeMdExcludes` pattern with the layer that set it."""
        out = []
        for layer in self.layers:
            patterns = layer.data.get("claudeMdExcludes")
            if isinstance(patterns, list):
                out.extend((p, layer) for p in patterns if isinstance(p, str) and p)
        return out

    def ineffective_claude_md(self) -> list[Layer]:
        """Layers setting `claudeMd` where the key does nothing."""
        return [
            layer
            for layer in self.layers
            if "claudeMd" in layer.data and layer.scope not in ("managed", "policy")
        ]


def _read(path: Path, scope: str) -> Layer | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # A settings file Claude Code cannot parse is not whyrule's to report;
        # `claude doctor` covers it, and guessing at intent here would be worse.
        return None
    if not isinstance(data, dict):
        return None
    return Layer(scope=scope, path=path, data=data)


def load(project: Path | None) -> Settings:
    """Read every settings layer that exists, in load order."""
    candidates: list[tuple[str, Path]] = []

    managed = MANAGED_SETTINGS.get(sys.platform)
    if managed:
        candidates.append(("managed", Path(managed)))

    candidates.append(("user", claude_home() / "settings.json"))

    if project is not None:
        candidates.append(("project", project / ".claude" / "settings.json"))
        candidates.append(("local", project / ".claude" / "settings.local.json"))

    layers = [layer for scope, path in candidates if (layer := _read(path, scope)) is not None]
    return Settings(layers=layers)
