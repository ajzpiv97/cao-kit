"""Render concrete CAO profiles from a tool-agnostic role body and a tool adapter."""

import json
import re
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

from .adapters import ROLES, Adapter

# Mirrors CAO 2.5.4 install_service._PROFILE_NAME_RE; dots are NOT allowed.
PROFILE_NAME_RE = r"^[A-Za-z0-9_-]{1,64}$"
# Role and tool IDs: lowercase alphanumerics only, so "-" in a name is an unambiguous separator.
_PART_RE = re.compile(r"^[a-z0-9]+$")


# Project slug: lowercase alphanumerics and "-", at most 24 chars. It must not contain "_" because
# "_" separates the project from "<role>-<tool>", which keeps the full name unambiguous, and the
# cap keeps "<project>_<role>-<tool>" well under CAO's 64-character limit.
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")


def validate_project_name(project: str) -> str:
    """Check a project slug.

    Args:
        project: Candidate slug, e.g. ``myapp``.

    Returns:
        The slug unchanged.

    Raises:
        ValueError: If it is not 1-24 chars of lowercase letters, digits and ``-``.
    """
    if not PROJECT_RE.match(project):
        raise ValueError(
            f"invalid project name {project!r}: use 1-24 lowercase letters, digits or '-' "
            "(start with a letter or digit)"
        )
    return project


def profile_name(role: str, tool: str, project: str | None = None) -> str:
    """Build the concrete CAO profile name.

    Shared profiles are ``<role>-<tool>``; project-scoped ones are
    ``<project>_<role>-<tool>`` so projects never overwrite each other in CAO's
    machine-global profile store.

    Args:
        role: Role ID, e.g. ``inspector``.
        tool: Tool ID, e.g. ``antigravity``.
        project: Project slug, or None for the shared (machine-wide) profile.

    Returns:
        The profile name, e.g. ``inspector-antigravity`` or ``myapp_inspector-antigravity``.

    Raises:
        ValueError: If a part is invalid or the result is not a valid CAO profile name.
    """
    for part in (role, tool):
        if not _PART_RE.match(part):
            raise ValueError(f"invalid name part {part!r}")
    name = f"{role}-{tool}"
    if project is not None:
        name = f"{validate_project_name(project)}_{name}"
    if not re.match(PROFILE_NAME_RE, name):
        raise ValueError(f"invalid profile name {name!r}")
    return name


def role_file(role: str, role_dirs: Sequence[Path]) -> Path | None:
    """Find a custom role's file: the first ``<dir>/<role>.md`` that exists, or None."""
    if not _PART_RE.match(role):
        return None
    return next((d / (role + ".md") for d in role_dirs if (d / (role + ".md")).is_file()), None)


def load_role(role: str, role_dirs: Sequence[Path] = ()) -> str:
    """Read a tool-agnostic role file.

    A built-in role always comes from the package, so a file in ``role_dirs`` can never
    replace the General or weaken another built-in. A custom role comes from ``role_dirs``.

    Args:
        role: Role ID (validated so it cannot traverse out of a roles folder).
        role_dirs: Folders searched, in order, for a custom role's ``<role>.md``.

    Returns:
        The full markdown text, frontmatter included.

    Raises:
        ValueError: If ``role`` is not a valid role ID or a custom role has no file.
    """
    if not _PART_RE.match(role):
        raise ValueError(f"invalid role {role!r}")
    if role in ROLES:
        return (resources.files("caokit") / "data" / "roles" / (role + ".md")).read_text(
            encoding="utf-8"
        )
    path = role_file(role, role_dirs)
    if path is None:
        where = ", ".join(str(d) for d in role_dirs) or "no roles folder configured"
        raise ValueError(f"no role file {role}.md (looked in: {where})")
    return path.read_text(encoding="utf-8")


def _split(text: str) -> tuple[list[str], str] | None:
    """Split a role file into frontmatter lines and body; None without frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    return (m.group(1).split("\n"), m.group(2)) if m else None


def role_description(text: str) -> str:
    """Return the ``description:`` of a role file, unquoted; empty if it has none."""
    for line in (_split(text) or ([], ""))[0]:
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def check_role_text(text: str) -> tuple[list[str], list[str]]:
    """Check that a custom role file can become a safe, usable CAO profile.

    Args:
        text: The role file's text.

    Returns:
        ``(errors, warnings)``. Errors: no frontmatter, no ``role:`` line (the provider and
        model are inserted after it), no description (the General picks a custom role by its
        description), a ``name:`` line (caokit sets the name), or an allow-everything tool
        list. Warning: no ``@cao-mcp-server``, so the role cannot report back.
    """
    parts = _split(text)
    if parts is None:
        return ["it has no frontmatter (a block between two `---` lines at the top)"], []
    fm = parts[0]
    errors, warnings = [], []
    if not any(line.startswith("role:") for line in fm):
        errors.append("its frontmatter has no `role:` line")
    if not role_description(text):
        errors.append("its frontmatter has no `description:`; the General chooses by it")
    if any(line.startswith("name:") for line in fm):
        errors.append("remove its `name:` line; caokit sets the profile name")
    if any(re.fullmatch(r"\s*-\s*[\"']?\*[\"']?\s*", line) for line in fm):
        errors.append('allowedTools contains "*", which bypasses every restriction')
    if "@cao-mcp-server" not in "\n".join(fm):
        warnings.append("allowedTools has no `@cao-mcp-server`, so it cannot report back")
    return errors, warnings


def render_profile(
    role: str,
    adapter: Adapter,
    model: str | None,
    project: str | None = None,
    role_dirs: Sequence[Path] = (),
) -> str:
    """Combine a role body with a tool adapter into a complete CAO profile.

    Output is deterministic, since CAO stores profiles byte for byte and the
    installer verifies the stored copy against this text.

    Args:
        role: Role ID.
        adapter: The tool adapter that fills the role.
        model: Model ID to pin, or None to omit ``model:`` (tool default applies).
        project: Project slug to namespace the profile name with, or None for shared.
        role_dirs: Folders searched for a custom role's file.

    Returns:
        The profile text (frontmatter + body + optional "Tool notes" section).

    Raises:
        ValueError: If the role file is missing or has no frontmatter.
    """
    parts = _split(load_role(role, role_dirs))
    if parts is None:
        raise ValueError(f"role {role} has no frontmatter")
    fm_lines, body = parts
    out: list[str] = ["---", "name: " + profile_name(role, adapter.id, project)]
    for line in fm_lines:
        out.append(line)
        # Provider-specific fields are injected right after the CAO ``role:`` line.
        if line.startswith("role:"):
            out.append("provider: " + adapter.cao_provider)
            if model:
                out.append("model: " + json.dumps(model))  # quoted: IDs may contain dots/colons
            for k, v in adapter.frontmatter.items():
                out.append(f"{k}: {v}")
    out.append("---")
    result = "\n".join(out) + "\n" + body
    if adapter.notes:
        # Caveats (e.g. advisory-only limits) go at the end so the role body stays tool-agnostic.
        result = result.rstrip("\n") + "\n\n## Tool notes\n\n" + adapter.notes + "\n"
    return result
