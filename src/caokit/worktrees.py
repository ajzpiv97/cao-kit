"""Per-task git worktrees through CAO's ``use_worktree``.

CAO gives one engineer terminal its own ``git worktree`` at ``<repo>/.cao/worktrees/<terminal-id>``
on branch ``cao/<terminal-id>``, cut from the repo's HEAD. It removes the checkout when the
terminal is deleted and keeps the branch only if it holds commits. The agents do the dispatching
(see the role files); this module is what caokit itself knows about it: whether a repo can use
worktrees, and what CAO has left in one.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .adapters import Runner, default_runner

BRANCH_PREFIX = (
    "cao/"  # CAO's own branch naming; see cli_agent_orchestrator.services.worktree_service
)
WORKTREE_SUBDIR = ".cao/worktrees"


@dataclass
class TaskWorktree:
    """One branch CAO created for an engineer terminal.

    Attributes:
        branch: ``cao/<terminal-id>``.
        path: The checkout, or None once CAO has removed it (the branch outlives it).
        ahead: Commits on the branch that HEAD does not have (work not yet merged).
        dirty: True if the checkout has uncommitted changes, which CAO discards on teardown.
    """

    branch: str
    path: Path | None
    ahead: int
    dirty: bool


def _git(runner: Runner, repo: Path, *args: str) -> tuple[int, str]:
    try:
        r = runner(["git", "-C", str(repo), *args])
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, ((r.stdout or "") if r.returncode == 0 else (r.stderr or "")).strip()


def problems(repo: Path, runner: Runner = default_runner) -> tuple[list[str], list[str]]:
    """Check that ``repo`` can give each engineer a worktree.

    Args:
        repo: Project root.
        runner: Command runner (injectable for tests).

    Returns:
        ``(errors, warnings)``. Errors mean CAO's ``use_worktree`` would fail or lose work;
        warnings are things the human should know first.
    """
    errors: list[str] = []
    warnings: list[str] = []
    code, out = _git(runner, repo, "rev-parse", "--show-toplevel")
    if code != 0:
        return [f"{repo} is not a git repository, so there is nothing to make worktrees from"], []
    if Path(out).resolve() != Path(repo).resolve():
        errors.append(f"{repo} is inside the repository at {out}; run caokit on its root")
    if _git(runner, repo, "rev-parse", "--verify", "HEAD")[0] != 0:
        errors.append("the repository has no commits yet; a worktree is cut from HEAD")
    code, out = _git(runner, repo, "status", "--porcelain", "--untracked-files=no")
    if code == 0 and out:
        warnings.append(
            "uncommitted changes in the main checkout are not in a new worktree "
            "(it starts from the last commit)"
        )
    return errors, warnings


def list_task_worktrees(repo: Path, runner: Runner = default_runner) -> list[TaskWorktree]:
    """Return every ``cao/*`` branch in ``repo`` with its checkout and unmerged work.

    Args:
        repo: Project root.
        runner: Command runner (injectable for tests).

    Returns:
        One entry per branch, sorted by branch name. Empty if there are none or git fails.
    """
    code, out = _git(runner, repo, "worktree", "list", "--porcelain")
    paths: dict[str, Path] = {}
    if code == 0:
        path = None
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree ") :])
            elif line.startswith("branch refs/heads/") and path is not None:
                paths[line[len("branch refs/heads/") :]] = path
    code, out = _git(runner, repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/cao/")
    if code != 0:
        return []
    found = []
    for branch in sorted(out.split()):
        c, n = _git(runner, repo, "rev-list", "--count", f"HEAD..{branch}")
        path = paths.get(branch)
        dirty = False
        if path is not None:
            _, status = _git(runner, path, "status", "--porcelain")
            dirty = bool(status)
        found.append(TaskWorktree(branch, path, int(n) if c == 0 and n.isdigit() else 0, dirty))
    return found
