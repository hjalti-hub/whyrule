"""Tests for the rules themselves.

Each test builds the smallest tree of real files that triggers one rule, so a
failure names exactly one broken behaviour. Rules are asserted in both
directions wherever a false positive would be costly: the rule fires when it
should, and stays silent when it should not.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from whyrule.discover import discover
from whyrule.rules import Context, run_all
from whyrule.settings import Layer, Settings


class RuleCase(unittest.TestCase):
    """Base class providing a scratch project tree."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / ".claude").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_rules(self, *, settings: Settings | None = None, overlap: float = 0.45, **kwargs):
        files = discover(self.root, include_user=False, **kwargs)
        # A developer machine may have a CLAUDE.md in an ancestor of the temp
        # directory; excluding those keeps the suite deterministic.
        files = [f for f in files if str(f.path).startswith(str(self.root))]
        ctx = Context(
            project=self.root,
            settings=settings or Settings(),
            overlap_threshold=overlap,
        )
        return files, run_all(files, ctx)

    def fired(self, **kwargs) -> set:
        _, findings = self.run_rules(**kwargs)
        return {f.rule for f in findings}

    def messages(self, rule: str, **kwargs) -> list:
        _, findings = self.run_rules(**kwargs)
        return [f.message for f in findings if f.rule == rule]


class CleanProject(RuleCase):
    def test_a_reasonable_claude_md_produces_nothing(self):
        self.write("package.json", '{"scripts": {"test": "vitest run"}}')
        self.write("src/api/index.ts", "export const x = 1\n")
        self.write(
            "CLAUDE.md",
            "# Example\n\n"
            "- Use 2-space indentation in TypeScript files.\n"
            "- API handlers live in `src/api/`.\n"
            "- Run `npm test` to check a change.\n",
        )
        self.assertEqual(self.fired(), set())


class Loading(RuleCase):
    def test_oversized_file_is_skipped_whole(self):
        self.write("CLAUDE.md", "x" * (4 * 1024 * 1024 + 1))
        self.assertIn("LOAD001", self.fired())

    def test_a_file_just_under_the_limit_is_fine(self):
        self.write("CLAUDE.md", "x" * (4 * 1024 * 1024))
        self.assertNotIn("LOAD001", self.fired())

    def test_claude_md_excludes_pattern_is_reported(self):
        self.write("CLAUDE.md", "- Always use tabs\n")
        settings = Settings(
            layers=[
                Layer(
                    scope="local",
                    path=self.root / ".claude" / "settings.local.json",
                    data={"claudeMdExcludes": ["**/CLAUDE.md"]},
                )
            ]
        )
        self.assertIn("LOAD002", self.fired(settings=settings))

    def test_a_non_matching_exclude_is_silent(self):
        self.write("CLAUDE.md", "- Always use tabs\n")
        settings = Settings(
            layers=[
                Layer(
                    scope="local",
                    path=self.root / ".claude" / "settings.local.json",
                    data={"claudeMdExcludes": ["**/other/CLAUDE.md"]},
                )
            ]
        )
        self.assertNotIn("LOAD002", self.fired(settings=settings))

    def test_agents_md_alone_is_never_read(self):
        self.write("AGENTS.md", "- Always run the seed script\n")
        self.assertIn("LOAD003", self.fired())

    def test_agents_md_imported_by_claude_md_is_fine(self):
        self.write("AGENTS.md", "- Always run the seed script\n")
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertNotIn("LOAD003", self.fired())

    def test_claude_md_key_in_project_settings_does_nothing(self):
        self.write("CLAUDE.md", "hello\n")
        settings = Settings(
            layers=[
                Layer(
                    scope="project",
                    path=self.root / ".claude" / "settings.json",
                    data={"claudeMd": "Always run make lint."},
                )
            ]
        )
        self.assertIn("LOAD004", self.fired(settings=settings))

    def test_claude_md_key_in_managed_settings_is_honoured(self):
        self.write("CLAUDE.md", "hello\n")
        settings = Settings(
            layers=[Layer(scope="managed", path=Path("/managed.json"), data={"claudeMd": "x"})]
        )
        self.assertNotIn("LOAD004", self.fired(settings=settings))


class Reach(RuleCase):
    def test_instruction_in_a_comment_is_reported(self):
        self.write("CLAUDE.md", "# P\n\n<!--\n- Always use `pnpm`, never npm.\n-->\n")
        self.assertIn("REACH001", self.fired())

    def test_a_plain_maintainer_note_is_not_reported(self):
        self.write("CLAUDE.md", "# P\n\n<!-- last reviewed 2026-01-01 -->\n")
        self.assertNotIn("REACH001", self.fired())

    def test_a_comment_inside_a_fence_is_not_reported(self):
        self.write("CLAUDE.md", "# P\n\n```html\n<!-- Always use pnpm here -->\n```\n")
        self.assertNotIn("REACH001", self.fired())


class Imports(RuleCase):
    def test_missing_target_is_an_error(self):
        self.write("CLAUDE.md", "See @docs/missing.md for details.\n")
        self.assertIn("IMPORT001", self.fired())

    def test_present_target_is_silent(self):
        self.write("docs/present.md", "- Use tabs\n")
        self.write("CLAUDE.md", "See @docs/present.md for details.\n")
        self.assertNotIn("IMPORT001", self.fired())

    def test_relative_paths_resolve_against_the_importing_file(self):
        # Not against the working directory - the documented behaviour, and the
        # easiest one to get wrong in a way that reports a working import.
        self.write("docs/child.md", "- Use tabs\n")
        self.write("docs/parent.md", "@child.md\n")
        self.write("CLAUDE.md", "@docs/parent.md\n")
        self.assertNotIn("IMPORT001", self.fired())

    def test_package_scope_in_prose_is_reported_as_prose(self):
        self.write("CLAUDE.md", "We pin @types/node deliberately.\n")
        fired = self.fired()
        self.assertIn("IMPORT004", fired)
        self.assertNotIn("IMPORT001", fired)

    def test_chain_past_four_hops_is_reported(self):
        self.write("h4.md", "@h5.md\n")
        self.write("h5.md", "- Use tabs\n")
        self.write("h3.md", "@h4.md\n")
        self.write("h2.md", "@h3.md\n")
        self.write("h1.md", "@h2.md\n")
        self.write("CLAUDE.md", "@h1.md\n")
        self.assertIn("IMPORT002", self.fired())

    def test_a_short_chain_is_silent(self):
        self.write("h2.md", "- Use tabs\n")
        self.write("h1.md", "@h2.md\n")
        self.write("CLAUDE.md", "@h1.md\n")
        self.assertNotIn("IMPORT002", self.fired())

    def test_a_cycle_is_reported(self):
        self.write("a.md", "@b.md\n")
        self.write("b.md", "@a.md\n")
        self.write("CLAUDE.md", "@a.md\n")
        self.assertIn("IMPORT003", self.fired())

    def test_an_import_outside_the_project_is_noted(self):
        self.write("CLAUDE.md", "@~/.claude/shared.md\n")
        self.assertIn("IMPORT005", self.fired())

    def test_a_symlinked_project_root_does_not_make_imports_external(self):
        # On macOS /tmp is a symlink to /private/tmp, so an unresolved project
        # root fails every containment check and every import looks external.
        self.write("docs/inside.md", "- Use tabs\n")
        self.write("CLAUDE.md", "@docs/inside.md\n")
        link = Path(tempfile.mkdtemp()).resolve() / "link"
        link.symlink_to(self.root)
        try:
            files = discover(link, include_user=False)
            files = [
                f for f in files if "link" in str(f.path) or str(f.path).startswith(str(self.root))
            ]
            ctx = Context(project=link, settings=Settings())
            fired = {f.rule for f in run_all(files, ctx)}
            self.assertNotIn("IMPORT005", fired)
        finally:
            shutil.rmtree(link.parent, ignore_errors=True)


class Scoping(RuleCase):
    def test_globs_matching_nothing_never_load(self):
        self.write("src/api/handler.ts", "export {}\n")
        self.write(
            ".claude/rules/api.md",
            '---\npaths:\n  - "src/handlers/**/*.ts"\n---\n\n- Validate every input.\n',
        )
        self.assertIn("SCOPE001", self.fired())

    def test_globs_that_match_are_silent(self):
        self.write("src/api/handler.ts", "export {}\n")
        self.write(
            ".claude/rules/api.md",
            '---\npaths:\n  - "src/**/*.ts"\n---\n\n- Validate every input.\n',
        )
        self.assertNotIn("SCOPE001", self.fired())

    def test_a_rule_without_paths_loads_unconditionally(self):
        self.write(".claude/rules/style.md", "- Use 2-space indentation.\n")
        self.assertNotIn("SCOPE001", self.fired())

    def test_an_unclosed_bracket_matches_nothing(self):
        self.write("src/a.ts", "export {}\n")
        self.write(
            ".claude/rules/x.md",
            '---\npaths:\n  - "photos [2024/**"\n---\n\n- Always compress images.\n',
        )
        self.assertIn("SCOPE003", self.fired())


class Conflicts(RuleCase):
    def test_opposite_polarity_on_one_subject_is_reported(self):
        self.write("CLAUDE.md", "- Always run `npm run lint` before committing.\n")
        self.write("CLAUDE.local.md", "- Never run `npm run lint` before committing.\n")
        self.assertIn("CONFLICT001", self.fired())

    def test_two_unrelated_instructions_are_silent(self):
        self.write("CLAUDE.md", "- Always use 2-space indentation in TypeScript.\n")
        self.write("CLAUDE.local.md", "- Never deploy on a Friday afternoon.\n")
        self.assertNotIn("CONFLICT001", self.fired())

    def test_one_setting_with_two_values_is_reported(self):
        self.write("CLAUDE.md", "- Use 2-space indentation in TypeScript files.\n")
        self.write("CLAUDE.local.md", "- Use 4-space indentation in TypeScript files.\n")
        self.assertIn("CONFLICT002", self.fired())

    def test_the_same_instruction_twice_is_a_note(self):
        line = "- Always use `pnpm` for installing dependencies here.\n"
        self.write("CLAUDE.md", line)
        self.write("CLAUDE.local.md", line)
        self.assertIn("CONFLICT003", self.fired())

    def test_an_instruction_in_a_comment_cannot_contradict_anything(self):
        # It never arrives, so pairing it with a live instruction would invent a
        # conflict that does not exist in any session.
        self.write("CLAUDE.md", "- Always run `npm run lint` before committing.\n")
        self.write("CLAUDE.local.md", "<!--\n- Never run `npm run lint` before committing.\n-->\n")
        self.assertNotIn("CONFLICT001", self.fired())


class Enforceability(RuleCase):
    def test_a_lifecycle_promise_is_reported(self):
        self.write("CLAUDE.md", "- Run `git status` after each file edit.\n")
        self.assertIn("ENFORCE001", self.fired())

    def test_a_consequential_prohibition_is_reported(self):
        self.write("CLAUDE.md", "- Never force-push to main.\n")
        self.assertIn("ENFORCE002", self.fired())

    def test_a_stylistic_prohibition_is_not(self):
        self.write("CLAUDE.md", "- Never use single-letter variable names.\n")
        self.assertNotIn("ENFORCE002", self.fired())

    def test_an_unverifiable_instruction_is_noted(self):
        self.write("CLAUDE.md", "- Write good code and follow best practices.\n")
        self.assertIn("ENFORCE003", self.fired())

    def test_a_concrete_instruction_is_not(self):
        self.write("CLAUDE.md", "- Use 2-space indentation, following `.editorconfig`.\n")
        self.assertNotIn("ENFORCE003", self.fired())

    def test_a_missing_path_is_reported(self):
        self.write("CLAUDE.md", "- Handlers live in `src/api/handlers/`.\n")
        self.assertIn("ENFORCE004", self.fired())

    def test_an_existing_path_is_silent(self):
        self.write("src/api/handlers/x.ts", "export {}\n")
        self.write("CLAUDE.md", "- Handlers live in `src/api/handlers/`.\n")
        self.assertNotIn("ENFORCE004", self.fired())

    def test_a_model_id_is_not_treated_as_a_path(self):
        # Plenty of identifiers contain a slash without naming a file.
        self.write("CLAUDE.md", "- Generate images with `black-forest-labs/flux-2-max`.\n")
        self.assertNotIn("ENFORCE004", self.fired())

    def test_a_repository_slug_is_not_treated_as_a_path(self):
        self.write("CLAUDE.md", "- Mirror the layout of `hjalti-hub/whyskill` here.\n")
        self.assertNotIn("ENFORCE004", self.fired())

    def test_an_image_tag_is_not_treated_as_a_path(self):
        self.write("CLAUDE.md", "- Build on `library/node:22-alpine` for parity.\n")
        self.assertNotIn("ENFORCE004", self.fired())

    def test_a_directory_reference_is_still_reported(self):
        self.write("CLAUDE.md", "- Rendered output is written to `renders/`.\n")
        self.assertIn("ENFORCE004", self.fired())

    def test_an_extensionless_path_under_a_real_directory_is_reported(self):
        self.write("src/index.ts", "export {}\n")
        self.write("CLAUDE.md", "- Handlers live in `src/handlers`.\n")
        self.assertIn("ENFORCE004", self.fired())

    def test_a_url_is_not_treated_as_a_path(self):
        self.write("CLAUDE.md", "- See `https://example.com/docs/x` for the schema.\n")
        self.assertNotIn("ENFORCE004", self.fired())

    def test_a_missing_npm_script_is_reported(self):
        self.write("package.json", '{"scripts": {"test": "vitest run"}}')
        self.write("CLAUDE.md", "- Run `npm run lint` to check style.\n")
        self.assertIn("ENFORCE005", self.fired())

    def test_a_defined_npm_script_is_silent(self):
        self.write("package.json", '{"scripts": {"lint": "eslint ."}}')
        self.write("CLAUDE.md", "- Run `npm run lint` to check style.\n")
        self.assertNotIn("ENFORCE005", self.fired())

    def test_a_builtin_subcommand_is_never_reported(self):
        self.write("package.json", '{"scripts": {"lint": "eslint ."}}')
        self.write("CLAUDE.md", "- Run `npm install` after pulling.\n")
        self.assertNotIn("ENFORCE005", self.fired())

    def test_a_project_with_no_package_json_is_never_reported(self):
        self.write("CLAUDE.md", "- Run `npm run lint` to check style.\n")
        self.assertNotIn("ENFORCE005", self.fired())


class Weight(RuleCase):
    def test_a_long_file_is_reported(self):
        self.write("CLAUDE.md", "\n".join(f"- Use rule {i} carefully" for i in range(250)))
        self.assertIn("WEIGHT001", self.fired())

    def test_a_short_file_is_not(self):
        self.write("CLAUDE.md", "- Use 2-space indentation.\n")
        self.assertNotIn("WEIGHT001", self.fired())


if __name__ == "__main__":
    unittest.main()
