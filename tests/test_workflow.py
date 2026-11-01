import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from caokit.adapters import ProcessResult
from caokit.company import CompanyError, create_company, parse_binding, write_company
from caokit.config import Binding, Config
from caokit.init_project import InitError, init_project
from caokit.install import InstallError, find_legacy, install_profiles, remove_legacy, render_all

GOOD = Config(
    roles={
        "general": Binding("claude", "sonnet"),
        "engineer": Binding("claude", "opus"),
        "scout": Binding("antigravity", "gemini-3.8-flash-medium"),
        "inspector": Binding("antigravity", "gemini-4-argon-high"),
    }
)
AGY_MODELS = "gemini-4-argon-high\tG\ngemini-3.8-flash-medium\tF\nclaude-opus-5-5-high\tC\n"


class R:
    def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


def agy_runner(argv: Sequence[str]) -> ProcessResult:
    if list(argv) == ["agy", "models"]:
        return R(0, "Fetching available models...\n" + AGY_MODELS)
    return R(1)


class CompanyTests(unittest.TestCase):
    def test_valid(self):
        cfg = create_company(GOOD.roles, runner=agy_runner, out=lambda *_: None)
        self.assertEqual(cfg.roles["inspector"].model, "gemini-4-argon-high")

    def test_unlisted_model_rejected(self):
        b = dict(GOOD.roles, inspector=Binding("antigravity", "gemini-9-nope"))
        with self.assertRaisesRegex(CompanyError, "not listed"):
            create_company(b, runner=agy_runner, out=lambda *_: None)

    def test_not_logged_in_is_clear_error(self):
        with self.assertRaisesRegex(CompanyError, "cannot validate model"):
            create_company(
                GOOD.roles, runner=lambda a: R(1, "", "not logged in"), out=lambda *_: None
            )

    def test_guardrail_surfaces(self):
        b = dict(GOOD.roles, inspector=Binding("antigravity", "claude-opus-5-5-high"))
        with self.assertRaisesRegex(CompanyError, "vendor"):
            create_company(b, runner=agy_runner, out=lambda *_: None)

    def test_non_recommended_only_warns(self):
        msgs: list[str] = []
        b = dict(GOOD.roles, general=Binding("claude", "haiku"))
        create_company(b, runner=agy_runner, out=msgs.append)
        self.assertTrue(any("recommended" in m for m in msgs))

    def test_parse_binding(self):
        self.assertEqual(parse_binding("claude:opus"), Binding("claude", "opus"))
        self.assertEqual(parse_binding("claude"), Binding("claude", None))

    def test_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "sub" / "caokit.toml"
            write_company(GOOD, p)
            with self.assertRaises(CompanyError):
                write_company(GOOD, p)
            write_company(GOOD, p, force=True)


class FakeCao:
    """Mimics `cao profile validate` / `cao install` against a temp CAO home."""

    def __init__(self, home: Any, refuse: Iterable[str] = ()) -> None:
        self.home = Path(home)
        self.refuse = set(refuse)
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> ProcessResult:
        self.calls.append(list(argv))
        if argv[:3] == ["cao", "profile", "validate"]:
            return R(0, "ok")
        if argv[:2] == ["cao", "install"]:
            src = Path(argv[2])
            name = src.stem
            dest = self.home / "agent-store" / (name + ".md")
            if name in self.refuse and dest.exists():
                return R(
                    0, "Error: installed copy without CAO source provenance"
                )  # exit 0, like real CAO
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            return R(0, "installed")
        return R(1)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.home = Path(self.t.name)

    def test_installs_four_verified(self):
        res = install_profiles(GOOD, self.home, FakeCao(self.home), out=lambda *_: None)
        self.assertEqual(sorted(res.installed), sorted(render_all(GOOD)))
        self.assertEqual(res.failed, [])

    def test_error_text_with_exit_zero_fails(self):
        (self.home / "agent-store").mkdir()
        (self.home / "agent-store" / "engineer-claude.md").write_text("stale")
        res = install_profiles(
            GOOD, self.home, FakeCao(self.home, refuse={"engineer-claude"}), out=lambda *_: None
        )
        self.assertEqual(res.failed, ["engineer-claude"])

    def test_replace_legacy_backs_up_and_retries(self):
        (self.home / "agent-store").mkdir()
        (self.home / "agent-store" / "engineer-claude.md").write_text("stale")
        res = install_profiles(
            GOOD,
            self.home,
            FakeCao(self.home, refuse={"engineer-claude"}),
            replace_legacy=True,
            out=lambda *_: None,
        )
        self.assertEqual(res.failed, [])
        assert res.backup_dir is not None
        self.assertTrue((res.backup_dir / "agent-store" / "engineer-claude.md").exists())

    def test_verification_catches_drift(self):
        class Drift(FakeCao):
            def __call__(self, argv: Sequence[str]) -> ProcessResult:
                r = super().__call__(argv)
                if argv[:2] == ["cao", "install"]:
                    (self.home / "agent-store" / (Path(argv[2]).stem + ".md")).write_text("changed")
                return r

        res = install_profiles(GOOD, self.home, Drift(self.home), out=lambda *_: None)
        self.assertEqual(len(res.failed), 4)

    def test_invalid_roster_blocks_install(self):
        bad = Config(roles=dict(GOOD.roles, inspector=Binding("claude", "sonnet")))
        with self.assertRaises(InstallError):
            install_profiles(bad, self.home, FakeCao(self.home))

    def test_validate_failure_skips_install(self):
        fake = FakeCao(self.home)
        fake.__class__ = type(
            "V",
            (FakeCao,),
            {
                "__call__": lambda s, a: (
                    R(1, "[error] x")
                    if a[:3] == ["cao", "profile", "validate"]
                    else FakeCao.__call__(s, a)
                )
            },
        )
        res = install_profiles(GOOD, self.home, fake, out=lambda *_: None)
        self.assertEqual(len(res.failed), 4)
        self.assertFalse(any(c[:2] == ["cao", "install"] for c in fake.calls))

    def test_legacy_found_and_moved_not_deleted(self):
        for sub in ("agent-store", "agent-context"):
            (self.home / sub).mkdir()
            (self.home / sub / "startup_captain.md").write_text("x")
        self.assertEqual(find_legacy(self.home), ["startup_captain"])
        backup = remove_legacy(self.home, ["startup_captain"])
        assert backup is not None
        self.assertEqual(find_legacy(self.home), [])
        self.assertTrue((backup / "agent-store" / "startup_captain.md").exists())


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True)


class InitTests(unittest.TestCase):
    def repo(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        r = Path(t.name)
        git(r, "init", "-q")
        return r

    def test_refuses_non_git(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(InitError, "git"):
            init_project(Path(t), GOOD)

    def test_scaffold_roster_and_gitignore(self):
        r = self.repo()
        (r / ".gitignore").write_text("node_modules/\n")
        res = init_project(r, GOOD)
        for rel in (
            ".company/COMPANY.md",
            ".company/ROSTER.md",
            ".company/contracts/REVIEW_CONTRACT.md",
            ".company/tasks/TASK_TEMPLATE.md",
            ".company/reviews",
            ".company/handoffs",
        ):
            self.assertTrue((r / rel).exists(), rel)
        roster = (r / ".company/ROSTER.md").read_text()
        for name in (
            "general-claude",
            "engineer-claude",
            "scout-antigravity",
            "inspector-antigravity",
        ):
            self.assertIn(name, roster)
        self.assertIn("Suggested validation command", roster)
        gi = (r / ".gitignore").read_text()
        self.assertTrue(gi.startswith("node_modules/\n"))
        self.assertEqual(res.warnings, [])

    def test_git_actually_ignores_all_but_contracts(self):
        r = self.repo()
        init_project(r, GOOD)
        (r / ".company/tasks/TASK-0002-x.md").write_text("x")
        self.assertEqual(
            git(r, "check-ignore", "-q", ".company/tasks/TASK-0002-x.md").returncode, 0
        )
        self.assertEqual(git(r, "check-ignore", "-q", ".company/ROSTER.md").returncode, 0)
        self.assertEqual(
            git(r, "check-ignore", "-q", ".company/contracts/REVIEW_CONTRACT.md").returncode, 1
        )

    def test_never_overwrites_and_is_idempotent(self):
        r = self.repo()
        init_project(r, GOOD)
        (r / ".company/COMPANY.md").write_text("MINE")
        gi_before = (r / ".gitignore").read_text()
        res = init_project(r, GOOD)
        self.assertEqual((r / ".company/COMPANY.md").read_text(), "MINE")
        self.assertIn(".company/COMPANY.md", res.kept)
        self.assertEqual((r / ".gitignore").read_text(), gi_before)

    def test_warns_when_company_already_ignored(self):
        r = self.repo()
        (r / ".gitignore").write_text(".company/\n")
        res = init_project(r, GOOD)
        self.assertTrue(res.warnings)

    def test_suggestion_in_roster(self):
        r = self.repo()
        (r / "Makefile").write_text("test:\n\techo\n")
        init_project(r, GOOD)
        self.assertIn("make test", (r / ".company/ROSTER.md").read_text())


@unittest.skipUnless(shutil.which("cao"), "cao not installed")
class RealCaoTempHomeTests(unittest.TestCase):
    def test_real_cao_install_in_temp_home(self):
        from caokit.adapters import default_runner

        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            old: str | None = os.environ.get("HOME")
            os.environ["HOME"] = t
            try:
                res = install_profiles(
                    GOOD,
                    home / ".aws" / "cli-agent-orchestrator",
                    default_runner,
                    out=lambda *_: None,
                )
            finally:
                if old is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old
            self.assertEqual(res.failed, [], res)
            self.assertEqual(len(res.installed), 4)


if __name__ == "__main__":
    unittest.main()
