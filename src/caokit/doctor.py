"""`caokit doctor`: what is installed, authenticated and consistent."""

import os
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import Runner, adapter_ids, default_runner, load_adapter
from .config import Config, ConfigError, default_path, load_config
from .roster import check_roster

# PyPI/uv name of CAO (not the `cao` binary name).
CAO_PKG = "cli-agent-orchestrator"

# Looks up an executable on PATH; returns its path or None (like shutil.which).
Which = Callable[[str], str | None]


@dataclass
class Check:
    """One line of the doctor report."""

    level: str  # "ok" | "warn" | "fail"
    text: str


@dataclass
class Report:
    """Ordered list of checks produced by :func:`run_doctor`."""

    checks: list[Check] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        """Append a check.

        Args:
            level: One of ``"ok"``, ``"warn"`` or ``"fail"``.
            text: Human-readable description of the finding.
        """
        self.checks.append(Check(level, text))

    @property
    def failed(self) -> bool:
        """Whether any check has level ``"fail"`` (drives the exit code)."""
        return any(c.level == "fail" for c in self.checks)


def _run(runner: Runner, argv: Sequence[str]) -> str | None:
    """Run a command and return its combined output, or None if it did not succeed.

    Args:
        runner: Command runner (injected so tests need no real CLIs).
        argv: Command and arguments.

    Returns:
        Stripped stdout+stderr on exit code 0; None on a non-zero exit or when
        the command could not be run at all.
    """
    try:
        r = runner(argv)
    except Exception:  # noqa: BLE001 - missing binary, timeout, etc. all mean "unavailable"
        return None
    return ((r.stdout or "") + (r.stderr or "")).strip() if r.returncode == 0 else None


def _cao_installs(runner: Runner, which: Which) -> list[str]:
    """Find CAO installs other than the uv tool (pipx, or pip in a PATH python).

    Args:
        runner: Command runner.
        which: PATH lookup function.

    Returns:
        Labels of the extra installs; empty when there are none.
    """
    extra: list[str] = []
    if which("pipx"):
        out = _run(runner, ["pipx", "list", "--short"])
        if out and re.search(rf"(?m)^{CAO_PKG} ", out):
            extra.append("pipx")
    seen: set[str] = set()
    for name in ("python3", "python3.9", "python3.10", "python3.11", "python3.12", "python3.13"):
        p = which(name)
        if not p:
            continue
        # Resolve symlinks so python3 and python3.12 are not probed twice.
        real = os.path.realpath(p)
        if real in seen:
            continue
        seen.add(real)
        code = f"import importlib.metadata as m; print(m.version('{CAO_PKG}'))"
        if _run(runner, [real, "-c", code]):
            extra.append(f"pip in {real}")
    return extra


def _check_cao(rep: Report, expected: str, runner: Runner, which: Which) -> None:
    """Add checks for the cao binary: presence, exact version, uv origin, single install.

    Args:
        rep: Report to append to.
        expected: CAO version this kit is validated against.
        runner: Command runner.
        which: PATH lookup function.
    """
    if not which("cao"):
        rep.add(
            "fail",
            f"cao not found on PATH (uv tool install 'cli-agent-orchestrator=={expected}')",
        )
        return
    v = _run(runner, ["cao", "--version"]) or ""
    m = re.search(r"(\d+\.\d+\.\d+)", v)
    if not m:
        rep.add("fail", "cannot read `cao --version`")
    elif m.group(1) != expected:
        # A different version is a failure, not a warning: the kit is only validated on one.
        rep.add(
            "fail",
            f"cao {m.group(1)} found, expected {expected} "
            "(change only with `uv tool install --force 'cli-agent-orchestrator==X'`)",
        )
    else:
        rep.add("ok", f"cao {m.group(1)}")
    if which("uv"):
        out = _run(runner, ["uv", "tool", "list"]) or ""
        if re.search(rf"(?m)^{CAO_PKG} ", out):
            rep.add("ok", "cao installed as a uv tool")
        else:
            rep.add("warn", "cao is not a uv tool install")
    extra = _cao_installs(runner, which)
    if extra:
        joined = ", ".join(extra)
        rep.add("fail", f"additional cao installs found: {joined} (keep exactly one, the uv tool)")
    else:
        rep.add("ok", "single cao install")


def _check_tools(rep: Report, used: set[str], runner: Runner, which: Which) -> None:
    """Add checks for every adapter's CLI: binary, version and auth.

    A missing or unauthenticated tool is a failure only if the roster uses it.

    Args:
        rep: Report to append to.
        used: Tool IDs referenced by the configured roster.
        runner: Command runner.
        which: PATH lookup function.
    """
    ready = 0
    for tid in adapter_ids():
        a = load_adapter(tid)
        if a.status != "active":
            rep.add("ok", f"{tid}: parked (not selectable)")
            continue
        # Not having a tool you do not use is fine; not having one you rely on is not.
        lvl_missing = "fail" if tid in used else "warn"
        if not which(a.binary):
            rep.add(lvl_missing, f"{tid}: `{a.binary}` not found on PATH")
            continue
        ver = _run(runner, a.version_cmd)
        if ver is None:
            rep.add(lvl_missing, f"{tid}: `{' '.join(a.version_cmd)}` failed")
            continue
        first_line = ver.splitlines()[0] if ver else "installed"
        line = f"{tid}: {first_line} ({a.enforcement} enforcement)"
        if a.auth_cmd:
            if _run(runner, a.auth_cmd) is None:
                rep.add(
                    lvl_missing,
                    f"{tid}: installed but auth check `{' '.join(a.auth_cmd)}` failed (logged in?)",
                )
                continue
        else:
            line += "; auth not checked"  # e.g. claude has no cheap non-interactive check
        rep.add("ok", line)
        ready += 1
    if ready < 2:
        rep.add(
            "warn", f"only {ready} provider(s) ready: independent cross-provider review needs two"
        )


def _check_roster(rep: Report, cfg: Config, path: Path) -> None:
    """Add the roster guardrail results for a loaded config.

    Args:
        rep: Report to append to.
        cfg: Loaded configuration.
        path: Where the config was loaded from (shown on success).
    """
    r = check_roster(cfg)
    for err in r.errors:
        rep.add("fail", f"roster: {err}")
    for warning in r.warnings:
        rep.add("warn", f"roster: {warning}")
    if not r.errors:
        rep.add("ok", f"roster valid ({path})")


def run_doctor(
    config_path: Path | None = None,
    runner: Runner = default_runner,
    which: Which = shutil.which,
) -> Report:
    """Inspect the machine: CAO, provider CLIs, supporting tools and the roster.

    Args:
        config_path: Path to ``caokit.toml``; the default location if None.
        runner: Command runner (injectable for tests).
        which: PATH lookup (injectable for tests).

    Returns:
        A :class:`Report`; ``report.failed`` is true if anything must be fixed.
    """
    rep = Report()
    cfg: Config | None = None
    path = Path(config_path) if config_path else default_path()
    try:
        cfg = load_config(path)
    except ConfigError as e:
        # A missing config is expected before `company create`, so only warn.
        rep.add("warn", str(e))
    used = {b.tool for b in cfg.roles.values()} if cfg else set()
    expected = cfg.expected_cao_version if cfg else "2.5.4"

    _check_cao(rep, expected, runner, which)
    for binary in ("tmux", "git", "uv"):
        found = which(binary)
        # uv is only needed to install/upgrade; tmux and git are required to run at all.
        level = "ok" if found else ("warn" if binary == "uv" else "fail")
        rep.add(level, f"{binary} {'found' if found else 'not found'}")
    _check_tools(rep, used, runner, which)
    if cfg:
        _check_roster(rep, cfg, path)
    return rep


def format_report(rep: Report) -> str:
    """Render a report as one tagged line per check.

    Args:
        rep: Report to render.

    Returns:
        Text such as ``[ ok ] cao 2.5.4`` joined by newlines.
    """
    tag = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}
    return "\n".join(f"{tag[c.level]} {c.text}" for c in rep.checks)
