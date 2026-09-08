"""Tests for the command line surface.

The exit code is an API: CI depends on it, and so does anyone who pipes whyrule
into a script. These tests pin the codes and the machine-readable output shapes.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from whyrule.cli import main


class CliCase(unittest.TestCase):
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

    def run_cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def base(self) -> list:
        return ["--project", str(self.root), "--no-user"]


class ExitCodes(CliCase):
    def test_a_clean_project_exits_zero(self):
        self.write("CLAUDE.md", "- Use 2-space indentation.\n")
        code, out, _ = self.run_cli(*self.base())
        self.assertEqual(code, 0)
        self.assertIn("nothing silently dropped", out)

    def test_an_error_exits_one(self):
        self.write("CLAUDE.md", "See @docs/missing.md\n")
        code, _, _ = self.run_cli(*self.base())
        self.assertEqual(code, 1)

    def test_fail_on_never_always_exits_zero(self):
        self.write("CLAUDE.md", "See @docs/missing.md\n")
        code, _, _ = self.run_cli(*self.base(), "--fail-on", "never")
        self.assertEqual(code, 0)

    def test_a_warning_alone_does_not_fail_by_default(self):
        self.write("CLAUDE.md", "- Use 2-space indentation.\n")
        self.write("CLAUDE.local.md", "- Use 4-space indentation.\n")
        code, _, _ = self.run_cli(*self.base())
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(*self.base(), "--fail-on", "warning")
        self.assertEqual(code, 1)

    def test_a_missing_path_is_a_usage_error(self):
        code, _, err = self.run_cli(str(self.root / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)


class BareInvocation(CliCase):
    def test_no_arguments_does_not_crash(self):
        # Bare `whyrule` is the most common invocation there is; argparse builds
        # a Namespace without the check options unless the default is inserted.
        code, _, _ = self.run_cli()
        self.assertIn(code, (0, 1))

    def test_version_exits_cleanly(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("--version")
        self.assertEqual(caught.exception.code, 0)


class MachineOutput(CliCase):
    def test_json_has_the_documented_shape(self):
        self.write("CLAUDE.md", "See @docs/missing.md\n")
        _, out, _ = self.run_cli(*self.base(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["findings"][0]["rule"], "IMPORT001")
        self.assertIn("lines_at_launch", payload["summary"])

    def test_sarif_is_valid_and_names_the_rule(self):
        self.write("CLAUDE.md", "See @docs/missing.md\n")
        _, out, _ = self.run_cli(*self.base(), "--sarif")
        doc = json.loads(out)
        self.assertEqual(doc["version"], "2.1.0")
        result = doc["runs"][0]["results"][0]
        self.assertEqual(result["ruleId"], "IMPORT001")
        self.assertEqual(result["level"], "error")

    def test_disable_suppresses_a_rule(self):
        self.write("CLAUDE.md", "See @docs/missing.md\n")
        _, out, _ = self.run_cli(*self.base(), "--json", "--disable", "IMPORT001")
        self.assertEqual(json.loads(out)["findings"], [])


class Subcommands(CliCase):
    def test_list_shows_the_launch_total(self):
        self.write("CLAUDE.md", "- Use 2-space indentation.\n")
        code, out, _ = self.run_cli("list", *self.base())
        self.assertEqual(code, 0)
        self.assertIn("lines load at launch", out)

    def test_rules_lists_every_group(self):
        code, out, _ = self.run_cli("rules")
        self.assertEqual(code, 0)
        for group in ("Loading", "Imports", "Conflict", "Enforceability"):
            self.assertIn(group, out)

    def test_why_explains_a_matching_instruction(self):
        self.write("CLAUDE.md", "- Always run `npm run lint` before committing.\n")
        code, out, _ = self.run_cli("why", "run npm lint before committing", *self.base())
        self.assertEqual(code, 0)
        self.assertIn("ENFORCE001", out)

    def test_why_says_so_when_nothing_matches(self):
        self.write("CLAUDE.md", "- Use 2-space indentation.\n")
        code, out, _ = self.run_cli("why", "deploy the kubernetes cluster nightly", *self.base())
        self.assertEqual(code, 2)
        self.assertIn("No loaded instruction matches", out)

    def test_install_print_does_not_write(self):
        settings = self.root / ".claude" / "settings.json"
        code, out, _ = self.run_cli("install", "--project", str(self.root), "--print")
        self.assertFalse(settings.exists())
        # Refusing to install is a valid outcome when whyrule is not importable
        # from a neutral directory; both branches must stay non-crashing.
        self.assertIn(code, (0, 2))
        if code == 0:
            self.assertIn("hooks", json.loads(out))


class PipedOutput(unittest.TestCase):
    """`whyrule rules | head` must not end in a BrokenPipeError traceback.

    Closing the pipe early is how `head`, `grep -q` and quitting `less` all
    behave, so a traceback there is the tool's fault, not the user's.

    The sibling tools whyskill and deadweight both shipped this bug to PyPI
    before anyone noticed, and the fix that followed was itself incomplete the
    first time - which is what the third test here is for.
    """

    def _stderr_of_piped(self, args: str) -> str:
        import subprocess
        import sys

        repo = Path(__file__).resolve().parent.parent
        with tempfile.NamedTemporaryFile(suffix=".err") as err:
            subprocess.run(
                f"{sys.executable} -m whyrule {args} 2>{err.name} | head -1",
                shell=True,
                cwd=repo,
                stdout=subprocess.DEVNULL,
            )
            return Path(err.name).read_text()

    def test_rules_survives_a_closed_pipe(self):
        stderr = self._stderr_of_piped("rules")
        self.assertNotIn("BrokenPipeError", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_check_survives_a_closed_pipe(self):
        stderr = self._stderr_of_piped("examples/broken --no-user --explain")
        self.assertNotIn("BrokenPipeError", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_output_left_in_the_buffer_does_not_raise_at_shutdown(self):
        """The case a pipeline test cannot be trusted to catch.

        stdout is block-buffered when it is a pipe, so output smaller than the
        buffer never reaches the pipe while the command runs: the write fails
        for the first time in the interpreter's shutdown flush, after main()
        has returned, and prints "Exception ignored on flushing sys.stdout"
        where no handler can see it.

        Whether the pipeline tests above hit that depends on whether `head`
        exits before or after the first flush. In whyskill they passed locally
        and failed on all three CI versions. This one removes the race: the
        read end is closed before whyrule starts, so the only write that can
        fail is the flush main() performs itself.
        """
        import os
        import sys
        from unittest import mock

        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        writer = os.fdopen(write_fd, "w")

        with mock.patch.object(sys, "stdout", writer):
            code = main(["rules"])
        self.assertEqual(code, 0)

        # Not decoration: if main() returned without flushing, the output is
        # still sitting in this buffer and closing raises exactly what the
        # shutdown flush would have. Asserting only on `code` would pass with
        # the fix removed.
        writer.close()

    def test_the_buffer_test_above_is_actually_testing_something(self):
        """`whyrule rules` must stay smaller than the stdout buffer.

        If its output grew past 8 KiB it would reach the pipe during the run,
        the failure would surface somewhere main() can already catch it, and
        the test above would pass whether or not the flush is there.
        """
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["rules"])
        self.assertLess(len(buffer.getvalue().encode()), io.DEFAULT_BUFFER_SIZE)


if __name__ == "__main__":
    unittest.main()
