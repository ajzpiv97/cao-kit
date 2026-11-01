"""Render concrete CAO profiles from a tool-agnostic role body and a tool adapter."""

import json
import re
from importlib import resources

from .adapters import Adapter

# Mirrors CAO 2.5.4 install_service._PROFILE_NAME_RE; dots are NOT allowed.
PROFILE_NAME_RE = r"^[A-Za-z0-9_-]{1,64}$"
# Role and tool IDs: lowercase alphanumerics only, so "-" in a name is an unambiguous separator.
_PART_RE = re.compile(r"^[a-z0-9]+$")


def profile_name(role: str, tool: str) -> str:
    """Build the concrete CAO profile name ``<role>-<tool>``.

    Args:
        role: Role ID, e.g. ``inspector``.
        tool: Tool ID, e.g. ``antigravity``.

    Returns:
        The profile name, e.g. ``inspector-antigravity``.

    Raises:
        ValueError: If a part is not lowercase alphanumeric or the result is not a
            valid CAO profile name.
    """
    for part in (role, tool):
        if not _PART_RE.match(part):
            raise ValueError(f"invalid name part {part!r}")
    name = f"{role}-{tool}"
    if not re.match(PROFILE_NAME_RE, name):
        raise ValueError(f"invalid profile name {name!r}")
    return name


def load_role(role: str) -> str:
    """Read the tool-agnostic role file shipped in the package.

    Args:
        role: Role ID (validated so it cannot traverse out of ``data/roles``).

    Returns:
        The full markdown text, frontmatter included.

    Raises:
        ValueError: If ``role`` is not a valid role ID.
    """
    if not _PART_RE.match(role):
        raise ValueError(f"invalid role {role!r}")
    return (resources.files("caokit") / "data" / "roles" / (role + ".md")).read_text(
        encoding="utf-8"
    )


def render_profile(role: str, adapter: Adapter, model: str | None) -> str:
    """Combine a role body with a tool adapter into a complete CAO profile.

    Output is deterministic, since CAO stores profiles byte for byte and the
    installer verifies the stored copy against this text.

    Args:
        role: Role ID.
        adapter: The tool adapter that fills the role.
        model: Model ID to pin, or None to omit ``model:`` (tool default applies).

    Returns:
        The profile text (frontmatter + body + optional "Tool notes" section).

    Raises:
        ValueError: If the role file has no frontmatter.
    """
    text = load_role(role)
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"role {role} has no frontmatter")
    fm_lines, body = m.group(1).split("\n"), m.group(2)
    out: list[str] = ["---", "name: " + profile_name(role, adapter.id)]
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
