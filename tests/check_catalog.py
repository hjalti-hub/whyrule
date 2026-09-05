#!/usr/bin/env python3
"""Check that the rule catalog and the rules themselves agree.

The catalog is what `whyrule rules`, the SARIF output and the README all read
from, so a rule that exists in code but not in the catalog is invisible in three
places at once - and a catalog entry with no rule behind it is a promise the
tool does not keep. Neither drift produces a test failure on its own, which is
why this runs in CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whyrule.rules.catalog import CATALOG, GROUPS  # noqa: E402

RULE_ID = re.compile(r'"((?:LOAD|REACH|IMPORT|SCOPE|CONFLICT|ENFORCE|WEIGHT)\d{3})"')


def main() -> int:
    source_root = Path(__file__).resolve().parent.parent / "whyrule"
    emitted: set[str] = set()
    for path in source_root.rglob("*.py"):
        if path.name == "catalog.py":
            continue
        emitted.update(RULE_ID.findall(path.read_text(encoding="utf-8")))

    catalogued = set(CATALOG)
    problems = []

    for rule in sorted(emitted - catalogued):
        problems.append(f"{rule} is emitted by the rules but missing from the catalog")
    for rule in sorted(catalogued - emitted):
        problems.append(f"{rule} is in the catalog but nothing emits it")
    for rule in sorted(catalogued):
        if not any(rule.startswith(prefix) for prefix in GROUPS):
            problems.append(f"{rule} belongs to no group, so `whyrule rules` will not print it")

    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    print(f"catalog and rules agree on {len(catalogued)} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
