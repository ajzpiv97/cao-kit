"""Render profiles from caokit.toml and install them into CAO."""

import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ROLES, ProcessResult, Runner, default_runner, load_adapter
from .config import Config
from .render import profile_name, render_profile
from .roster import check_roster

# Profile names used by the pre-v1 bash kit. They stay in CAO's global store
# after migrating, so `install` offers to move them away.
LEGACY_NAMES = [
    "startup_captain",
    "claude_engineer",
    "claude_reviewer",
    "agy_researcher",
    "agy_reviewer",
    "codex_engineer",
    "codex_reviewer",
]


class InstallError(Exception):
    """Raised when profiles cannot even be attempted (for example an invalid roster)."""


@dataclass
class InstallResult:
    """Per-profile outcome of an install run."""

    installed: list[str] = field(default_factory=list)  # installed and verified
    failed: list[str] = field(default_factory=list)  # validate, install or verify failed
    backup_dir: Path | None = None  # set when stale copies were moved aside


def cao_home() -> Path:
    """Return CAO's home directory.

    Honors ``$CAO_HOME_DIR``, else ``~/.aws/cli-agent-orchestrator``. Because
    ``~`` follows ``$HOME``, tests can redirect everything with a temp HOME.
    """
    env = os.environ.get("CAO_HOME_DIR")
    return Path(env) if env else Path.home() / ".aws" / "cli-agent-orchestrator"


def render_all(cfg: Config) -> dict[str, str]:
    """Render every roster profile.

    Args:
        cfg: The company configuration.

    Returns:
        Mapping of concrete profile name to full profile text. Names are
        ``<role>-<tool>``, or ``<project>_<role>-<tool>`` for a project-scoped config.
    """
    out = {}
    for role in ROLES:
        b = cfg.roles[role]
        name = profile_name(role, b.tool, cfg.project)
        out[name] = render_profile(role, load_adapter(b.tool), b.model, cfg.project)
    return out


def find_legacy(home: Path) -> list[str]:
    """Return the legacy profile names that still have a copy under ``home``."""
    return [
        n
        for n in LEGACY_NAMES
        if (home / "agent-store" / (n + ".md")).exists()
        or (home / "agent-context" / (n + ".md")).exists()
    ]


def _backup(home: Path, names: list[str], backup: Path | None) -> Path | None:
    """Move installed copies of ``names`` into a backup folder under ``home``.

    Files are moved, never deleted, so a wrong guess is recoverable by hand.

    Args:
        home: CAO home directory.
        names: Profile names whose ``agent-context`` and ``agent-store`` copies to move.
        backup: Existing backup folder to reuse so one run produces one folder,
            or None to create a timestamped one on first move.

    Returns:
        The backup folder (None if nothing was moved and none was supplied).
    """
    for n in names:
        for sub in ("agent-context", "agent-store"):
            src = home / sub / (n + ".md")
            if src.exists():
                if backup is None:  # created lazily so a no-op leaves no empty folder
                    backup = home / ("caokit-backup-" + time.strftime("%Y%m%d%H%M%S"))
                (backup / sub).mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(backup / sub / (n + ".md")))
    return backup


def remove_legacy(home: Path, names: list[str]) -> Path | None:
    """Move legacy profile copies to a backup folder (nothing is deleted).

    Args:
        home: CAO home directory.
        names: Legacy profile names, as returned by :func:`find_legacy`.

    Returns:
        The backup folder, or None if there was nothing to move.
    """
    return _backup(home, names, None)


def _failed_output(r: ProcessResult) -> bool:
    """Return True if a ``cao`` call failed.

    CAO 2.5.x prints ``Error: ...`` but exits 0 when it refuses to overwrite a
    profile copy from an older CAO, so the exit code alone is not trustworthy.
    """
    return r.returncode != 0 or "Error:" in ((r.stdout or "") + (r.stderr or ""))


def install_profiles(
    cfg: Config,
    home: Path | None = None,
    runner: Runner = default_runner,
    replace_legacy: bool = False,
    out: Callable[[str], None] = print,
) -> InstallResult:
    """Render, validate, install and verify every profile in the roster.

    Each profile is verified by comparing CAO's stored copy byte for byte with
    what was rendered, because CAO stores profiles verbatim and a mismatch means
    a stale or altered copy.

    Args:
        cfg: The company configuration.
        home: CAO home directory (default: :func:`cao_home`).
        runner: Command runner used to call ``cao`` (injectable for tests).
        replace_legacy: On a refused install, move the stale copies to a
            backup folder and retry once.
        out: Sink for progress and failure messages.

    Returns:
        Which profiles were installed and which failed.

    Raises:
        InstallError: The roster violates a guardrail; nothing is attempted.
    """
    home = home or cao_home()
    roster = check_roster(cfg)
    if roster.errors:
        raise InstallError("roster is invalid:\n  " + "\n  ".join(roster.errors))
    profiles = render_all(cfg)
    res = InstallResult()
    with tempfile.TemporaryDirectory(prefix="caokit-") as stage:
        for name, text in profiles.items():
            # `cao install <file>` names the profile after the file stem, so the
            # staged filename must be exactly the concrete profile name.
            path = Path(stage) / (name + ".md")
            path.write_text(text, encoding="utf-8")
            v = runner(["cao", "profile", "validate", str(path)])
            if v.returncode != 0:  # validate exits 1 on schema errors; warnings exit 0
                out(f"validate FAILED for {name}:\n{(v.stdout or '') + (v.stderr or '')}")
                res.failed.append(name)
                continue
            r = runner(["cao", "install", str(path)])
            if _failed_output(r) and replace_legacy:
                res.backup_dir = _backup(home, [name], res.backup_dir)
                out(f"  moved stale copies of {name} to {res.backup_dir}; retrying")
                r = runner(["cao", "install", str(path)])
            if _failed_output(r):
                detail = ((r.stdout or "") + (r.stderr or "")).strip()
                out(f"install FAILED for {name}:\n{detail}")
                res.failed.append(name)
                continue
            stored = home / "agent-store" / (name + ".md")
            if not stored.is_file() or stored.read_bytes() != text.encode("utf-8"):
                out(
                    f"install verification FAILED for {name}: "
                    "stored copy differs from rendered profile"
                )
                res.failed.append(name)
                continue
            out(f"  installed {name} (verified byte for byte)")
            res.installed.append(name)
    return res
