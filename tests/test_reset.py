import json
import tempfile
import unittest
from pathlib import Path

from caokit.doctor import Report, _check_server
from caokit.reset import ResetError, _cao_server_pids, plan, run_reset


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


if __name__ == "__main__":
    unittest.main()
