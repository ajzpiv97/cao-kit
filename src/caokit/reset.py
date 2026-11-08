"""`caokit reset`: back up CAO's state, reinstall the pinned CAO, then reinstall profiles.

Nothing is deleted. CAO's state folder is moved and the Antigravity MCP config is copied
into a timestamped backup folder first. Without ``--yes`` the command only prints the plan.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ProcessResult, Runner, default_runner
from .doctor import CAO_PKG


class ResetError(Exception):
    """Raised when a reset step fails; the backup folder holds everything moved so far."""


@dataclass
class ResetResult:
    """What a reset did.

    Attributes:
        backup: Folder holding the moved CAO state and the copied MCP config.
        steps: One line per completed step.
    """

    backup: Path
    steps: list[str] = field(default_factory=list)


def plan(version: str, cao_home: Path) -> list[str]:
    """Return the steps a reset would perform, in order, for display."""
    return [
        "stop all CAO sessions, the cao-server process and cao-* tmux sessions",
        f"move {cao_home} into the backup folder",
        "remove CAO entries from the Antigravity MCP config (a copy is kept in the backup)",
        f"uv tool uninstall {CAO_PKG}, then uv tool install {CAO_PKG}=={version}",
        "cao init, then install the company profiles",
    ]


def _drop_cao_servers(config: Path) -> list[str]:
    """Remove CAO MCP servers from an Antigravity config file; return the names removed."""
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    drop = [
        k
        for k, v in servers.items()
        if k == "cao" or k.startswith("cao-") or "cao-mcp-server" in json.dumps(v)
    ]
    for k in drop:
        servers.pop(k)
    if drop:  # write beside the file, then swap, so a crash cannot leave half a config
        fd, tmp = tempfile.mkstemp(dir=config.parent, prefix=config.name + ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp, config)
    return drop


def _unsafe_home(cao_home: Path) -> str | None:
    """Return why ``cao_home`` must not be moved wholesale, or None if it is fine."""
    if cao_home.is_symlink():
        return f"{cao_home} is a symlink; moving it would move the link, not the data"
    real, home = cao_home.resolve(), Path.home().resolve()
    if real == home or real in home.parents or real.parent == real:
        return f"{cao_home} is your home folder or above it; refusing to move it"
    return None


def _new_backup(root: Path) -> Path:
    """Create a fresh timestamped backup folder, never reusing one from the same second."""
    stamp = "cao-reset-backup-" + time.strftime("%Y%m%d-%H%M%S")
    for n in range(100):
        path = root / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            path.mkdir(parents=True)
        except FileExistsError:
            continue
        return path
    raise ResetError(f"could not create a backup folder under {root}")


def run_reset(
    version: str,
    cao_home: Path,
    agy_mcp: Path,
    backup_root: Path,
    runner: Runner = default_runner,
    install_profiles: Callable[[], None] = lambda: None,
    slow_runner: Runner | None = None,
) -> ResetResult:
    """Back up and reinstall CAO.

    Args:
        version: CAO version to pin.
        cao_home: CAO's state folder (moved, not deleted).
        agy_mcp: Antigravity MCP config path (copied, then edited in place).
        backup_root: Folder in which the timestamped backup folder is created.
        runner: Command runner (injectable for tests).
        install_profiles: Called last to reinstall the company's profiles.
        slow_runner: Runner for the ``uv`` install (a cold download can exceed the default
            runner's timeout); defaults to ``runner``.

    Returns:
        The backup folder and the steps taken.

    Raises:
        ResetError: ``cao_home`` is unsafe to move, a command failed or could not run, or the
            installed version is not ``version``. Nothing is moved before the checks pass.
    """
    why = _unsafe_home(cao_home)
    if why:
        raise ResetError(why)
    backup = _new_backup(backup_root)
    res = ResetResult(backup)
    slow = slow_runner or runner
    try:
        _reset_steps(version, cao_home, agy_mcp, backup, res, runner, slow, install_profiles)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ResetError(f"{e} (backup: {backup})") from e
    return res


def _reset_steps(
    version: str,
    cao_home: Path,
    agy_mcp: Path,
    backup: Path,
    res: ResetResult,
    runner: Runner,
    slow: Runner,
    install_profiles: Callable[[], None],
) -> None:
    def must(run: Runner, argv: list[str], what: str) -> str:
        r = run(argv)
        if r.returncode != 0:
            raise ResetError(f"{what} failed: {(r.stderr or r.stdout).strip()} (backup: {backup})")
        return r.stdout or ""

    def best_effort(argv: list[str]) -> ProcessResult | None:
        try:
            return runner(argv)
        except (OSError, subprocess.TimeoutExpired):  # tool missing or hung: nothing to stop
            return None

    best_effort(["cao", "shutdown", "--all"])  # the server may already be down
    for pid in _cao_server_pids(runner):
        best_effort(["kill", pid])
    listed = best_effort(["tmux", "list-sessions", "-F", "#{session_name}"])
    for name in ((listed.stdout if listed else "") or "").split():
        if name.startswith("cao-"):
            best_effort(["tmux", "kill-session", "-t", name])
    res.steps.append("stopped sessions and server")
    if cao_home.is_dir():
        shutil.move(str(cao_home), str(backup / "cli-agent-orchestrator"))
        res.steps.append(f"moved {cao_home} to {backup}")
    if agy_mcp.is_file():
        shutil.copy2(agy_mcp, backup / "gemini-mcp_config.json")
        removed = _drop_cao_servers(agy_mcp)
        res.steps.append("removed from MCP config: " + (", ".join(removed) or "nothing"))
    best_effort(["uv", "tool", "uninstall", CAO_PKG])  # fine if it was not installed
    must(slow, ["uv", "tool", "install", f"{CAO_PKG}=={version}"], "install of CAO")
    if version not in re.findall(
        r"\d+(?:\.\d+)*", must(runner, ["cao", "--version"], "cao --version")
    ):
        raise ResetError(f"cao is not {version} after install (backup: {backup})")
    must(runner, ["cao", "init"], "cao init")
    res.steps.append(f"installed CAO {version}")
    try:
        install_profiles()
    except ResetError as e:
        raise ResetError(f"{e} (backup: {backup})") from e
    res.steps.append("installed company profiles")


def _cao_server_pids(runner: Runner) -> list[str]:
    """Return PIDs of real ``cao-server`` processes (argv0, or argv1 after a python), not greps."""
    try:
        r = runner(["ps", "-axo", "pid=,command="])
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids: list[str] = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        a1 = parts[1]
        a2 = parts[2] if len(parts) > 2 else ""
        is_server = a1.endswith("cao-server") or (
            "python" in a1.lower() and a2.endswith("cao-server")
        )
        if is_server:
            pids.append(parts[0])
    return pids
