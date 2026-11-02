"""`caokit reset`: back up CAO's state, reinstall the pinned CAO, then reinstall profiles.

Nothing is deleted. CAO's state folder is moved and the Antigravity MCP config is copied
into a timestamped backup folder first. Without ``--yes`` the command only prints the plan.
"""

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import Runner, default_runner
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
    servers = data.get("mcpServers") or {}
    drop = [
        k for k, v in servers.items() if k.startswith("cao") or "cao-mcp-server" in json.dumps(v)
    ]
    for k in drop:
        servers.pop(k)
    if drop:
        config.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return drop


def run_reset(
    version: str,
    cao_home: Path,
    agy_mcp: Path,
    backup_root: Path,
    runner: Runner = default_runner,
    install_profiles: Callable[[], None] = lambda: None,
) -> ResetResult:
    """Back up and reinstall CAO.

    Args:
        version: CAO version to pin.
        cao_home: CAO's state folder (moved, not deleted).
        agy_mcp: Antigravity MCP config path (copied, then edited in place).
        backup_root: Folder in which the timestamped backup folder is created.
        runner: Command runner (injectable for tests).
        install_profiles: Called last to reinstall the company's profiles.

    Returns:
        The backup folder and the steps taken.

    Raises:
        ResetError: A command failed or the installed version is not ``version``.
    """
    backup = backup_root / ("cao-reset-backup-" + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True)
    res = ResetResult(backup)

    def must(argv: list[str], what: str) -> str:
        r = runner(argv)
        if r.returncode != 0:
            raise ResetError(f"{what} failed: {(r.stderr or r.stdout).strip()} (backup: {backup})")
        return r.stdout or ""

    runner(["cao", "shutdown", "--all"])  # best effort: the server may already be down
    for pid in _cao_server_pids(runner):
        runner(["kill", pid])
    listed = runner(["tmux", "list-sessions", "-F", "#{session_name}"])
    for name in (listed.stdout or "").split():
        if name.startswith("cao-"):
            runner(["tmux", "kill-session", "-t", name])
    res.steps.append("stopped sessions and server")
    if cao_home.is_dir():
        shutil.move(str(cao_home), str(backup / "cli-agent-orchestrator"))
        res.steps.append(f"moved {cao_home} to {backup}")
    if agy_mcp.is_file():
        shutil.copy2(agy_mcp, backup / "gemini-mcp_config.json")
        removed = _drop_cao_servers(agy_mcp)
        res.steps.append("removed from MCP config: " + (", ".join(removed) or "nothing"))
    runner(["uv", "tool", "uninstall", CAO_PKG])  # fine if it was not installed
    must(["uv", "tool", "install", f"{CAO_PKG}=={version}"], "install of CAO")
    if version not in must(["cao", "--version"], "cao --version"):
        raise ResetError(f"cao is not {version} after install (backup: {backup})")
    must(["cao", "init"], "cao init")
    res.steps.append(f"installed CAO {version}")
    install_profiles()
    res.steps.append("installed company profiles")
    return res


def _cao_server_pids(runner: Runner) -> list[str]:
    """Return PIDs of real ``cao-server`` processes (argv0, or argv1 after a python), not greps."""
    r = runner(["ps", "-axo", "pid=,command="])
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
