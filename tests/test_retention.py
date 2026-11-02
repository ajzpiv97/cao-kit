import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from caokit import cli, schedule
from caokit.config import ConfigError
from caokit.project import dump_overrides, load_overrides, parse_overrides, set_keep_archived_days
from caokit.tasks import archive_finished, prune_archive


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def task(n, state):
    return f"# TASK-{n:04d}: t{n}\n\n- **State:** {state}\n"


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.tasks = self.repo / ".company" / "tasks"
        self.tasks.mkdir(parents=True)
        (self.repo / ".company" / "caokit.toml").write_text('schema = 1\n[project]\nname = "pj"\n')

    def archived(self, n, age_days):
        (self.tasks / f"TASK-{n:04d}-x.md").write_text(task(n, "ACCEPTED"))
        archive_finished(self.repo)
        p = self.tasks / "archive" / f"TASK-{n:04d}-x.md"
        old = time.time() - age_days * 86400
        os.utime(p, (old, old))
        return p

    def test_archive_stamps_the_archive_date_not_the_old_mtime(self):
        p = self.tasks / "TASK-0001-x.md"
        p.write_text(task(1, "ACCEPTED"))
        os.utime(p, (1_000_000_000, 1_000_000_000))
        archive_finished(self.repo)
        self.assertGreater((self.tasks / "archive" / p.name).stat().st_mtime, time.time() - 60)

    def test_prune_lists_old_files_and_only_deletes_with_apply(self):
        old, fresh = self.archived(1, 40), self.archived(2, 3)
        self.assertEqual(prune_archive(self.repo, 30), [old])
        self.assertTrue(old.exists())
        self.assertEqual(prune_archive(self.repo, 30, apply=True), [old])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(prune_archive(self.repo, 30, apply=True), [])

    def test_prune_never_touches_active_tasks(self):
        active = self.tasks / "TASK-0009-live.md"
        active.write_text(task(9, "IN_PROGRESS"))
        old = time.time() - 999 * 86400
        os.utime(active, (old, old))
        self.archived(1, 40)
        prune_archive(self.repo, 1, apply=True)
        self.assertTrue(active.exists())

    def test_policy_round_trips_and_rejects_bad_values(self):
        set_keep_archived_days(self.repo, 45)
        self.assertEqual(load_overrides(self.repo).keep_archived_days, 45)
        self.assertEqual(
            parse_overrides({"schema": 1, "project": {"name": "a"}}).keep_archived_days, None
        )
        for bad in (0, -3):
            with self.assertRaises(ConfigError):
                set_keep_archived_days(self.repo, bad)
        for bad in ("7", 1.5, True):
            with self.assertRaises(ConfigError):
                parse_overrides(
                    {"schema": 1, "project": {"name": "a"}, "tasks": {"keep_archived_days": bad}}
                )
        ov = load_overrides(self.repo)
        self.assertEqual(parse_overrides(__import__("tomllib").loads(dump_overrides(ov))), ov)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cli_prune_uses_the_project_policy_and_needs_yes(self):
        old = self.archived(1, 40)
        code, _, err = self.run_cli("tasks", "prune", str(self.repo))
        self.assertEqual((code, "no retention" in err), (1, True))
        self.run_cli("tasks", "policy", str(self.repo), "--keep-archived-days", "30")
        code, out, _ = self.run_cli("tasks", "prune", str(self.repo))
        self.assertIn("Would delete 1", out)
        self.assertTrue(old.exists())
        self.run_cli("tasks", "prune", str(self.repo), "--yes")
        self.assertFalse(old.exists())


class ScheduleTests(unittest.TestCase):
    def fake(self, crontab):
        state = {"tab": crontab}

        def runner(argv):
            if argv[:2] == ["crontab", "-l"]:
                return R(0, state["tab"]) if state["tab"] is not None else R(1, err="no crontab")
            state["tab"] = Path(argv[1]).read_text()
            return R(0)

        return runner, state

    def test_line_is_absolute_quoted_and_marked(self):
        line = schedule.cron_line("/opt/bin/caokit", Path("/p/my proj"), "04:05")
        self.assertTrue(line.startswith("5 4 * * * "))
        self.assertIn("'/p/my proj'", line)
        self.assertTrue(line.endswith("# caokit-tasks:/p/my proj"))
        with self.assertRaises(ValueError):
            schedule.cron_line("/x", Path("/p"), "25:00")

    def test_install_replaces_only_its_own_entry(self):
        repo = Path("/p/a")
        runner, state = self.fake("0 1 * * * backup\n")
        schedule.install(schedule.cron_line("/x/caokit", repo), repo, runner)
        schedule.install(schedule.cron_line("/x/caokit", repo, "05:00"), repo, runner)
        lines = state["tab"].splitlines()
        self.assertEqual(lines[0], "0 1 * * * backup")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("0 5 "))

    def test_install_with_no_crontab_and_remove(self):
        repo = Path("/p/a")
        runner, state = self.fake(None)
        schedule.install(schedule.cron_line("/x/caokit", repo), repo, runner)
        self.assertEqual(len(state["tab"].splitlines()), 1)
        self.assertTrue(schedule.remove(repo, runner))
        self.assertEqual(state["tab"], "")
        self.assertFalse(schedule.remove(repo, runner))

    def test_write_failure_is_reported(self):
        def runner(argv):
            return R(0, "") if argv[1] == "-l" else R(1, err="denied")

        with self.assertRaises(schedule.ScheduleError):
            schedule.install("x", Path("/p"), runner)


if __name__ == "__main__":
    unittest.main()
