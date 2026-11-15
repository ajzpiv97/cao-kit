import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from caokit import cli
from caokit.config import Binding, ConfigError, dump_config, load_config, roles_dir
from caokit.init_project import init_project
from caokit.install import render_all
from caokit.project import Overrides, effective_config
from caokit.render import check_role_text
from caokit.roles import RoleError, add_role, list_roles, remove_role, template
from caokit.roster import check_roster
from tests.test_session import good_config
from tests.test_workflow import agy_runner


class RoleFileTests(unittest.TestCase):
    def test_the_starter_template_passes_its_own_checks(self):
        self.assertEqual(check_role_text(template("auditor")), ([], []))

    def test_unsafe_or_unusable_role_files_are_rejected(self):
        good = template("auditor")
        cases = [
            ("# no frontmatter\n", "no frontmatter"),
            (good.replace("role: researcher\n", ""), "no `role:` line"),
            (good.replace('  - "fs_read"', '  - "*"'), "bypasses every restriction"),
            (good.replace("role: researcher", "name: x\nrole: researcher"), "`name:` line"),
            ("\n".join(x for x in good.split("\n") if not x.startswith("desc")), "description"),
        ]
        for text, expected in cases:
            errors, _ = check_role_text(text)
            self.assertTrue(any(expected in e for e in errors), (expected, errors))

    def test_a_role_that_cannot_report_back_is_a_warning(self):
        text = template("auditor").replace('  - "@cao-mcp-server"\n', "")
        errors, warnings = check_role_text(text.replace("cao-mcp-server", "other"))
        self.assertEqual(errors, [])
        self.assertIn("cannot report back", warnings[0])


class CustomRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg_path = self.root / "home" / "caokit.toml"
        self.cfg_path.parent.mkdir()
        self.cfg_path.write_text(dump_config(good_config()))
        self.repo = self.root / "proj"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)

    def init_project(self, name="pj"):
        init_project(self.repo, load_config(self.cfg_path), agy_runner, Overrides(name=name))

    def test_add_writes_the_template_binds_the_role_and_renders_a_profile(self):
        res = add_role("auditor", Binding("claude", "sonnet"), self.cfg_path)
        self.assertEqual(
            (res.created, res.role_file), (True, roles_dir(self.cfg_path) / "auditor.md")
        )
        cfg = load_config(self.cfg_path)
        self.assertEqual(list(cfg.roles), ["general", "engineer", "scout", "inspector", "auditor"])
        self.assertEqual(check_roster(cfg).errors, [])
        profile = render_all(cfg)["auditor-claude"]
        self.assertIn("name: auditor-claude\n", profile)
        self.assertIn('provider: claude_code\nmodel: "sonnet"\n', profile)
        self.assertIn("# Auditor", profile)

    def test_add_keeps_an_existing_role_file(self):
        mine = template("auditor").replace("# Auditor", "# My auditor")
        roles_dir(self.cfg_path).mkdir()
        (roles_dir(self.cfg_path) / "auditor.md").write_text(mine)
        res = add_role("auditor", Binding("claude"), self.cfg_path)
        self.assertFalse(res.created)
        self.assertEqual(res.role_file.read_text(), mine)

    def test_add_from_a_file_copies_it(self):
        src = self.root / "x.md"
        src.write_text(template("auditor").replace("# Auditor", "# From file"))
        res = add_role("auditor", Binding("claude"), self.cfg_path, source=src)
        self.assertIn("# From file", res.role_file.read_text())

    def test_a_rejected_role_leaves_no_file_and_no_binding(self):
        before = self.cfg_path.read_text()
        with self.assertRaisesRegex(RoleError, "unknown tool"):
            add_role("auditor", Binding("nosuchtool"), self.cfg_path)
        bad = self.root / "bad.md"
        bad.write_text(template("auditor").replace('  - "fs_read"', '  - "*"'))
        with self.assertRaisesRegex(RoleError, "bypasses"):
            add_role("auditor", Binding("claude"), self.cfg_path, source=bad)
        self.assertEqual(self.cfg_path.read_text(), before)
        self.assertFalse((roles_dir(self.cfg_path) / "auditor.md").exists())

    def test_built_in_and_malformed_names_are_refused(self):
        for name in ("general", "engineer", "My-Role", "a_b", ""):
            with self.assertRaises(RoleError, msg=name):
                add_role(name, Binding("claude"), self.cfg_path)

    def test_a_file_named_like_a_built_in_role_never_replaces_it(self):
        roles_dir(self.cfg_path).mkdir()
        (roles_dir(self.cfg_path) / "general.md").write_text(template("general"))
        profile = render_all(load_config(self.cfg_path))["general-claude"]
        self.assertNotIn("one line saying what this role is for", profile)

    def test_a_custom_role_on_a_soft_tool_is_flagged_as_advisory(self):
        res = add_role("auditor", Binding("antigravity"), self.cfg_path, runner=agy_runner)
        self.assertTrue(any("advisory only" in w for w in res.warnings), res.warnings)

    def test_project_role_is_namespaced_listed_in_the_roster_and_not_user_level(self):
        self.init_project()
        res = add_role("auditor", Binding("claude", "haiku"), self.cfg_path, repo=self.repo)
        self.assertEqual(res.role_file, self.repo / ".caokit" / "roles" / "auditor.md")
        self.assertNotIn("auditor", load_config(self.cfg_path).roles)
        cfg = effective_config(self.repo, load_config(self.cfg_path))
        self.assertIn("pj_auditor-claude", render_all(cfg))
        roster = (self.repo / ".caokit" / "ROSTER.md").read_text()
        self.assertIn("| auditor | `pj_auditor-claude` | claude | haiku |", roster)
        self.assertIn("## Custom roles", roster)
        self.assertIn("- `auditor`: auditor: one line saying", roster)

    def test_a_project_can_rebind_a_user_level_custom_role(self):
        add_role("auditor", Binding("claude", "sonnet"), self.cfg_path)
        self.init_project()
        add_role("auditor", Binding("claude", "haiku"), self.cfg_path, repo=self.repo)
        cfg = effective_config(self.repo, load_config(self.cfg_path))
        self.assertEqual(cfg.roles["auditor"], Binding("claude", "haiku"))
        # The user-level file is reused: nothing was copied into the project.
        self.assertFalse((self.repo / ".caokit" / "roles" / "auditor.md").exists())

    def test_a_project_only_role_needs_a_tool(self):
        self.init_project()
        (self.repo / ".caokit" / "caokit.toml").write_text(
            'schema = 1\n[project]\nname = "pj"\n[roles.auditor]\nmodel = "haiku"\n'
        )
        with self.assertRaisesRegex(ConfigError, "roles.auditor: no tool"):
            effective_config(self.repo, load_config(self.cfg_path))

    def test_remove_unbinds_and_keeps_the_file(self):
        res = add_role("auditor", Binding("claude"), self.cfg_path)
        remove_role("auditor", self.cfg_path)
        self.assertNotIn("auditor", load_config(self.cfg_path).roles)
        self.assertTrue(res.role_file.exists())
        with self.assertRaisesRegex(RoleError, "not bound"):
            remove_role("auditor", self.cfg_path)

    def test_list_shows_built_in_bound_and_unbound_roles(self):
        add_role("auditor", Binding("claude"), self.cfg_path)
        (roles_dir(self.cfg_path) / "spare.md").write_text(template("spare"))
        rows = {r.name: r for r in list_roles(load_config(self.cfg_path))}
        self.assertEqual(list(rows)[:4], ["general", "engineer", "scout", "inspector"])
        self.assertTrue(rows["general"].builtin)
        self.assertEqual(rows["auditor"].binding, Binding("claude"))
        self.assertIsNone(rows["spare"].binding)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", str(self.cfg_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_cli_add_list_remove(self):
        code, out, _ = self.run_cli("role", "add", "auditor", "claude:sonnet")
        self.assertEqual(code, 0)
        self.assertIn("caokit install", out)
        code, out, _ = self.run_cli("role", "list")
        self.assertIn("auditor      custom    claude:sonnet", out)
        self.assertEqual(self.run_cli("role", "remove", "auditor")[0], 0)
        code, _, err = self.run_cli("role", "add", "general", "claude")
        self.assertEqual((code, "built-in role" in err), (1, True))
        self.assertEqual(self.run_cli("role", "add", "auditor")[0], 2)


if __name__ == "__main__":
    unittest.main()
