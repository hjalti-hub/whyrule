"""Reading a memory file the way Claude Code reads it.

Two behaviours here are the reason several rules are possible at all:

* "Import parsing skips Markdown code spans and fenced code blocks." So finding
  imports means masking code first, not running a regex over raw text.
* "Block-level HTML comments (``<!-- maintainer notes -->``) in CLAUDE.md files
  are stripped before the content is injected into Claude's context." So an
  instruction inside one is invisible, and no error says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .spec import DIRECTIVE_PATTERN, IMPORT_PATTERN, NEGATIONS, STOPWORDS

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?:.|\n)*?\1")
_HTML_COMMENT = re.compile(r"<!--(?:.|\n)*?-->")
_INLINE_MD = re.compile(r"[*_~]{1,3}|\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _blank(match: re.Match) -> str:
    """Replace a span with spaces and newlines, so offsets never move."""
    return "".join("\n" if ch == "\n" else " " for ch in match.group(0))


def mask_code(text: str) -> str:
    """Blank out fenced blocks and code spans, preserving every offset.

    Returned text is the same length as ``text`` and has the same line breaks,
    so an offset found in the mask points at the same character in the original.
    """
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        match = _FENCE.match(stripped)
        if fence is None and match:
            fence = match.group(2)[0] * 3
            out.append(" " * len(stripped) + line[len(stripped) :])
            continue
        if fence is not None:
            out.append(" " * len(stripped) + line[len(stripped) :])
            if match and match.group(2).startswith(fence):
                fence = None
            continue
        out.append(line)
    masked = "".join(out)
    # Code spans are only meaningful outside a fence, which is already blanked.
    return _CODE_SPAN.sub(_blank, masked)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


@dataclass
class ImportRef:
    """One `@path` import, as written."""

    target: str
    line: int
    raw: str


def find_imports(text: str) -> list[ImportRef]:
    """Every `@path` Claude Code would treat as an import.

    Runs against masked text, so a path inside backticks is correctly ignored -
    that is the documented way to write one without importing it.
    """
    masked = mask_code(text)
    refs = []
    for match in IMPORT_PATTERN.finditer(masked):
        refs.append(
            ImportRef(
                target=match.group(1),
                line=line_of(masked, match.start()),
                raw=match.group(0),
            )
        )
    return refs


@dataclass
class CommentSpan:
    """A block-level HTML comment, which never reaches Claude."""

    line: int
    text: str


def find_stripped_comments(text: str) -> list[CommentSpan]:
    """HTML comments outside code, whose contents are dropped before injection."""
    masked = mask_code(text)
    spans = []
    for match in _HTML_COMMENT.finditer(masked):
        body = text[match.start() : match.end()]
        spans.append(CommentSpan(line=line_of(masked, match.start()), text=body))
    return spans


def strip_for_reading(text: str) -> str:
    """The text as Claude actually receives it: comments gone, code kept."""
    masked = mask_code(text)
    keep = list(text)
    for match in _HTML_COMMENT.finditer(masked):
        for i in range(match.start(), match.end()):
            if keep[i] != "\n":
                keep[i] = " "
    return "".join(keep)


def plain(line: str) -> str:
    """A line with markdown decoration removed, for phrasing checks."""
    without_bullet = _BULLET.sub("", line)
    without_heading = _HEADING.sub("", without_bullet)
    return _INLINE_MD.sub(lambda m: m.group(1) or "", without_heading).strip()


def is_directive(line: str) -> bool:
    """True when a line reads as an instruction rather than a description.

    Headings and table rows are excluded: a heading called "Never commit
    secrets" is a section label, and judging it as a rule duplicates whatever
    the section says underneath.
    """
    if _HEADING.match(line) or line.strip().startswith("|"):
        return False
    body = plain(line)
    if len(body) < 8:
        return False
    return bool(DIRECTIVE_PATTERN.search(body))


_WORD = re.compile(r"[a-z0-9][\w.\-/]*")
#: Punctuation that ends a word in prose. Left attached, "committing." and
#: "committing" are two different subjects, and two instructions that disagree
#: about the same thing stop looking alike.
_TRAILING = ".,;:!?)"
_VALUE = re.compile(r"`([^`]+)`|\b(\d+(?:\.\d+)?)\b")


def subject_words(line: str) -> frozenset[str]:
    """Content words of an instruction, for comparing two of them.

    Backticked tokens are kept whole and lowercased: `pnpm` and `npm` are the
    entire disagreement in "use pnpm" versus "use npm", and dropping the ticks
    is what makes them comparable.
    """
    ticked = [t.lower() for t in re.findall(r"`([^`]+)`", line)]
    body = plain(line).lower()
    words = set()
    for raw in _WORD.findall(body):
        word = raw.rstrip(_TRAILING)
        if len(word) > 2 and word not in STOPWORDS:
            words.add(word)
        # A token carrying a value keeps the value glued to the thing it sets,
        # so "2-space" and "4-space" share nothing. Adding the alphabetic
        # remainder lets the two be recognised as one subject set two ways -
        # which is the whole point of CONFLICT002.
        if any(ch.isdigit() for ch in word):
            stem = "".join(ch for ch in word if not ch.isdigit()).strip("-_.")
            if len(stem) > 2 and stem not in STOPWORDS:
                words.add(stem)
    words.update(t for t in ticked if t not in STOPWORDS)
    return frozenset(words)


def value_tokens(line: str) -> frozenset[str]:
    """Numbers and backticked tokens, for spotting one knob set two ways."""
    out = set()
    for ticked, number in _VALUE.findall(line):
        token = (ticked or number).strip().lower()
        if token:
            out.add(token)
    return frozenset(out)


def is_negated(line: str) -> bool:
    """True when the instruction forbids rather than requires.

    Checked on words, not substrings: "cannot" contains "not" but "annotation"
    must not count, and a bare "no" is a negation while "node" is not.
    """
    body = plain(line).lower()
    words = re.findall(r"[a-z']+", body)
    return any(word in NEGATIONS for word in words)
