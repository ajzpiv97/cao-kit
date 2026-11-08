import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caokit import cli
from caokit.config import Binding, Config, dump_config
from caokit.launch import (
    build_launch_argv,
    build_send_argv,
    build_status_argv,
    build_stop_argv,
    session_id,
    session_name,
)


def good_config() -> Config:
    return Config(
        roles={
            "general": Binding("claude", "sonnet"),
            "engineer": Binding("claude", "opus"),
            "scout": Binding("antigravity", "gemini-3.8-flash-medium"),
            "inspector": Binding("antigravity", "gemini-4-argon-high"),
        }
    )


class SessionArgvTests(unittest.TestCase):
    def test_launch_with_prompt_and_flags(self):
        with tempfile.TemporaryDirectory() as d:
            argv = build_launch_argv(
                Path(d), "p_general-claude", "p", prompt="go", headless=True, auto_approve=True
            )
        self.assertEqual(argv[:3], ["cao", "launch", "--agents"])
        self.assertEqual(argv[-2:], ["--", "go"])
        self.assertIn("--headless", argv)
        self.assertIn("--auto-approve", argv)
        self.assertNotIn("--yolo", argv)

    def test_async_launch_passes_the_flag_only_when_asked(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertNotIn("--async", build_launch_argv(Path(d), "g", headless=True, prompt="x"))
            argv = build_launch_argv(Path(d), "g", headless=True, prompt="x", wait=False)
        self.assertIn("--async", argv)
        self.assertEqual(argv[-2:], ["--", "x"])

    def test_launch_without_prompt_has_no_message(self):
        with tempfile.TemporaryDirectory() as d:
            argv = build_launch_argv(Path(d), "general-claude")
        self.assertEqual(argv[:3], ["cao", "launch", "--agents"])

    def test_session_name_prefers_project_slug_then_directory(self):
        self.assertEqual(session_name(Path("/x/My App!"), "slug"), "slug")
        self.assertRegex(session_name(Path("/x/My App!"), None), r"^my-app-[0-9a-f]{6}$")
        self.assertEqual(session_id("slug"), "cao-slug")

    def test_same_directory_name_in_different_parents_gets_different_sessions(self):
        self.assertNotEqual(session_name(Path("/a/app"), None), session_name(Path("/b/app"), None))
        self.assertEqual(session_name(Path("/a/app"), None), session_name(Path("/a/app"), None))

    def test_a_message_starting_with_a_dash_stays_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            argv = build_launch_argv(Path(d), "general-claude", prompt="--yolo")
        self.assertEqual(argv[-2:], ["--", "--yolo"])
        self.assertEqual(build_send_argv("cao-p", "--async")[-2:], ["cao-p", "--async"])
        self.assertLess(build_send_argv("cao-p", "--async").index("--"), 6)

    def test_session_id_does_not_double_the_cao_prefix(self):
        self.assertEqual(session_id("cao-trial"), "cao-trial")
        name = session_name(Path("/x/cao-trial"), None)
        self.assertTrue(name.startswith("cao-trial-"))
        self.assertEqual(session_id(name), name)

    def test_status_send_stop(self):
        self.assertEqual(
            build_status_argv("cao-p")[1], ["cao", "session", "status", "cao-p", "--workers"]
        )
        self.assertEqual(
            build_send_argv("cao-p", "hi", 30),
            ["cao", "session", "send", "--timeout", "30", "--", "cao-p", "hi"],
        )
        self.assertEqual(build_stop_argv("cao-p"), ["cao", "shutdown", "--session", "cao-p"])


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "caokit.toml"
        self.cfg.write_text(dump_config(good_config()))
        self.repo = self.root / "proj"
        (self.repo / ".company").mkdir(parents=True)
        (self.repo / ".company" / "caokit.toml").write_text('schema = 1\n[project]\nname = "pj"\n')

    def run_cli(self, *argv):
        err = io.StringIO()
        with mock.patch("caokit.cli._run", return_value=0) as run, contextlib.redirect_stderr(err):
            code = cli.main(["--config", str(self.cfg), *argv])
        return code, [c.args[0] for c in run.call_args_list], err.getvalue()

    def test_launch_uses_project_profile_and_session(self):
        prompt = self.root / "p.md"
        prompt.write_text("do the thing")
        code, calls, _ = self.run_cli(
            "launch", str(self.repo), "--prompt-file", str(prompt), "--headless"
        )
        self.assertEqual(code, 0)
        argv = calls[0]
        self.assertEqual(argv[-2:], ["--", "do the thing"])
        self.assertEqual(argv[argv.index("--agents") + 1], "pj_general-claude")
        self.assertEqual(argv[argv.index("--session-name") + 1], "pj")

    def test_empty_prompt_file_is_an_error_not_a_silent_launch(self):
        prompt = self.repo / "empty.md"
        prompt.write_text("  \n")
        code, calls, err = self.run_cli("launch", str(self.repo), "--prompt-file", str(prompt))
        self.assertEqual((code, calls, "empty" in err), (1, [], True))

    def test_stop_and_send_target_the_project_session(self):
        _, calls, _ = self.run_cli("stop", str(self.repo))
        self.assertEqual(calls[0], ["cao", "shutdown", "--session", "cao-pj"])
        _, calls, _ = self.run_cli("send", "hello", "--repo", str(self.repo))
        self.assertEqual(calls[0][-2:], ["cao-pj", "hello"])

    def test_status_runs_list_then_workers(self):
        _, calls, _ = self.run_cli("status", str(self.repo))
        self.assertEqual([c[2] for c in calls], ["list", "status"])

    def test_missing_prompt_file_is_an_error_not_a_launch(self):
        code, calls, err = self.run_cli("launch", str(self.repo), "--prompt-file", "/nope.md")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
