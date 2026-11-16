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
        (self.repo / ".caokit").mkdir(parents=True)
        (self.repo / ".caokit" / "caokit.toml").write_text('schema = 1\n[project]\nname = "pj"\n')

    def run_cli(self, *argv):
        err = io.StringIO()
        with (
            mock.patch("caokit.cli._run", return_value=0) as run,
            mock.patch("caokit.cli._run_tee", return_value=(0, "")) as tee,  # headless launches
            mock.patch("caokit.cli._capture", return_value=(0, "")),
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(["--config", str(self.cfg), *argv])
        calls = run.call_args_list + tee.call_args_list
        return code, [c.args[0] for c in calls], err.getvalue()

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

    def stop_worker(self, worker, terminals='[{"id": "aaaa1111"}, {"id": "bbbb2222"}]', http="200"):
        seen = []

        def capture(argv):
            seen.append(list(argv))
            return (0, http) if "DELETE" in argv else (0, terminals)

        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("caokit.cli._run", return_value=0) as run,
            mock.patch("caokit.cli._capture", side_effect=capture),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(["--config", str(self.cfg), "stop", str(self.repo), "--worker", worker])
        deletes = [a[-1] for a in seen if "DELETE" in a]
        return code, deletes, run.call_count, out.getvalue() + err.getvalue()

    def test_stop_worker_deletes_that_terminal_and_leaves_the_session_up(self):
        # Seen live: mid-handoff the General cannot stop a worker, so the owner needs a way to.
        code, deletes, shutdowns, text = self.stop_worker("bbbb2222")
        self.assertEqual((code, shutdowns), (0, 0))
        self.assertEqual(deletes, ["http://127.0.0.1:9889/terminals/bbbb2222"])
        self.assertIn("bbbb2222", text)

    def test_stop_worker_refuses_the_general_and_unknown_ids(self):
        code, deletes, _, text = self.stop_worker("aaaa1111")
        self.assertEqual((code, deletes), (1, []))
        self.assertIn("General", text)
        code, deletes, _, text = self.stop_worker("cccc3333")
        self.assertEqual((code, deletes), (1, []))
        self.assertIn("bbbb2222", text)  # names the workers that do exist

    def test_stop_worker_reports_a_server_that_is_down_or_refuses(self):
        code, deletes, _, text = self.stop_worker("bbbb2222", terminals="")
        self.assertEqual((code, deletes), (1, []))
        self.assertIn("caokit server", text)
        code, _, _, text = self.stop_worker("bbbb2222", http="409")
        self.assertEqual(code, 1)
        self.assertIn("409", text)

    def test_status_runs_list_then_workers(self):
        _, calls, _ = self.run_cli("status", str(self.repo))
        self.assertEqual([c[2] for c in calls], ["list", "status"])

    def test_headless_launch_whose_prompt_was_not_delivered_fails_and_says_how_to_answer(self):
        # Seen live: Claude Code showed a startup menu, cao printed this and the General sat idle.
        prompt = self.root / "p.md"
        prompt.write_text("do the thing")
        undelivered = (
            "Session created: cao-pj\n"
            "Error: Initial message was not delivered to terminal c75cf34b (waiting_user_answer)\n"
        )
        err = io.StringIO()
        with (
            mock.patch("caokit.cli._run", return_value=0),  # never start a real session
            mock.patch("caokit.cli._run_tee", return_value=(0, undelivered)),
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(
                ["--config", str(self.cfg), "launch", str(self.repo), "--headless"]
                + ["--prompt-file", str(prompt)]
            )
        self.assertEqual(code, 1)
        self.assertIn("tmux attach -t cao-pj", err.getvalue())
        self.assertIn("caokit send", err.getvalue())

    def test_failed_send_while_the_general_asks_a_question_shows_the_question(self):
        # Seen live: the General asked through a menu; send timed out without showing it.
        status = "Terminal: c75cf34b\nStatus:   waiting_user_answer\n"
        pane = "what form does `rate` take?\n> 1. Fraction\n  2. Percent\n"

        def capture(argv):
            return (0, status) if argv[0] == "cao" else (0, pane)

        err = io.StringIO()
        with (
            mock.patch("caokit.cli._run", return_value=1),
            mock.patch("caokit.cli._capture", side_effect=capture) as cap,
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(["--config", str(self.cfg), "send", "hello", "--repo", str(self.repo)])
        self.assertEqual(code, 1)
        self.assertIn("1. Fraction", err.getvalue())
        self.assertIn("tmux attach -t cao-pj", err.getvalue())
        self.assertEqual(cap.call_args_list[0].args[0], ["cao", "session", "status", "cao-pj"])

    def test_failed_send_without_a_pending_question_adds_nothing(self):
        err = io.StringIO()
        with (
            mock.patch("caokit.cli._run", return_value=1),
            mock.patch("caokit.cli._capture", return_value=(0, "Status:   processing\n")),
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(["--config", str(self.cfg), "send", "hello", "--repo", str(self.repo)])
        self.assertEqual((code, err.getvalue()), (1, ""))

    def test_missing_prompt_file_is_an_error_not_a_launch(self):
        code, calls, err = self.run_cli("launch", str(self.repo), "--prompt-file", "/nope.md")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
