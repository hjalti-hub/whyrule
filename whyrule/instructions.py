"""Pulling the instructions out of a memory file.

A CLAUDE.md is mostly prose. Judging every line as a rule produces noise, and
noise is what makes a linter get uninstalled - so a line becomes a Directive
only when it carries a modal cue ("always", "never", "must", "use", "run") and
is not a heading or a table row.

Comparison then happens on content words rather than raw text, because two
instructions that disagree are rarely phrased alike. "Always use `pnpm`" and
"Never use `pnpm`, npm only" share almost nothing as strings and everything as
subjects.
"""

from __future__ import annotations

from .markdown import (
    is_directive,
    is_negated,
    plain,
    strip_for_reading,
    subject_words,
    value_tokens,
)
from .model import Directive, MemoryFile


def extract(memo: MemoryFile) -> list[Directive]:
    """Every instruction in a file, as Claude receives it.

    Runs against the stripped text, so an instruction inside an HTML comment is
    not compared against anything - it never arrives, which REACH001 reports
    separately and which would otherwise produce a phantom contradiction.
    """
    text = strip_for_reading(memo.text)
    offset = memo.body_line - 1 if memo.body_line > 1 else 0
    body = text.split("\n", offset)[-1] if offset else text

    directives: list[Directive] = []
    for index, line in enumerate(body.splitlines(), start=offset + 1):
        if not is_directive(line):
            continue
        subject = subject_words(line)
        if len(subject) < 2:
            continue  # Nothing distinctive enough to compare against.
        directives.append(
            Directive(
                text=plain(line),
                path=memo.path,
                line=index,
                scope=memo.scope,
                negated=is_negated(line),
                subject=subject,
                values=value_tokens(line),
            )
        )
    return directives


def extract_all(files: list[MemoryFile]) -> list[Directive]:
    """Instructions from every file that is in context at launch."""
    out: list[Directive] = []
    for memo in files:
        if memo.scope.loads_at_launch:
            out.extend(extract(memo))
    return out


def candidate_pairs(directives: list[Directive], minimum_shared: int = 2):
    """Pairs worth comparing, found through an inverted index.

    Comparing every pair is quadratic and most pairs share no words at all, so
    pairs are drawn from an index on content words. Very common words are
    skipped as index keys: a word appearing in most instructions produces a
    bucket the size of the whole corpus and puts the quadratic cost back.
    """
    index: dict[str, list[int]] = {}
    for position, directive in enumerate(directives):
        for word in directive.subject:
            index.setdefault(word, []).append(position)

    ceiling = max(12, len(directives) // 4)
    seen: set[tuple[int, int]] = set()
    counts: dict[tuple[int, int], int] = {}

    for bucket in index.values():
        if len(bucket) > ceiling:
            continue
        for i, left in enumerate(bucket):
            for right in bucket[i + 1 :]:
                counts[(left, right)] = counts.get((left, right), 0) + 1

    for pair, shared in counts.items():
        if shared >= minimum_shared and pair not in seen:
            seen.add(pair)
            yield directives[pair[0]], directives[pair[1]]
