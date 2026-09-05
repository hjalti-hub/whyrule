"""Tests for reading a memory file the way Claude Code reads it.

Every behaviour asserted here is a documented one - which text is masked, which
`@path` counts as an import, which comment bodies never arrive - so a failure
means whyrule has stopped modelling the loader, not that a preference changed.
"""

from __future__ import annotations

import unittest

from whyrule.markdown import (
    find_imports,
    find_stripped_comments,
    is_directive,
    is_negated,
    mask_code,
    strip_for_reading,
    subject_words,
    value_tokens,
)


class Masking(unittest.TestCase):
    def test_offsets_are_preserved(self):
        text = "before\n```\nsecret\n```\nafter\n"
        masked = mask_code(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count("\n"), text.count("\n"))
        self.assertNotIn("secret", masked)
        self.assertIn("before", masked)
        self.assertIn("after", masked)

    def test_tilde_fences_are_masked_too(self):
        self.assertNotIn("secret", mask_code("~~~\nsecret\n~~~\n"))

    def test_an_unterminated_fence_masks_to_end_of_file(self):
        self.assertNotIn("secret", mask_code("```\nsecret\n"))


class Imports(unittest.TestCase):
    def test_backticked_path_is_not_an_import(self):
        # The documented way to mention a path without importing it.
        self.assertEqual(find_imports("Write `@README` to keep it literal."), [])

    def test_bare_path_is_an_import(self):
        self.assertEqual([r.target for r in find_imports("See @README for context.")], ["README"])

    def test_path_inside_a_fence_is_not_an_import(self):
        text = "```\n@docs/example.md\n```\n@docs/real.md\n"
        self.assertEqual([r.target for r in find_imports(text)], ["docs/real.md"])

    def test_line_numbers_are_the_files_own(self):
        self.assertEqual(find_imports("one\ntwo\n@docs/three.md\n")[0].line, 3)

    def test_trailing_punctuation_is_not_part_of_the_path(self):
        found = find_imports("see @docs/setup.md, then go")
        self.assertEqual([r.target for r in found], ["docs/setup.md"])

    def test_email_address_is_not_an_import(self):
        # `@` preceded by a word character is an address, not a path.
        self.assertEqual(find_imports("mail hjalti@urru.ai"), [])

    def test_package_scope_is_an_import_because_the_loader_says_so(self):
        # Not a mistake in whyrule: this genuinely parses as an import, which is
        # exactly why IMPORT004 exists to point it out.
        self.assertEqual([r.target for r in find_imports("we pin @types/node")], ["types/node"])


class Comments(unittest.TestCase):
    def test_only_comments_outside_code_are_stripped(self):
        text = "<!-- always use pnpm -->\n\n```\n<!-- kept -->\n```\n"
        spans = find_stripped_comments(text)
        self.assertEqual(len(spans), 1)
        self.assertIn("pnpm", spans[0].text)

    def test_strip_for_reading_removes_bodies_and_keeps_shape(self):
        text = "keep me\n<!-- always use pnpm -->\nkeep me too\n"
        out = strip_for_reading(text)
        self.assertNotIn("pnpm", out)
        self.assertIn("keep me", out)
        self.assertIn("keep me too", out)
        self.assertEqual(out.count("\n"), text.count("\n"))


class DirectiveShape(unittest.TestCase):
    def test_headings_are_not_directives(self):
        self.assertFalse(is_directive("## Always run the tests"))

    def test_bullets_with_a_modal_are_directives(self):
        self.assertTrue(is_directive("- Always run the tests before pushing"))

    def test_table_rows_are_not_directives(self):
        self.assertFalse(is_directive("| always | use pnpm | here |"))

    def test_prose_without_a_modal_is_not_a_directive(self):
        self.assertFalse(is_directive("This project talks to a Postgres database."))


class Negation(unittest.TestCase):
    def test_never_is_a_negation(self):
        self.assertTrue(is_negated("Never use tabs"))

    def test_substring_matches_do_not_count(self):
        self.assertFalse(is_negated("Use annotations everywhere"))  # contains "not"
        self.assertFalse(is_negated("Use node for the runtime"))  # contains "no"


class Subjects(unittest.TestCase):
    def test_trailing_punctuation_is_dropped(self):
        words = subject_words("Always run lint before committing.")
        self.assertIn("committing", words)
        self.assertNotIn("committing.", words)

    def test_backticked_tokens_survive_whole(self):
        self.assertIn("npm run lint", subject_words("Run `npm run lint` first"))

    def test_values_pick_up_numbers_and_ticks(self):
        self.assertEqual(value_tokens("Use 2-space indentation"), frozenset({"2"}))
        self.assertIn("pnpm", value_tokens("Use `pnpm`"))


if __name__ == "__main__":
    unittest.main()
