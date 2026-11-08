import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from caokit.config import Binding, Config
from caokit.doctor import Report, _check_server
from caokit.install import uninstall_profiles
from caokit.reset import ResetError, _cao_server_pids, _drop_cao_servers, plan, run_reset


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def make_runner(calls, fail=None, version="cao, version 2.5.4", ps=""):
    def runner(argv):
        calls.append(list(argv))
        if fail and list(argv)[: len(fail)] == fail:
            return R(1, err="boom")
        if argv[:2] == ["cao", "--version"]:
            return R(0, version)
        if argv[0] == "ps":
            return R(0, ps)
        if argv[0] == "tmux" and argv[1] == "list-sessions":
            return R(0, "cao-pj\nmine\n")
        return R(0)

    return runner


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "cao"
        (self.home / "agent-store").mkdir(parents=True)
        (self.home / "agent-store" / "x.md").write_text("x")
        self.mcp = self.root / "mcp.json"
        self.mcp.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "cao-mcp-server": {"command": "cao-mcp-server"},
                        "keep": {"command": "z"},
                    }
                }
            )
        )

    def test_moves_state_backs_up_config_and_keeps_other_servers(self):
        calls = []
        res = run_reset("2.5.4", self.home, self.mcp, self.root, make_runner(calls))
        self.assertFalse(self.home.exists())
        self.assertTrue((res.backup / "cli-agent-orchestrator" / "agent-store" / "x.md").exists())
        self.assertIn("cao-mcp-server", (res.backup / "gemini-mcp_config.json").read_text())
        self.assertEqual(list(json.loads(self.mcp.read_text())["mcpServers"]), ["keep"])
        self.assertIn(["uv", "tool", "install", "cli-agent-orchestrator==2.5.4"], calls)
        self.assertIn(["tmux", "kill-session", "-t", "cao-pj"], calls)
        self.assertNotIn(["tmux", "kill-session", "-t", "mine"], calls)

    def test_failed_install_stops_before_profiles_and_names_the_backup(self):
        installed = []
        with self.assertRaisesRegex(ResetError, "backup"):
            run_reset(
                "2.5.4",
                self.home,
                self.mcp,
                self.root,
                make_runner([], fail=["uv", "tool", "install"]),
                install_profiles=lambda: installed.append(1),
            )
        self.assertEqual(installed, [])
        self.assertFalse(self.home.exists())  # moved, not deleted: it is in the backup

    def test_wrong_version_after_install_is_an_error(self):
        with self.assertRaisesRegex(ResetError, "not 2.5.4"):
            run_reset("2.5.4", self.home, self.mcp, self.root, make_runner([], version="cao 2.5.3"))

    def test_a_hung_install_is_a_reset_error_naming_the_backup(self):
        def runner(argv):
            if argv[:3] == ["uv", "tool", "install"]:
                raise subprocess.TimeoutExpired(argv, 60)
            return make_runner([])(argv)

        with self.assertRaisesRegex(ResetError, "backup"):
            run_reset("2.5.4", self.home, self.mcp, self.root, runner)

    def test_install_uses_the_slow_runner(self):
        slow_calls = []
        run_reset(
            "2.5.4",
            self.home,
            self.mcp,
            self.root,
            make_runner([]),
            slow_runner=make_runner(slow_calls),
        )
        self.assertEqual(slow_calls, [["uv", "tool", "install", "cli-agent-orchestrator==2.5.4"]])

    def test_missing_tools_do_not_stop_the_stop_phase(self):
        def runner(argv):
            if (
                argv[0] in ("tmux", "ps", "cao")
                and argv[1:2] != ["--version"]
                and argv[1:2] != ["init"]
            ):
                raise FileNotFoundError(argv[0])
            return make_runner([])(argv)

        res = run_reset("2.5.4", self.home, self.mcp, self.root, runner)
        self.assertIn("installed CAO 2.5.4", res.steps)

    def test_refuses_to_move_a_symlink_or_the_home_folder(self):
        link = self.root / "link"
        link.symlink_to(self.home)
        for bad in (link, Path.home()):
            with self.assertRaises(ResetError):
                run_reset("2.5.4", bad, self.mcp, self.root, make_runner([]))
        self.assertTrue(self.home.exists())

    def test_two_resets_in_one_second_get_separate_backups(self):
        a = run_reset("2.5.4", self.home, self.mcp, self.root, make_runner([]))
        self.home.mkdir()
        b = run_reset("2.5.4", self.home, self.mcp, self.root, make_runner([]))
        self.assertNotEqual(a.backup, b.backup)

    def test_version_check_is_not_a_substring_match(self):
        with self.assertRaisesRegex(ResetError, "not 2.5"):
            run_reset("2.5", self.home, self.mcp, self.root, make_runner([], version="cao 2.5.10"))

    def test_mcp_config_with_odd_shape_is_left_alone(self):
        for text in ("[]", '{"mcpServers": []}', '{"mcpServers": {"caobot": {"command": "x"}}}'):
            self.mcp.write_text(text)
            self.assertEqual(_drop_cao_servers(self.mcp), [])
            self.assertEqual(self.mcp.read_text(), text)

    def test_server_pid_match_ignores_greps_and_editors(self):
        ps = (
            " 11 /Users/x/.local/bin/cao-server\n"
            " 12 /usr/bin/python3 /Users/x/.local/bin/cao-server\n"
            " 13 vim cao-server.md\n"
            " 14 grep cao-server\n"
        )
        self.assertEqual(_cao_server_pids(make_runner([], ps=ps)), ["11", "12"])

    def test_plan_names_the_pinned_version(self):
        self.assertTrue(any("==2.5.4" in s for s in plan("2.5.4", self.home)))


class ServerCheckTests(unittest.TestCase):
    def check(self, answers):
        def runner(argv):
            key = argv[-1].rsplit("/", 1)[-1] or "/"
            return answers.get(key, R(1))

        rep = Report()
        _check_server(rep, runner, lambda n: "/usr/bin/curl")
        return [(c.level, c.text) for c in rep.checks]

    def test_not_running_is_a_warning(self):
        self.assertEqual(self.check({})[0][0], "warn")

    def test_running_with_ui(self):
        out = self.check({"health": R(0, '{"status":"ok"}'), "/": R(0, "200")})
        self.assertEqual([lvl for lvl, _ in out], ["ok", "ok"])

    def test_running_without_ui_warns_with_the_restart_hint(self):
        out = self.check({"health": R(0, '{"status":"ok"}'), "/": R(0, "404")})
        self.assertEqual(out[1][0], "warn")
        self.assertIn("restart", out[1][1])


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "agent-store").mkdir()
        self.cfg = Config(
            roles={
                "general": Binding("claude", "sonnet"),
                "engineer": Binding("claude", "opus"),
                "scout": Binding("antigravity", "gemini-3.8-flash-medium"),
                "inspector": Binding("antigravity", "gemini-4-argon-high"),
            },
            project="pj",
        )

    def install(self, *names):
        (self.home / "agent-context").mkdir(exist_ok=True)
        for n in names:
            (self.home / "agent-store" / (n + ".md")).write_text("x")
            (self.home / "agent-context" / (n + ".md")).write_text("x")

    def test_dry_run_runs_nothing(self):
        self.install("pj_general-claude")
        calls = []
        res = uninstall_profiles(self.cfg, self.home, make_runner(calls))
        self.assertEqual(res.removed, ["pj_general-claude"])
        self.assertEqual(calls, [])

    def test_removes_only_this_projects_installed_profiles(self):
        self.install("pj_general-claude", "pj_engineer-claude", "other_general-claude")
        calls = []
        res = uninstall_profiles(self.cfg, self.home, make_runner(calls), apply=True)
        self.assertEqual(res.removed, ["pj_general-claude", "pj_engineer-claude"])
        self.assertEqual(len(res.missing), 2)
        self.assertEqual(calls, [["cao", "profile", "remove", n, "--yes"] for n in res.removed])

    def test_context_copy_is_moved_to_a_backup_not_deleted(self):
        self.install("pj_general-claude")
        res = uninstall_profiles(self.cfg, self.home, make_runner([]), apply=True)
        self.assertFalse((self.home / "agent-context" / "pj_general-claude.md").exists())
        self.assertTrue(
            res.backup and (res.backup / "agent-context" / "pj_general-claude.md").exists()
        )

    def test_context_only_leftover_is_cleaned_without_calling_cao(self):
        (self.home / "agent-context").mkdir()
        (self.home / "agent-context" / "pj_general-claude.md").write_text("x")
        calls = []
        res = uninstall_profiles(self.cfg, self.home, make_runner(calls), apply=True)
        self.assertEqual((res.removed, calls), (["pj_general-claude"], []))

    def test_cao_error_text_counts_as_failure(self):
        self.install("pj_general-claude")

        def runner(argv):
            return R(0, "Error: refused")

        res = uninstall_profiles(self.cfg, self.home, runner, apply=True)
        self.assertEqual(res.failed, ["pj_general-claude"])


if __name__ == "__main__":
    unittest.main()
