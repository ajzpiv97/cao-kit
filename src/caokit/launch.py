"""Build ``cao launch`` argv. Always passes an explicit absolute --working-directory."""

from pathlib import Path


def build_launch_argv(project: Path, profile: str, session: str | None = None) -> list[str]:
    """Build the argv that launches a CAO session for ``profile`` in ``project``.

    The working directory is always explicit and absolute: without it CAO uses
    the caller's cwd, which once led the General to start in the kit repo
    instead of the project.

    Args:
        project: Project directory the session must run in (relative paths are resolved).
        profile: Concrete CAO profile name, e.g. ``general-claude``.
        session: Optional CAO session name.

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
    return argv
