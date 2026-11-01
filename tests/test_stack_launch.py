import json
import tempfile
import unittest
from pathlib import Path

from caokit.launch import build_launch_argv
from caokit.stack import suggest_validation


class FakeResult:
    """Minimal stand-in for a subprocess result (what the Runner protocol reads)."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def ok_runner(argv):
    """Pretend `python3 -c "import pytest"` succeeded."""
    return FakeResult(0)


def fail_runner(argv):
    """Pretend pytest is not importable."""
    return FakeResult(1)


class StackTests(unittest.TestCase):
    """Stack detection suggests commands without ever installing anything."""

    def suggested(self, r, runner):
        """Return the suggestion for ``r``, failing the test if there is none."""
        s = suggest_validation(r, runner=runner)
        assert s is not None
        return s

    def repo(self, files):
        """Create a temp repo containing ``files`` (name -> content)."""
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        for name, content in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return root

    def test_pytest_config(self):
        r = self.repo(
            {"pyproject.toml": "[tool.pytest.ini_options]\naddopts='-q'\n", "tests/test_a.py": ""}
        )
        s = self.suggested(r, ok_runner)
        self.assertEqual(s.command, "python3 -B -m pytest -p no:cacheprovider -q")

    def test_pytest_not_installed_falls_back_to_unittest(self):
        r = self.repo(
            {
                "pyproject.toml": "[tool.pytest.ini_options]\n",
                "tests/test_a.py": "import unittest\n",
            }
        )
        s = self.suggested(r, fail_runner)
        self.assertEqual(s.command, "python3 -B -m unittest discover")

    def test_unittest_layout(self):
        r = self.repo({"tests/test_a.py": "import unittest\nclass T(unittest.TestCase): pass\n"})
        self.assertEqual(self.suggested(r, fail_runner).command, "python3 -B -m unittest discover")

    def test_package_json_test_script(self):
        r = self.repo(
            {"package.json": '{"scripts": {"test": "vitest run"}}', "node_modules/.keep": ""}
        )
        self.assertEqual(self.suggested(r, ok_runner).command, "npm test")

    def test_package_json_default_script_ignored(self):
        r = self.repo(
            {
                "package.json": json.dumps(
                    {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
                )
            }
        )
        self.assertIsNone(suggest_validation(r, runner=ok_runner))

    def test_package_json_without_node_modules_is_noted(self):
        r = self.repo({"package.json": '{"scripts": {"test": "jest"}}'})
        s = self.suggested(r, ok_runner)
        self.assertIn("node_modules", s.note)

    def test_makefile_test_target(self):
        r = self.repo({"Makefile": "build:\n\techo x\ntest:\n\techo y\n"})
        self.assertEqual(self.suggested(r, ok_runner).command, "make test")

    def test_ci_only_gives_hint_without_command(self):
        r = self.repo({".github/workflows/ci.yml": "name: ci\n"})
        s = self.suggested(r, ok_runner)
        self.assertIsNone(s.command)
        self.assertIn("ci.yml", s.reason)

    def test_nothing(self):
        self.assertIsNone(suggest_validation(self.repo({"README.md": "x"}), runner=ok_runner))

    def test_broken_package_json(self):
        r = self.repo({"package.json": "{not json"})
        self.assertIsNone(suggest_validation(r, runner=ok_runner))


class LaunchTests(unittest.TestCase):
    """Launch argv is always explicit about the working directory."""

    def test_always_has_absolute_working_directory(self):
        with tempfile.TemporaryDirectory() as t:
            argv = build_launch_argv(Path(t), "general-claude")
            i = argv.index("--working-directory")
            self.assertTrue(Path(argv[i + 1]).is_absolute())
            self.assertEqual(Path(argv[i + 1]), Path(t).resolve())
            self.assertEqual(argv[:2], ["cao", "launch"])
            self.assertIn("general-claude", argv)

    def test_relative_path_resolved(self):
        argv = build_launch_argv(Path("."), "general-claude")
        self.assertTrue(Path(argv[argv.index("--working-directory") + 1]).is_absolute())

    def test_never_dangerous_flags(self):
        argv = build_launch_argv(Path("."), "general-claude", session="s")
        self.assertNotIn("--yolo", argv)
        self.assertNotIn("*", argv)

    def test_missing_dir_rejected(self):
        with self.assertRaises(ValueError):
            build_launch_argv(Path("/nonexistent/zzz"), "general-claude")


if __name__ == "__main__":
    unittest.main()
