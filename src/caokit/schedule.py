"""Install a daily cron job that archives finished tasks and prunes old archived ones.

cron is the only scheduler used. The entry carries a marker comment holding the project path,
so installing twice replaces the entry and removing it touches nothing else in the crontab.
"""

import shlex
import tempfile
from pathlib import Path

from .adapters import Runner, default_runner

MARKER = "# caokit-tasks:"
DEFAULT_TIME = "03:17"


class ScheduleError(Exception):
    """Raised when the crontab cannot be read or written."""


def cron_line(caokit: str, repo: Path, at: str = DEFAULT_TIME) -> str:
    """Build the crontab entry for one project.

    Args:
        caokit: Absolute path of the ``caokit`` executable (cron has a minimal PATH).
        repo: Project root.
        at: Time of day, ``HH:MM`` (24 hour).

    Returns:
        One crontab line ending in the project marker.

    Raises:
        ValueError: ``at`` is not a valid ``HH:MM`` time.
    """
    hh, _, mm = at.partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        raise ValueError(f"invalid time {at!r}: use HH:MM, 24 hour")
    exe, root = shlex.quote(caokit), shlex.quote(str(repo))
    cmd = f"{exe} tasks archive {root} && {exe} tasks prune {root} --yes"
    return f"{int(mm)} {int(hh)} * * * {cmd} {MARKER}{repo}"


def _read(runner: Runner) -> list[str]:
    r = runner(["crontab", "-l"])
    if r.returncode != 0:  # no crontab yet is reported as a non-zero exit
        return []
    return (r.stdout or "").splitlines()


def _write(runner: Runner, lines: list[str]) -> None:
    text = "\n".join(lines) + "\n" if lines else ""
    with tempfile.NamedTemporaryFile("w", suffix=".cron", delete=False) as f:
        f.write(text)
    try:
        r = runner(["crontab", f.name])  # the runner has no stdin, so install from a file
    finally:
        Path(f.name).unlink(missing_ok=True)
    if r.returncode != 0:
        raise ScheduleError("could not write the crontab: " + (r.stderr or "").strip())


def _without(lines: list[str], repo: Path) -> list[str]:
    tag = MARKER + str(repo)
    return [ln for ln in lines if not ln.endswith(tag)]


def install(line: str, repo: Path, runner: Runner = default_runner) -> None:
    """Add (or replace) the project's entry, leaving every other crontab line alone."""
    _write(runner, [*_without(_read(runner), repo), line])


def remove(repo: Path, runner: Runner = default_runner) -> bool:
    """Remove the project's entry.

    Returns:
        True if an entry was removed, False if there was none.
    """
    before = _read(runner)
    after = _without(before, repo)
    if after == before:
        return False
    _write(runner, after)
    return True
