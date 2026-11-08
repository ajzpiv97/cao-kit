"""Build the ``cao`` argv for launching, inspecting, messaging and stopping a company session.

Every command is a pure function from arguments to an argv list, so tests can check exactly
what would run. The CLI layer is the only caller that executes them.
"""

import re
from pathlib import Path

SESSION_PREFIX = "cao-"  # CAO prepends this to the --session-name it is given


def session_name(project: Path, slug: str | None) -> str:
    """Pick the CAO session name for a project.

    Args:
        project: Project directory.
        slug: The project's namespace slug if it has one.

    Returns:
        ``slug`` if given, else the directory name reduced to lowercase letters, digits and
        ``-``, so two checkouts of different projects get different sessions.
    """
    if slug:
        return slug
    name = re.sub(r"[^a-z0-9]+", "-", Path(project).resolve().name.lower()).strip("-")
    return name or "company"


def session_id(name: str) -> str:
    """Return the ID CAO gives a session started with ``--session-name name``.

    CAO adds its prefix only when the name does not already start with it, so a project
    called ``cao-foo`` is the session ``cao-foo``, not ``cao-cao-foo``.
    """
    return name if name.startswith(SESSION_PREFIX) else SESSION_PREFIX + name


def build_launch_argv(
    project: Path,
    profile: str,
    session: str | None = None,
    prompt: str | None = None,
    headless: bool = False,
    auto_approve: bool = False,
) -> list[str]:
    """Build the argv that launches a CAO session for ``profile`` in ``project``.

    The working directory is always explicit and absolute: without it CAO uses
    the caller's cwd, which once led the General to start in the kit repo
    instead of the project.

    Args:
        project: Project directory the session must run in (relative paths are resolved).
        profile: Concrete CAO profile name, e.g. ``general-claude``.
        session: Optional CAO session name.
        prompt: Optional first message for the General.
        headless: Start detached instead of attaching to the terminal.
        auto_approve: Skip CAO's launch confirmation. Never grants extra tool access.

    Returns:
        The argv list, starting with ``cao launch``. Never includes ``--yolo``.

    Raises:
        ValueError: If ``project`` is not an existing directory.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    argv = ["cao", "launch", "--agents", profile, "--working-directory", str(root)]
    if session:
        argv += ["--session-name", session]
    if headless:
        argv.append("--headless")
    if auto_approve:
        argv.append("--auto-approve")
    if prompt:
        argv.insert(2, prompt)
    return argv


def build_status_argv(session: str) -> list[list[str]]:
    """Build the commands that show every session and one session's workers."""
    return [["cao", "session", "list"], ["cao", "session", "status", session, "--workers"]]


def build_send_argv(session: str, message: str, timeout: int = 600) -> list[str]:
    """Build the command that sends ``message`` to a session's General."""
    return ["cao", "session", "send", session, message, "--timeout", str(timeout)]


def build_stop_argv(session: str) -> list[str]:
    """Build the command that shuts one session down. It asks no confirmation."""
    return ["cao", "shutdown", "--session", session]
