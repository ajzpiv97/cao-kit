"""Tests for ``caokit doctor`` and the command line (no real CLIs or CAO installs)."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caokit import cli
from caokit.config import Binding, Config, dump_config
from caokit.doctor import Report, format_report, run_doctor
from caokit.install import InstallResult


class R:
    """Minimal stand-in for a CompletedProcess."""

    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


ALL_BINARIES = {
    n: f"/fake/bin/{n}" for n in ("cao", "uv", "tmux", "git", "claude", "agy", "python3", "pipx")
}


def make_runner(overrides=None):
    """Runner that answers like a healthy machine; ``overrides`` maps argv tuple -> R/Exception."""
    overrides = overrides or {}
    healthy = {
        ("cao", "--version"): R(0, "cao, version 2.5.4"),
        ("uv", "tool", "list"): R(0, "cli-agent-orchestrator v2.5.4\n- cao\n"),
        ("pipx", "list", "--short"): R(0, ""),
        ("claude", "--version"): R(0, "2.1.316 (Claude Code)"),
        ("agy", "--version"): R(0, "1.4.12"),
        ("agy", "models"): R(0, "gemini-4-argon-high\tG\n"),
    }

    def runner(argv):
        key = tuple(argv)
        if key in overrides:
            res = overrides[key]
            if isinstance(res, Exception):
                raise res
            return res
        if len(key) > 1 and key[1] == "-c":  # pip metadata probe: not installed
            return R(1)
        return healthy.get(key, R(1))

    return runner


def good_config() -> Config:
    return Config(
        roles={
            "general": Binding("claude", "sonnet"),
            "engineer": Binding("claude", "opus"),
            "scout": Binding("antigravity", "gemini-3.8-flash-medium"),
            "inspector": Binding("antigravity", "gemini-4-argon-high"),
        }
    )


def levels(rep: Report, needle: str):
    return [c.level for c in rep.checks if needle in c.text]


class DoctorTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.cfg_path = Path(t.name) / "caokit.toml"

    def write(self, cfg: Config) -> None:
        self.cfg_path.write_text(dump_config(cfg))

    def run_it(self, overrides=None, binaries=None, config=True):
        if config:
            self.write(good_config())
        paths = dict(ALL_BINARIES if binaries is None else binaries)
        return run_doctor(self.cfg_path, make_runner(overrides), paths.get)

    def test_healthy_machine_has_no_failures(self):
        rep = self.run_it()
        self.assertFalse(rep.failed, format_report(rep))
        self.assertIn("single cao install", format_report(rep))
        self.assertEqual(levels(rep, "codex"), ["ok"])  # parked tools are informational
        self.assertEqual(levels(rep, "roster valid"), ["ok"])

    def test_missing_config_only_warns(self):
        rep = self.run_it(config=False)
        self.assertEqual(rep.checks[0].level, "warn")
        self.assertIn("config not found", rep.checks[0].text)
        self.assertFalse(rep.failed)

    def test_cao_missing_fails(self):
        binaries = {k: v for k, v in ALL_BINARIES.items() if k != "cao"}
        rep = self.run_it(binaries=binaries)
        self.assertTrue(rep.failed)
        self.assertEqual(levels(rep, "cao not found"), ["fail"])

    def test_wrong_cao_version_fails(self):
        rep = self.run_it({("cao", "--version"): R(0, "cao, version 2.6.0")})
        self.assertEqual(levels(rep, "expected 2.5.4"), ["fail"])

    def test_unreadable_cao_version_fails(self):
        rep = self.run_it({("cao", "--version"): R(0, "garbage")})
        self.assertEqual(levels(rep, "cannot read"), ["fail"])

    def test_cao_not_a_uv_tool_warns(self):
        rep = self.run_it({("uv", "tool", "list"): R(0, "graphifyy v1\n")})
        self.assertEqual(levels(rep, "not a uv tool"), ["warn"])

    def test_extra_pipx_install_fails(self):
        rep = self.run_it({("pipx", "list", "--short"): R(0, "cli-agent-orchestrator 2.5.4\n")})
        self.assertEqual(levels(rep, "additional cao installs"), ["fail"])
        self.assertIn("pipx", format_report(rep))

    def test_extra_pip_install_fails_and_dedups(self):
        code_probe = ("/fake/bin/python3", "-c")

        def runner(argv):
            if tuple(argv[:2]) == code_probe:
                return R(0, "2.5.4")
            return make_runner()(argv)

        self.write(good_config())
        rep = run_doctor(self.cfg_path, runner, ALL_BINARIES.get)
        self.assertEqual(levels(rep, "additional cao installs"), ["fail"])
        self.assertEqual(format_report(rep).count("pip in"), 1)

    def test_used_tool_failing_auth_fails(self):
        rep = self.run_it({("agy", "models"): R(1, "", "not logged in")})
        self.assertEqual(levels(rep, "antigravity: installed but auth"), ["fail"])
        self.assertTrue(rep.failed)

    def test_unused_tool_failing_auth_only_warns(self):
        # Roster uses only claude, so a broken agy login is not a failure.
        self.write(
            Config(
                roles={r: Binding("claude", "sonnet") for r in good_config().roles},
                allow_single_provider=True,
            )
        )
        rep = run_doctor(self.cfg_path, make_runner({("agy", "models"): R(1)}), ALL_BINARIES.get)
        self.assertEqual(levels(rep, "antigravity: installed but auth"), ["warn"])
        self.assertFalse(rep.failed, format_report(rep))

    def test_used_tool_binary_missing_fails_unused_warns(self):
        binaries = {k: v for k, v in ALL_BINARIES.items() if k != "agy"}
        self.assertEqual(levels(self.run_it(binaries=binaries), "`agy` not found"), ["fail"])
        self.write(
            Config(
                roles={r: Binding("claude", "sonnet") for r in good_config().roles},
                allow_single_provider=True,
            )
        )
        rep = run_doctor(self.cfg_path, make_runner(), binaries.get)
        self.assertEqual(levels(rep, "`agy` not found"), ["warn"])

    def test_version_command_failure_and_exception(self):
        rep = self.run_it({("agy", "--version"): R(1)})
        self.assertEqual(levels(rep, "`agy --version` failed"), ["fail"])
        rep = self.run_it({("agy", "--version"): OSError("boom")})
        self.assertEqual(levels(rep, "`agy --version` failed"), ["fail"])
        rep = self.run_it({("agy", "--version"): subprocess.TimeoutExpired("agy", 1)})
        self.assertEqual(levels(rep, "`agy --version` failed"), ["fail"])

    def test_claude_auth_not_checked_note(self):
        self.assertIn("auth not checked", format_report(self.run_it()))

    def test_one_provider_ready_warns(self):
        binaries = {k: v for k, v in ALL_BINARIES.items() if k != "agy"}
        rep = self.run_it(binaries=binaries)
        self.assertEqual(levels(rep, "provider(s) ready"), ["warn"])

    def test_tmux_missing_fails_uv_missing_warns(self):
        rep = self.run_it(binaries={k: v for k, v in ALL_BINARIES.items() if k != "tmux"})
        self.assertEqual(levels(rep, "tmux not found"), ["fail"])
        rep = self.run_it(binaries={k: v for k, v in ALL_BINARIES.items() if k != "uv"})
        self.assertEqual(levels(rep, "uv not found"), ["warn"])

    def test_invalid_roster_fails_and_warnings_surface(self):
        self.write(
            Config(
                roles={**good_config().roles, "inspector": Binding("claude", "sonnet")},
                allow_single_provider=False,
            )
        )
        rep = run_doctor(self.cfg_path, make_runner(), ALL_BINARIES.get)
        self.assertTrue(any(c.level == "fail" and "roster:" in c.text for c in rep.checks))
        self.assertEqual(levels(rep, "roster valid"), [])

        self.write(Config(roles=good_config().roles, allow_soft_engineer=True))  # still fine
        rep = run_doctor(self.cfg_path, make_runner(), ALL_BINARIES.get)
        self.assertFalse(rep.failed)

    def test_roster_warning_is_reported(self):
        cfg = Config(
            roles={
                **good_config().roles,
                "engineer": Binding("antigravity", "gemini-4-argon-high"),
                "inspector": Binding("claude", "sonnet"),
            },
            allow_soft_engineer=True,
        )
        self.write(cfg)
        rep = run_doctor(self.cfg_path, make_runner(), ALL_BINARIES.get)
        self.assertEqual(levels(rep, "roster: engineer uses"), ["warn"])

    def test_default_config_path_used_when_none(self):
        with mock.patch.dict("os.environ", {"CAOKIT_HOME": str(self.cfg_path.parent)}):
            self.write(good_config())
            rep = run_doctor(None, make_runner(), ALL_BINARIES.get)
        self.assertEqual(levels(rep, "roster valid"), ["ok"])

    def test_format_report_tags(self):
        rep = Report()
        rep.add("ok", "a")
        rep.add("warn", "b")
        rep.add("fail", "c")
        self.assertEqual(format_report(rep), "[ ok ] a\n[warn] b\n[FAIL] c")
        self.assertTrue(rep.failed)
        self.assertFalse(Report().failed)


def run_cli(*argv, stdin_tty=False, answers=None):
    """Call cli.main, returning (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    stdin = mock.MagicMock()
    stdin.isatty.return_value = stdin_tty
    patches = [mock.patch("sys.stdin", stdin)]
    if answers is not None:
        patches.append(mock.patch("builtins.input", side_effect=list(answers)))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# Antigravity roles without a model skip `agy models`, so no CLI is needed.
FLAGS = [
    "--general", "claude:sonnet",
    "--engineer", "claude:opus",
    "--scout", "antigravity",
    "--inspector", "antigravity",
]  # fmt: skip


class CliTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.cfg = self.tmp / "caokit.toml"

    def create(self, *extra):
        return run_cli("--config", str(self.cfg), "company", "create", *FLAGS, *extra)

    def test_create_flag_driven_success(self):
        code, out, _ = self.create()
        self.assertEqual(code, 0)
        self.assertIn("Next: caokit install", out)
        self.assertIn('tool = "antigravity"', self.cfg.read_text())

    def test_create_refuses_overwrite_then_force(self):
        self.create()
        code, _, err = self.create()
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(self.create("--force")[0], 0)

    def test_create_guardrail_failure_exits_1(self):
        code, _, err = run_cli(
            "--config", str(self.cfg), "company", "create",
            "--general", "claude", "--engineer", "claude",
            "--scout", "claude", "--inspector", "claude",
        )  # fmt: skip
        self.assertEqual(code, 1)
        self.assertIn("cross-provider", err)
        self.assertFalse(self.cfg.exists())

    def test_create_without_flags_and_no_tty_exits_2(self):
        code, _, err = run_cli("--config", str(self.cfg), "company", "create")
        self.assertEqual(code, 2)
        self.assertIn("run interactively", err)

    def test_create_interactive_enter_accepts_recommendations(self):
        # Blank answers take the defaults: claude/sonnet general, claude/opus engineer.
        answers = ["", "", "", "", "antigravity", "none", "antigravity", "none"]
        code, out, _ = run_cli(
            "--config", str(self.cfg), "company", "create",
            stdin_tty=True, answers=answers,
        )  # fmt: skip
        self.assertEqual(code, 0)
        self.assertIn("Pick a tool and model per role", out)
        text = self.cfg.read_text()
        self.assertIn('model = "sonnet"', text)
        self.assertIn('model = "opus"', text)

    def test_create_interactive_unknown_tool_reports_roster_error(self):
        answers = ["nope", "none", "claude", "none", "claude", "none", "claude", "none"]
        code, _, err = run_cli(
            "--config", str(self.cfg), "company", "create",
            stdin_tty=True, answers=answers,
        )  # fmt: skip
        self.assertEqual(code, 1)
        self.assertIn("unknown tool", err)

    def test_create_interactive_success(self):
        answers = [
            "claude",
            "sonnet",
            "claude",
            "opus",
            "antigravity",
            "none",
            "antigravity",
            "none",
        ]
        code, _, _ = run_cli(
            "--config", str(self.cfg), "company", "create",
            stdin_tty=True, answers=answers,
        )  # fmt: skip
        self.assertEqual(code, 0)
        self.assertNotIn("model", self.cfg.read_text().split("[roles.scout]")[1].split("[")[0])

    def test_doctor_exit_codes(self):
        bad, good = Report(), Report()
        bad.add("fail", "x")
        good.add("ok", "y")
        with mock.patch("caokit.cli.run_doctor", return_value=bad):
            self.assertEqual(run_cli("doctor")[0], 1)
        with mock.patch("caokit.cli.run_doctor", return_value=good):
            code, out, _ = run_cli("doctor")
        self.assertEqual((code, out.strip()), (0, "[ ok ] y"))

    def test_install_missing_config_exits_1(self):
        code, _, err = run_cli("--config", str(self.tmp / "none.toml"), "install")
        self.assertEqual(code, 1)
        self.assertIn("config not found", err)

    def install(self, result, legacy, *extra, tty=False, answers=None):
        self.create()
        home = self.tmp / "cao"
        with (
            mock.patch("caokit.cli.cao_home", return_value=home),
            mock.patch("caokit.cli.find_legacy", return_value=legacy),
            mock.patch("caokit.cli.install_profiles", return_value=result) as ip,
            mock.patch("caokit.cli.remove_legacy", return_value=home / "bk") as rl,
        ):
            res = run_cli("--config", str(self.cfg), "install", *extra,
                          stdin_tty=tty, answers=answers)  # fmt: skip
        return res, ip, rl

    def test_install_failure_exits_1(self):
        (code, _, err), _, _ = self.install(InstallResult(failed=["x-claude"]), [])
        self.assertEqual(code, 1)
        self.assertIn("FAILED: x-claude", err)
        self.assertIn("--replace-legacy", err)

    def test_install_invalid_roster_exits_1(self):
        self.create()
        bad = Config(roles={**good_config().roles, "inspector": Binding("claude", "sonnet")})
        self.cfg.write_text(dump_config(bad))
        code, _, err = run_cli("--config", str(self.cfg), "install")
        self.assertEqual(code, 1)
        self.assertIn("roster is invalid", err)

    def test_install_legacy_left_in_place_without_tty(self):
        (code, out, _), ip, rl = self.install(InstallResult(), ["startup_captain"])
        self.assertEqual(code, 0)
        self.assertIn("Left in place", out)
        rl.assert_not_called()
        self.assertFalse(ip.call_args.kwargs["replace_legacy"])

    def test_install_remove_legacy_flag(self):
        (code, out, _), ip, rl = self.install(
            InstallResult(), ["startup_captain"], "--remove-legacy", "--replace-legacy"
        )
        self.assertEqual(code, 0)
        rl.assert_called_once()
        self.assertIn("Moved to", out)
        self.assertTrue(ip.call_args.kwargs["replace_legacy"])

    def test_install_legacy_prompt_yes_and_no(self):
        (_, out, _), _, rl = self.install(InstallResult(), ["a"], tty=True, answers=["y"])
        rl.assert_called_once()
        self.assertIn("Moved to", out)
        (_, out, _), _, rl = self.install(InstallResult(), ["a"], tty=True, answers=["n"])
        rl.assert_not_called()

    def test_install_without_legacy_is_quiet(self):
        (code, out, _), _, _ = self.install(InstallResult(), [])
        self.assertEqual((code, out), (0, ""))

    def test_init_missing_config_and_non_git(self):
        code, _, err = run_cli("--config", str(self.tmp / "none.toml"), "init", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertIn("config not found", err)
        self.create()
        code, _, err = run_cli("--config", str(self.cfg), "init", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertIn("git", err)

    def test_init_on_git_repo_and_rerun(self):
        self.create()
        repo = self.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / "Makefile").write_text("test:\n\techo\n")
        code, out, _ = run_cli("--config", str(self.cfg), "init", str(repo))
        self.assertEqual(code, 0)
        self.assertIn("make test", out)
        self.assertIn(".gitignore updated", out)
        self.assertTrue((repo / ".company" / "ROSTER.md").is_file())
        code, out, _ = run_cli("--config", str(self.cfg), "init", str(repo))
        self.assertEqual(code, 0)
        self.assertIn("  kept: .company/COMPANY.md", out)

    def test_init_reports_warning_note_and_no_suggestion(self):
        self.create()
        repo = self.tmp / "repo2"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / ".gitignore").write_text(".company/\n")
        code, out, _ = run_cli("--config", str(self.cfg), "init", str(repo))
        self.assertEqual(code, 0)
        self.assertIn("WARNING: .gitignore already ignores", out)
        self.assertIn("No validation command detected", out)
        # npm project without node_modules prints the note line.
        repo3 = self.tmp / "repo3"
        repo3.mkdir()
        subprocess.run(["git", "-C", str(repo3), "init", "-q"], check=True)
        (repo3 / "package.json").write_text('{"scripts": {"test": "jest"}}')
        _, out, _ = run_cli("--config", str(self.cfg), "init", str(repo3))
        self.assertIn("note: node_modules is missing", out)

    def test_init_ci_hint_without_command(self):
        self.create()
        repo = self.tmp / "repo4"
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        _, out, _ = run_cli("--config", str(self.cfg), "init", str(repo))
        self.assertIn("(none) CI workflow found", out)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
