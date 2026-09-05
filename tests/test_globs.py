"""Tests for glob handling.

`fnmatch` is not used here because it lets `*` cross directory separators, which
would make a path-scoped rule that never fires look like one that fires
everywhere. These tests pin that difference down.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from whyrule.globs import (
    InvalidPattern,
    any_project_file_matches,
    compile_all,
    expand_braces,
    matches,
    translate,
)


class SingleStar(unittest.TestCase):
    def test_does_not_cross_a_separator(self):
        pattern = translate("src/*.ts")
        self.assertTrue(pattern.match("src/a.ts"))
        self.assertFalse(pattern.match("src/api/a.ts"))

    def test_root_level_markdown(self):
        pattern = translate("*.md")
        self.assertTrue(pattern.match("README.md"))
        self.assertFalse(pattern.match("docs/README.md"))


class DoubleStar(unittest.TestCase):
    def test_crosses_separators(self):
        pattern = translate("src/**/*.ts")
        self.assertTrue(pattern.match("src/api/deep/a.ts"))

    def test_matches_zero_directories(self):
        # `**/*.ts` has to match a file at the root as well as a nested one.
        pattern = translate("**/*.ts")
        self.assertTrue(pattern.match("a.ts"))
        self.assertTrue(pattern.match("src/a.ts"))

    def test_everything_under_a_directory(self):
        pattern = translate("src/**/*")
        self.assertTrue(pattern.match("src/a.ts"))
        self.assertTrue(pattern.match("src/api/a.ts"))


class Brackets(unittest.TestCase):
    def test_a_bracket_expression_works(self):
        self.assertTrue(translate("a[bc].ts").match("ab.ts"))

    def test_an_unclosed_bracket_is_invalid(self):
        with self.assertRaises(InvalidPattern):
            translate("photos [2024/**")

    def test_an_escaped_bracket_is_literal(self):
        self.assertTrue(translate(r"photos \[2024/**").match("photos [2024/a.jpg"))


class Braces(unittest.TestCase):
    def test_expansion_multiplies(self):
        expanded, _ = expand_braces("src/*.{ts,tsx}", 1000)
        self.assertEqual(sorted(expanded), ["src/*.ts", "src/*.tsx"])

    def test_nested_groups_multiply_together(self):
        expanded, _ = expand_braces("{a,b}/{c,d}/*.{ts,tsx}", 1000)
        self.assertEqual(len(expanded), 8)

    def test_budget_returns_the_pattern_unexpanded(self):
        # Which is what Claude Code does, and the literal braces then match no
        # file - the behaviour SCOPE002 exists to report.
        expanded, _ = expand_braces("{a,b}/{c,d}/*.{ts,tsx}", 4)
        self.assertEqual(expanded, ["{a,b}/{c,d}/*.{ts,tsx}"])

    def test_the_budget_is_shared_across_the_whole_list(self):
        big = "{a,b,c,d,e,f,g,h,i,j}/" * 4 + "*.ts"
        _, over_budget, _ = compile_all([big, big])
        self.assertTrue(over_budget)


class ProjectMatching(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "src" / "api").mkdir(parents=True)
        (self.root / "src" / "api" / "handler.ts").write_text("export {}\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_matching_pattern_is_found(self):
        matchers, _, _ = compile_all(["src/**/*.ts"])
        self.assertTrue(any_project_file_matches(self.root, matchers))

    def test_a_non_matching_pattern_is_not(self):
        matchers, _, _ = compile_all(["src/handlers/**/*.ts"])
        self.assertFalse(any_project_file_matches(self.root, matchers))

    def test_pruned_directories_are_not_searched(self):
        vendored = self.root / "node_modules" / "pkg"
        vendored.mkdir(parents=True)
        (vendored / "index.mjs").write_text("export {}\n")
        matchers, _, _ = compile_all(["**/*.mjs"])
        self.assertFalse(any_project_file_matches(self.root, matchers))

    def test_matches_helper_accepts_any(self):
        matchers, _, _ = compile_all(["*.md", "*.ts"])
        self.assertTrue(matches("a.ts", matchers))
        self.assertFalse(matches("a.py", matchers))


if __name__ == "__main__":
    unittest.main()
