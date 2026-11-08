import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caokit import cli, worktrees
from caokit.config import ConfigError
from caokit.project import (
    dump_overrides,
    load_overrides,
    parse_overrides,
    set_worktrees,
    worktrees_enabled,
)

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def git(repo, *args):
    return subprocess.run(
        ["git", *GIT_ID, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def make_repo(root: Path, commit=True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    if commit:
        (root / "a.txt").write_text("a")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
    return root


class ProjectSettingTests(unittest.TestCase):
    def test_worktrees_round_trips_and_defaults_off(self):
        d = {"schema": 1, "project": {"name": "pj"}}
        self.assertFalse(parse_overrides(d).worktrees)
        on = parse_overrides({**d, "tasks": {"worktrees": True, "keep_archived_days": 7}})
        again = parse_overrides(__import__("tomllib").loads(dump_overrides(on)))
        self.assertEqual((again.worktrees, again.keep_archived_days), (True, 7))
        self.assertNotIn("worktrees", dump_overrides(parse_overrides(d)))

    def test_worktrees_must_be_a_boolean(self):
        with self.assertRaises(ConfigError):
            parse_overrides({"schema": 1, "project": {"name": "pj"}, "tasks": {"worktrees": "on"}})

    def test_enabled_is_false_without_a_project_file(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(worktrees_enabled(Path(t)))


class RepoChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_not_a_git_repo(self):
        errors, _ = worktrees.problems(self.root)
        self.assertTrue(errors and "not a git repository" in errors[0])

    def test_repo_without_commits_is_an_error(self):
        make_repo(self.root / "r", commit=False)
        errors, _ = worktrees.problems(self.root / "r")
        self.assertTrue(any("no commits" in e for e in errors))

    def test_subdirectory_of_a_repo_is_an_error(self):
        repo = make_repo(self.root / "r")
        (repo / "sub").mkdir()
        errors, _ = worktrees.problems(repo / "sub")
        self.assertTrue(any("run caokit on its root" in e for e in errors))

    def test_clean_repo_is_fine_and_dirty_repo_warns(self):
        repo = make_repo(self.root / "r")
        self.assertEqual(worktrees.problems(repo), ([], []))
        (repo / "a.txt").write_text("changed")
        errors, warnings = worktrees.problems(repo)
        self.assertEqual((errors, len(warnings)), ([], 1))

    def test_missing_git_binary_is_reported_not_raised(self):
        def runner(argv):
            raise FileNotFoundError("git")

        errors, _ = worktrees.problems(self.root, runner)
        self.assertTrue(errors)


class ListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name).resolve() / "r")

    def add_worktree(self, name):
        path = self.repo / ".cao" / "worktrees" / name
        git(self.repo, "worktree", "add", "-q", "-b", f"cao/{name}", str(path))
        return path

    def test_nothing_when_cao_made_no_branches(self):
        git(self.repo, "branch", "feature")
        self.assertEqual(worktrees.list_task_worktrees(self.repo), [])

    def test_reports_unmerged_commits_dirty_checkout_and_orphan_branch(self):
        a = self.add_worktree("aaaa1111")
        (a / "new.txt").write_text("x")
        git(a, "add", "-A")
        git(a, "commit", "-q", "-m", "work")
        b = self.add_worktree("bbbb2222")
        (b / "a.txt").write_text("dirty")
        c = self.add_worktree("cccc3333")
        git(self.repo, "worktree", "remove", "--force", str(c))  # CAO removed it; branch stays
        by = {w.branch: w for w in worktrees.list_task_worktrees(self.repo)}
        self.assertEqual(sorted(by), ["cao/aaaa1111", "cao/bbbb2222", "cao/cccc3333"])
        self.assertEqual((by["cao/aaaa1111"].ahead, by["cao/aaaa1111"].dirty), (1, False))
        self.assertEqual((by["cao/bbbb2222"].ahead, by["cao/bbbb2222"].dirty), (0, True))
        self.assertIsNone(by["cao/cccc3333"].path)


class RoleTextTests(unittest.TestCase):
    """The behaviour lives in the role prompts; pin the rules that keep work from being lost."""

    def role(self, name):
        from caokit.render import load_role

        return load_role(name)

    def test_general_dispatches_with_use_worktree_and_keeps_the_terminal(self):
        g = self.role("general")
        for needle in (
            "use_worktree=true",
            "delete_terminal",
            "same engineer terminal",
            "cd <worktree path>",
            "git rev-parse HEAD",
        ):
            self.assertIn(needle, g)

    def test_engineer_commits_on_its_branch_and_records_base_and_commit(self):
        e = self.role("engineer")
        for needle in ("git add -A", "git commit", "Base commit", "**Commit**", "/.cao/worktrees/"):
            self.assertIn(needle, e)

    def test_inspector_runs_the_listed_cd_commands(self):
        self.assertIn("cd <path>/.cao/worktrees/<id>", self.role("inspector"))

    def test_safety_contract_allows_only_add_and_commit(self):
        from importlib import resources

        text = (
            resources.files("caokit") / "data/scaffold/company/contracts/SAFETY_CONTRACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("`git add -A` and `git commit`", text)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name).resolve() / "r")
        (self.repo / ".company").mkdir()
        (self.repo / ".company" / "caokit.toml").write_text(
            'schema = 1\n[project]\nname = "pj"\n', encoding="utf-8"
        )

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_policy_turns_worktrees_on_and_off(self):
        code, out, _ = self.run_cli("tasks", "policy", str(self.repo), "--worktrees", "on")
        self.assertEqual((code, load_overrides(self.repo).worktrees), (0, True))
        self.assertIn("caokit install", out)
        _, shown, _ = self.run_cli("tasks", "policy", str(self.repo))
        self.assertIn("worktrees: on", shown)
        self.run_cli("tasks", "policy", str(self.repo), "--worktrees", "off")
        self.assertFalse(load_overrides(self.repo).worktrees)

    def test_cannot_turn_on_in_a_repo_without_commits(self):
        bare = make_repo(Path(self.tmp.name).resolve() / "empty", commit=False)
        (bare / ".company").mkdir()
        (bare / ".company" / "caokit.toml").write_text('schema = 1\n[project]\nname = "e"\n')
        code, _, err = self.run_cli("tasks", "policy", str(bare), "--worktrees", "on")
        self.assertEqual((code, "no commits" in err, worktrees_enabled(bare)), (1, True, False))

    def test_worktrees_command_lists_branches(self):
        set_worktrees(self.repo, True)
        path = self.repo / ".cao" / "worktrees" / "dead0001"
        git(self.repo, "worktree", "add", "-q", "-b", "cao/dead0001", str(path))
        (path / "f.txt").write_text("x")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "w")
        code, out, _ = self.run_cli("worktrees", str(self.repo))
        self.assertEqual(code, 0)
        self.assertIn("worktrees: on", out)
        self.assertIn("cao/dead0001: 1 unmerged commit(s)", out)
        self.assertIn("git merge", out)

    def test_launch_refuses_when_worktrees_are_on_but_the_repo_is_unusable(self):
        set_worktrees(self.repo, True)
        git(self.repo, "update-ref", "-d", "refs/heads/main")  # no HEAD any more
        with (
            mock.patch("caokit.cli._run", return_value=0) as run,
            mock.patch("caokit.cli._session_of", return_value=(self.repo, "pj_general", "pj")),
        ):
            code, _, err = self.run_cli("launch", str(self.repo))
        self.assertEqual((code, "no commits" in err, run.called), (1, True, False))


if __name__ == "__main__":
    unittest.main()
