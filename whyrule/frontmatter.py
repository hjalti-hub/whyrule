"""A frontmatter reader for `.claude/rules/` files.

Only rules files carry frontmatter, and only one field in it changes whether the
file loads: ``paths``. That is a small enough surface to read directly, which
keeps whyrule dependency-free - it has to run wherever `python3` runs, including
a bare CI container.

The parser is deliberately forgiving in the same places a YAML parser is strict.
A rules file whose frontmatter does not parse still loads its body, so a hard
failure here would report a problem Claude Code does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}


@dataclass
class Parsed:
    data: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    #: Line the body starts on in the original file, 1-based.
    body_line: int = 1
    has_frontmatter: bool = False
    key_lines: dict[str, int] = field(default_factory=dict)


def _scalar(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return text


def _inline_list(raw: str) -> list[Any]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [_scalar(part) for part in inner.split(",")]


def parse(text: str) -> Parsed:
    """Split frontmatter from body.

    Frontmatter counts only when the opening ``---`` is the file's first line,
    matching how every Claude Code loader reads these files.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Parsed(body=text, body_line=1)

    closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if closing is None:
        # Unterminated frontmatter: the whole file is body, `---` included.
        return Parsed(body=text, body_line=1)

    data: dict[str, Any] = {}
    key_lines: dict[str, int] = {}
    current: str | None = None

    for index in range(1, closing):
        raw = lines[index]
        line_no = index + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") or stripped == "-":
            if current is not None:
                data.setdefault(current, [])
                if isinstance(data[current], list):
                    data[current].append(_scalar(stripped[1:]))
            continue

        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        key_lines.setdefault(key, line_no)

        if not value:
            # A key with nothing after it opens a block list on the next lines.
            data[key] = []
            current = key
        elif value.startswith("[") and value.endswith("]"):
            data[key] = _inline_list(value)
            current = None
        else:
            data[key] = _scalar(value)
            current = None

    body = "\n".join(lines[closing + 1 :])
    return Parsed(
        data=data,
        body=body,
        body_line=closing + 2,
        has_frontmatter=True,
        key_lines=key_lines,
    )
