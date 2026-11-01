"""Tests for per-project namespacing: names, overrides, init, install, CLI."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from caokit import cli
from caokit.adapters import ROLES, load_adapter
from caokit.config import Binding, Config, ConfigError, dump_config, parse_config
from caokit.init_project import InitError, init_project
from caokit.install import install_profiles, render_all
from caokit.project import (
    PROJECT_FILE,
    Overrides,
    apply_overrides,
    check_effective,
    dump_overrides,
    effective_config,
    load_overrides,
    parse_override_specs,
    parse_overrides,
    resolve_project,
)
from caokit.render import profile_name, render_profile, validate_project_name
from tests.test_workflow import GOOD, FakeCao, agy_runner


def git_repo(testcase: unittest.TestCase) -> Path:
    """Create a temp git repo that is removed after the test."""
    t = tempfile.TemporaryDirectory()
    testcase.addCleanup(t.cleanup)
    subprocess.run(["git", "-C", t.name, "init", "-q"], check=True)
    return Path(t.name)


class NamingTests(unittest.TestCase):
    def test_project_name_rules(self):
        for ok in ("myapp", "my-app", "a", "proj2", "a" * 24):
            self.assertEqual(validate_project_name(ok), ok)
        for bad in ("", "My", "my_app", "-x", "a" * 25, "a b", "a.b", "../x"):
            with self.assertRaises(ValueError, msg=bad):
                validate_project_name(bad)

    def test_namespaced_profile_name(self):
        self.assertEqual(profile_name("engineer", "claude", "myapp"), "myapp_engineer-claude")
        self.assertEqual(profile_name("engineer", "claude"), "engineer-claude")
        longest = profile_name("inspector", "antigravity", "a" * 24)
        self.assertLessEqual(len(longest), 64)

    def test_render_profile_uses_namespaced_name(self):
        out = render_profile("engineer", load_adapter("claude"), "opus", "myapp")
        self.assertTrue(out.startswith("---\nname: myapp_engineer-claude\n"))

    def test_render_all_names(self):
        shared = set(render_all(GOOD))
        self.assertIn("engineer-claude", shared)
        scoped = Config(roles=GOOD.roles, project="myapp")
        self.assertEqual(
            set(render_all(scoped)),
            {f"myapp_{n}" for n in shared},
        )


class ConfigProjectTests(unittest.TestCase):
    def test_project_roundtrip_in_user_config(self):
        c = Config(roles=GOOD.roles, project="myapp")
        self.assertEqual(parse_config(__import__("tomllib").loads(dump_config(c))), c)

    def test_bad_project_name_in_config(self):
        d = __import__("tomllib").loads(dump_config(GOOD))
        d["project"] = {"name": "Bad_Name"}
        with self.assertRaises(ConfigError):
            parse_config(d)


class OverridesTests(unittest.TestCase):
    def test_roundtrip(self):
        ov = Overrides(
            "myapp",
            roles={"engineer": {"model": "sonnet"}, "inspector": {"tool": "claude", "model": "x"}},
            policy={"allow_soft_engineer": True},
        )
        parsed = parse_overrides(__import__("tomllib").loads(dump_overrides(ov)))
        self.assertEqual(parsed, ov)

    def test_parse_errors(self):
        base: dict[str, Any] = {"schema": 1, "project": {"name": "myapp"}}
        cases: list[tuple[dict[str, Any], str]] = [
            ({"schema": 2, "project": {"name": "a"}}, "schema"),
            ({"schema": 1}, "project.name"),
            ({"schema": 1, "project": {"name": "Bad"}}, "invalid project name"),
            ({**base, "roles": {"colonel": {"tool": "claude"}}}, "unknown role"),
            ({**base, "roles": {"engineer": {"modle": "x"}}}, "roles.engineer.modle"),
            ({**base, "roles": {"engineer": {"model": ""}}}, "non-empty"),
            ({**base, "policy": {"allow_soft_engineer": "yes"}}, "true or false"),
            ({**base, "extra": 1}, "unknown key"),
        ]
        for d, msg in cases:
            with self.assertRaisesRegex(ConfigError, msg):
                parse_overrides(d)

    def test_apply_model_only_keeps_tool(self):
        eff = apply_overrides(GOOD, Overrides("p", roles={"engineer": {"model": "sonnet"}}))
        self.assertEqual(eff.roles["engineer"], Binding("claude", "sonnet"))
        self.assertEqual(eff.project, "p")

    def test_apply_tool_change_drops_base_model(self):
        eff = apply_overrides(GOOD, Overrides("p", roles={"scout": {"tool": "claude"}}))
        self.assertEqual(eff.roles["scout"], Binding("claude", None))

    def test_apply_tool_and_model(self):
        ov = Overrides("p", roles={"scout": {"tool": "claude", "model": "haiku"}})
        self.assertEqual(apply_overrides(GOOD, ov).roles["scout"], Binding("claude", "haiku"))

    def test_apply_policy_and_base_untouched(self):
        ov = Overrides(
            "p", roles={"engineer": {"model": "x"}}, policy={"allow_soft_engineer": True}
        )
        eff = apply_overrides(GOOD, ov)
        self.assertTrue(eff.allow_soft_engineer)
        self.assertEqual(GOOD.roles["engineer"].model, "opus")
        self.assertFalse(GOOD.allow_soft_engineer)
        self.assertIsNone(GOOD.project)

    def test_specs(self):
        self.assertEqual(
            parse_override_specs(["engineer=claude:sonnet", "scout=:flash", "inspector=claude"]),
            {
                "engineer": {"tool": "claude", "model": "sonnet"},
                "scout": {"model": "flash"},
                "inspector": {"tool": "claude"},
            },
        )

    def test_bad_specs(self):
        for bad in ("engineer", "colonel=claude", "engineer=", "=claude"):
            with self.assertRaises(ConfigError, msg=bad):
                parse_override_specs([bad])

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(ConfigError, "no project"):
            load_overrides(Path(t))

    def test_load_invalid_toml(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".company").mkdir()
            (Path(t) / PROJECT_FILE).write_text("not = [valid")
            with self.assertRaisesRegex(ConfigError, "invalid TOML"):
                load_overrides(Path(t))


class ResolveTests(unittest.TestCase):
    def test_no_name_no_file_is_unscoped(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, new = resolve_project(Path(t), GOOD, None, [])
        self.assertIs(cfg, GOOD)
        self.assertIsNone(new)

    def test_override_without_name_errors(self):
        with self.assertRaisesRegex(ConfigError, "--name"):
            resolve_project(Path("."), GOOD, None, ["engineer=:sonnet"])

    def test_bad_name_errors(self):
        with self.assertRaisesRegex(ConfigError, "invalid project name"):
            resolve_project(Path("."), GOOD, "Bad_Name", [])

    def test_name_builds_new_overrides(self):
        cfg, new = resolve_project(Path("."), GOOD, "myapp", ["engineer=:sonnet"])
        self.assertEqual(cfg.project, "myapp")
        self.assertEqual(cfg.roles["engineer"].model, "sonnet")
        self.assertEqual(new, Overrides("myapp", roles={"engineer": {"model": "sonnet"}}))

    def test_existing_file_loaded(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".company").mkdir()
            (Path(t) / PROJECT_FILE).write_text(dump_overrides(Overrides("saved")))
            cfg, new = resolve_project(Path(t), GOOD, None, [])
            self.assertEqual(cfg.project, "saved")
            self.assertIsNone(new)
            self.assertEqual(effective_config(Path(t), GOOD).project, "saved")


class CheckEffectiveTests(unittest.TestCase):
    def test_override_breaking_cross_provider_is_error(self):
        ov = Overrides("p", roles={"inspector": {"tool": "claude", "model": "sonnet"}})
        errors, _ = check_effective(apply_overrides(GOOD, ov), ov, agy_runner)
        self.assertTrue(any("cross-provider" in e for e in errors), errors)

    def test_overridden_model_validated_against_tool(self):
        ov = Overrides("p", roles={"inspector": {"model": "gemini-9-nope"}})
        errors, _ = check_effective(apply_overrides(GOOD, ov), ov, agy_runner)
        self.assertTrue(any("not listed" in e for e in errors), errors)

    def test_valid_override_passes(self):
        ov = Overrides("p", roles={"scout": {"model": "gemini-4-argon-high"}})
        errors, _ = check_effective(apply_overrides(GOOD, ov), ov, agy_runner)
        self.assertEqual(errors, [])

    def test_unknown_tool_reported_once_by_roster(self):
        ov = Overrides("p", roles={"scout": {"tool": "nope", "model": "x"}})
        errors, _ = check_effective(apply_overrides(GOOD, ov), ov, agy_runner)
        self.assertTrue(any("unknown tool" in e for e in errors))


class InitProjectTests(unittest.TestCase):
    def test_init_with_overrides_writes_file_and_namespaced_roster(self):
        repo = git_repo(self)
        ov = Overrides("myapp", roles={"engineer": {"model": "sonnet"}})
        init_project(repo, apply_overrides(GOOD, ov), overrides=ov)
        self.assertEqual(load_overrides(repo), ov)
        roster = (repo / ".company/ROSTER.md").read_text()
        for role in ROLES:
            self.assertIn(f"myapp_{role}-", roster)
        self.assertIn("sonnet", roster)
        self.assertIn("project `myapp`", roster)

    def test_project_file_is_git_ignored(self):
        repo = git_repo(self)
        ov = Overrides("myapp")
        init_project(repo, apply_overrides(GOOD, ov), overrides=ov)
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".company/caokit.toml"])
        self.assertEqual(r.returncode, 0)

    def test_existing_project_file_protected(self):
        repo = git_repo(self)
        ov = Overrides("myapp")
        cfg = apply_overrides(GOOD, ov)
        init_project(repo, cfg, overrides=ov)
        with self.assertRaisesRegex(InitError, "already exists"):
            init_project(repo, cfg, overrides=ov)
        ov2 = Overrides("myapp", roles={"engineer": {"model": "haiku"}})
        init_project(repo, apply_overrides(GOOD, ov2), overrides=ov2, force_project=True)
        self.assertEqual(load_overrides(repo), ov2)

    def test_rerun_without_overrides_keeps_file(self):
        repo = git_repo(self)
        ov = Overrides("myapp")
        cfg = apply_overrides(GOOD, ov)
        init_project(repo, cfg, overrides=ov)
        before = (repo / PROJECT_FILE).read_text()
        init_project(repo, cfg)  # e.g. refresh ROSTER.md only
        self.assertEqual((repo / PROJECT_FILE).read_text(), before)


class TwoProjectInstallTests(unittest.TestCase):
    """The reason for namespacing: two projects must not overwrite each other."""

    def test_projects_with_different_models_coexist(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            fake = FakeCao(home)
            cfg_a = apply_overrides(GOOD, Overrides("proja", roles={"engineer": {"model": "opus"}}))
            cfg_b = apply_overrides(
                GOOD, Overrides("projb", roles={"engineer": {"model": "sonnet"}})
            )
            for cfg in (GOOD, cfg_a, cfg_b):
                res = install_profiles(cfg, home, fake, out=lambda *_: None)
                self.assertEqual(res.failed, [])
            store = home / "agent-store"
            self.assertIn('model: "opus"', (store / "proja_engineer-claude.md").read_text())
            self.assertIn('model: "sonnet"', (store / "projb_engineer-claude.md").read_text())
            self.assertEqual(len(list(store.glob("*.md"))), 12)  # 3 sets of 4, none overwritten

    def test_reinstall_one_project_leaves_the_other_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            fake = FakeCao(home)
            a = apply_overrides(GOOD, Overrides("proja"))
            b = apply_overrides(GOOD, Overrides("projb", roles={"engineer": {"model": "sonnet"}}))
            install_profiles(a, home, fake, out=lambda *_: None)
            install_profiles(b, home, fake, out=lambda *_: None)
            before = (home / "agent-store/proja_engineer-claude.md").read_bytes()
            install_profiles(b, home, fake, out=lambda *_: None)
            self.assertEqual((home / "agent-store/proja_engineer-claude.md").read_bytes(), before)


class CliProjectTests(unittest.TestCase):
    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.dict(os.environ, env or {}),
        ):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def config(self, tmp: Path) -> Path:
        p = tmp / "caokit.toml"
        p.write_text(dump_config(GOOD))
        return p

    def test_init_with_name_prints_next_steps(self):
        repo = git_repo(self)
        with tempfile.TemporaryDirectory() as t:
            cfg = self.config(Path(t))
            fake = mock.patch("caokit.project.default_runner", agy_runner)
            with fake, mock.patch("caokit.cli.check_effective", return_value=([], [])):
                code, out, err = self.run_cli(
                    "--config",
                    str(cfg),
                    "init",
                    str(repo),
                    "--name",
                    "myapp",
                    "--override",
                    "engineer=:sonnet",
                )
        self.assertEqual(code, 0, err)
        self.assertIn("caokit install --project", out)
        self.assertIn("--agents myapp_general-claude --session-name myapp", out)
        self.assertIn(f"--working-directory {repo.resolve()}", out)
        self.assertEqual(load_overrides(repo).roles["engineer"], {"model": "sonnet"})

    def test_init_bad_override_exits_1(self):
        repo = git_repo(self)
        with tempfile.TemporaryDirectory() as t:
            cfg = self.config(Path(t))
            code, _, err = self.run_cli(
                "--config", str(cfg), "init", str(repo), "--override", "engineer=:x"
            )
        self.assertEqual(code, 1)
        self.assertIn("--name", err)

    def test_init_roster_violation_exits_1_and_writes_nothing(self):
        repo = git_repo(self)
        with tempfile.TemporaryDirectory() as t:
            cfg = self.config(Path(t))
            with mock.patch(
                "caokit.cli.check_effective",
                return_value=(["cross-provider inspection violated: x"], []),
            ):
                code, _, err = self.run_cli(
                    "--config",
                    str(cfg),
                    "init",
                    str(repo),
                    "--name",
                    "myapp",
                    "--override",
                    "inspector=claude:sonnet",
                )
        self.assertEqual(code, 1)
        self.assertIn("cross-provider", err)
        self.assertFalse((repo / ".company").exists())

    def test_install_project_requires_project_file(self):
        repo = git_repo(self)
        with tempfile.TemporaryDirectory() as t:
            cfg = self.config(Path(t))
            code, _, err = self.run_cli("--config", str(cfg), "install", "--project", str(repo))
        self.assertEqual(code, 1)
        self.assertIn("no project config", err)

    def test_install_project_installs_namespaced(self):
        repo = git_repo(self)
        ov = Overrides("myapp", roles={"engineer": {"model": "sonnet"}})
        init_project(repo, apply_overrides(GOOD, ov), overrides=ov)
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "cao"
            cfg = self.config(Path(t))
            fake = FakeCao(home)
            env = {"CAO_HOME_DIR": str(home)}
            with (
                mock.patch("caokit.install.default_runner", fake),
                mock.patch(
                    "caokit.cli.install_profiles",
                    lambda c, h, **kw: install_profiles(c, h, fake, out=lambda *_: None, **kw),
                ),
            ):
                code, out, err = self.run_cli(
                    "--config", str(cfg), "install", "--project", str(repo), env=env
                )
            self.assertEqual(code, 0, err)
            names = sorted(p.stem for p in (home / "agent-store").glob("*.md"))
        self.assertEqual(
            names,
            [f"myapp_{r}-{GOOD.roles[r].tool}" for r in sorted(ROLES)],
        )


if __name__ == "__main__":
    unittest.main()
