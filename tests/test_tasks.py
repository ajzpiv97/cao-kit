import tempfile
import unittest
from pathlib import Path

from caokit.cli import main
from caokit.tasks import TaskError, archive_finished, find_cycle, load_tasks, with_blockers


def _task(root: Path, n: int, state: str, deps: str = "none") -> None:
    (root / f"TASK-{n:04d}-x.md").write_text(
        f"# TASK-{n:04d}: t{n}\n\n- **State:** {state}\n- **Depends on:** {deps}\n"
    )


class TasksTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.root = self.repo / ".company" / "tasks"
        self.root.mkdir(parents=True)

    def test_blocked_until_dependency_accepted(self):
        _task(self.root, 1, "REVIEW_READY")
        _task(self.root, 2, "APPROVED", "TASK-0001")
        t = {x.id: x for x in with_blockers(load_tasks(self.repo))}
        self.assertEqual(t["TASK-0002"].blocked_by, ("TASK-0001",))
        _task(self.root, 1, "ACCEPTED")
        t = {x.id: x for x in with_blockers(load_tasks(self.repo))}
        self.assertEqual(t["TASK-0002"].blocked_by, ())

    def test_loop_detected(self):
        _task(self.root, 1, "APPROVED", "TASK-0002")
        _task(self.root, 2, "APPROVED", "TASK-0001")
        self.assertEqual(find_cycle(load_tasks(self.repo)), ["TASK-0001", "TASK-0002", "TASK-0001"])
        with self.assertRaises(TaskError):
            with_blockers(load_tasks(self.repo))
        self.assertEqual(main(["tasks", "list", str(self.repo)]), 1)

    def test_archive_moves_only_finished_and_is_idempotent(self):
        _task(self.root, 1, "ACCEPTED")
        _task(self.root, 2, "IN_PROGRESS", "TASK-0001")
        self.assertEqual([t.id for t in archive_finished(self.repo)], ["TASK-0001"])
        self.assertEqual(archive_finished(self.repo), [])
        self.assertTrue((self.root / "archive" / "TASK-0001-x.md").exists())
        self.assertTrue((self.root / "TASK-0002-x.md").exists())
        # an archived ACCEPTED dependency still counts as satisfied
        t = {x.id: x for x in with_blockers(load_tasks(self.repo))}
        self.assertEqual(t["TASK-0002"].blocked_by, ())

    def test_delete_and_template_ignored(self):
        _task(self.root, 1, "CANCELLED")
        (self.root / "TASK_TEMPLATE.md").write_text("# <TASK-ID>: <Title>\n")
        self.assertEqual(len(archive_finished(self.repo, delete=True)), 1)
        self.assertEqual(load_tasks(self.repo), [])

    def test_missing_folder_is_an_error(self):
        self.assertEqual(main(["tasks", "list", str(self.repo / "nope")]), 1)


if __name__ == "__main__":
    unittest.main()
