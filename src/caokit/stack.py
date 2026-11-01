"""Suggest a project validation command from what is already in the repo.

Only suggests; the human confirms at task approval. Prefers forms that leave no
generated files behind (no .pyc, no pytest cache). Agents never install, so we
only suggest tooling that is already present.
"""

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .adapters import ProcessResult, Runner

PYTEST_CMD = "python3 -B -m pytest -p no:cacheprovider -q"
UNITTEST_CMD = "python3 -B -m unittest discover"


@dataclass
class Suggestion:
    """A proposed validation command; never authorised until the human confirms it."""

    command: str | None  # None when only a hint is possible (e.g. CI file found)
    reason: str  # what in the repo led to this suggestion
    note: str = ""  # caveat shown to the human, e.g. dependencies not installed


def _default_runner(argv: Sequence[str]) -> ProcessResult:
    """Run ``argv`` with captured text output and a short timeout."""
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=30)


def _read(p: Path) -> str:
    """Read a text file, returning "" if it is missing or unreadable."""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _uses_pytest(root: Path) -> bool:
    """Return True if the repo configures or depends on pytest."""
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists():
        return True
    for name in (
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "requirements.txt",
        "requirements-dev.txt",
    ):
        t = _read(root / name)
        if re.search(r"pytest", t):
            return True
    return False


def _has_py_tests(root: Path) -> bool:
    """Return True if ``test*.py`` files exist in tests/, test/ or the root."""
    for d in (root / "tests", root / "test", root):
        if d.is_dir() and any(d.glob("test*.py")):
            return True
    return False


def suggest_validation(root: Path, runner: Runner = _default_runner) -> Suggestion | None:
    """Suggest how to validate the project at ``root``, or None if nothing is detected.

    Order: package.json test script, pytest (only if importable), unittest files,
    Makefile ``test`` target, then a CI-workflow hint.

    Args:
        root: Project root directory.
        runner: Executes ``python3 -c "import pytest"``; injected so tests need no pytest.

    Returns:
        A :class:`Suggestion`, or None.
    """
    root = Path(root)
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            script = json.loads(_read(pkg)).get("scripts", {}).get("test", "")
        except (ValueError, AttributeError):
            script = ""
        # `npm init` writes a placeholder script that always fails; ignore it.
        if script and "no test specified" not in script:
            note = (
                ""
                if (root / "node_modules").is_dir()
                else "node_modules is missing; agents never install, "
                "install dependencies yourself first"
            )
            return Suggestion("npm test", "package.json defines a test script", note)
    if _has_py_tests(root) or _uses_pytest(root):
        # -B / no:cacheprovider keep the working tree clean (no .pyc or .pytest_cache).
        if _uses_pytest(root):
            # Agents never install anything, so only suggest pytest if it is already present.
            try:
                have = runner(["python3", "-c", "import pytest"]).returncode == 0
            except (OSError, subprocess.SubprocessError):
                have = False
            if have:
                return Suggestion(PYTEST_CMD, "pytest is configured and importable")
        if _has_py_tests(root):
            return Suggestion(UNITTEST_CMD, "test*.py files found")
    mk = _read(root / "Makefile")
    if re.search(r"(?m)^test\s*:", mk):
        return Suggestion("make test", "Makefile has a test target")
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        files = sorted(p.name for p in wf.iterdir() if p.suffix in (".yml", ".yaml"))
        if files:
            return Suggestion(None, f"CI workflow found ({files[0]}): copy its test step")
    return None
