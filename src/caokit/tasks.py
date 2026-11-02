"""Read-only view of ``.company/tasks`` plus archiving of finished tasks."""

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL = frozenset({"ACCEPTED", "CANCELLED", "FAILED"})
_ID = re.compile(r"TASK-\d{4}")
_STATE = re.compile(r"^- \*\*State:\*\*\s*([A-Z_]+)", re.M)
_DEPS = re.compile(r"^- \*\*Depends on:\*\*(.*)$", re.M)
_TITLE = re.compile(r"^# (TASK-\d{4}):\s*(.*)$", re.M)


class TaskError(Exception):
    """Raised for an unreadable task folder or a dependency loop."""


@dataclass(frozen=True)
class Task:
    """One task file, reduced to what listing and archiving need."""

    id: str
    title: str
    state: str
    depends: tuple[str, ...]
    path: Path
    archived: bool = False
    blocked_by: tuple[str, ...] = field(default=(), compare=False)


def tasks_dir(repo: Path) -> Path:
    """Return ``<repo>/.company/tasks``, raising if the repo has none."""
    d = repo / ".company" / "tasks"
    if not d.is_dir():
        raise TaskError(f"no .company/tasks folder in {repo}")
    return d


def parse_task(path: Path, archived: bool = False) -> Task | None:
    """Parse a task file, or return None if it has no ``# TASK-NNNN`` heading."""
    text = path.read_text(encoding="utf-8", errors="replace")
    title = _TITLE.search(text)
    if not title:
        return None
    state = _STATE.search(text)
    deps = _DEPS.search(text)
    return Task(
        id=title.group(1),
        title=title.group(2).strip(),
        state=state.group(1) if state else "UNKNOWN",
        depends=tuple(dict.fromkeys(_ID.findall(deps.group(1)))) if deps else (),
        path=path,
        archived=archived,
    )


def load_tasks(repo: Path) -> list[Task]:
    """Load active tasks and archived ones, sorted by id."""
    root = tasks_dir(repo)
    found = [t for p in root.glob("TASK-*.md") if (t := parse_task(p))]
    arch = root / "archive"
    if arch.is_dir():
        found += [t for p in arch.glob("TASK-*.md") if (t := parse_task(p, archived=True))]
    return sorted(found, key=lambda t: t.id)


def find_cycle(tasks: list[Task]) -> list[str] | None:
    """Return one dependency loop as ``[A, B, A]``, or None if there is none."""
    graph = {t.id: t.depends for t in tasks}
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> list[str] | None:
        if node in path:
            return [*path[path.index(node) :], node]
        if node in done or node not in graph:
            return None
        for nxt in graph[node]:
            if (hit := visit(nxt, [*path, node])) is not None:
                return hit
        done.add(node)
        return None

    for tid in sorted(graph):
        if (hit := visit(tid, [])) is not None:
            return hit
    return None


def with_blockers(tasks: list[Task]) -> list[Task]:
    """Fill ``blocked_by``: dependencies that are missing or not ACCEPTED.

    Raises:
        TaskError: if the dependencies form a loop.
    """
    if (loop := find_cycle(tasks)) is not None:
        raise TaskError("dependency loop: " + " -> ".join(loop))
    state = {t.id: t.state for t in tasks}
    return [
        Task(
            t.id, t.title, t.state, t.depends, t.path, t.archived,
            tuple(d for d in t.depends if state.get(d) != "ACCEPTED"),
        )
        for t in tasks
    ]  # fmt: skip


def format_tasks(tasks: list[Task], show_all: bool = False) -> str:
    """Render a table of open tasks (or every task with ``show_all``)."""
    rows = [t for t in tasks if show_all or t.state not in TERMINAL]
    if not rows:
        return "No open tasks."
    lines = []
    for t in rows:
        wait = (
            f"  BLOCKED by {', '.join(t.blocked_by)}"
            if t.blocked_by and t.state not in TERMINAL
            else ""
        )
        tag = " [archived]" if t.archived else ""
        lines.append(f"{t.id}  {t.state:<19}{t.title}{wait}{tag}")
    return "\n".join(lines)


def archive_finished(repo: Path, delete: bool = False) -> list[Task]:
    """Move finished tasks into ``tasks/archive/`` (or delete them).

    A task is finished when its state is ACCEPTED, CANCELLED or FAILED. Running it
    twice changes nothing the second time.

    Returns:
        The tasks that were moved or deleted.
    """
    root = tasks_dir(repo)
    moved = []
    for p in sorted(root.glob("TASK-*.md")):
        task = parse_task(p)
        if task is None or task.state not in TERMINAL:
            continue
        if delete:
            p.unlink()
        else:
            (root / "archive").mkdir(exist_ok=True)
            dest = root / "archive" / p.name
            shutil.move(str(p), dest)
            os.utime(dest)  # a move keeps the old mtime; the archive date is when it was archived
        moved.append(task)
    return moved


def prune_archive(
    repo: Path, days: int, apply: bool = False, now: float | None = None
) -> list[Path]:
    """List archived task files older than ``days``, deleting them when ``apply`` is true.

    Age is measured from when the file was archived (its modification time).

    Args:
        repo: Project root.
        days: Keep files archived within this many days.
        apply: Delete the old files instead of only listing them.
        now: Current time as a Unix timestamp (injectable for tests).

    Returns:
        The old archived files, oldest first. Empty when there is no archive folder.
    """
    arch = tasks_dir(repo) / "archive"
    if not arch.is_dir():
        return []
    cutoff = (time.time() if now is None else now) - days * 86400
    old = sorted(
        (p for p in arch.glob("TASK-*.md") if p.stat().st_mtime < cutoff),
        key=lambda p: p.stat().st_mtime,
    )
    if apply:
        for p in old:
            p.unlink()
    return old
