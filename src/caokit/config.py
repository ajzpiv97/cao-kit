"""caokit.toml: load, validate and dump the company configuration."""

import json
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ROLES
from .render import validate_project_name

SCHEMA = 1
CAO_VERSION = "2.5.4"  # the only CAO version this kit is validated against


class ConfigError(Exception):
    """Raised for any problem reading or validating ``caokit.toml``."""


@dataclass
class Binding:
    """The tool (and optionally model) assigned to one role.

    Attributes:
        tool: Adapter ID, e.g. ``claude``.
        model: Model ID, or None to use the tool's own default.
    """

    tool: str
    model: str | None = None  # None = use the tool's own default model


@dataclass
class Config:
    """The whole company: one binding per role plus policy switches.

    Attributes:
        roles: Binding for each of the four roles.
        allow_soft_engineer: Lets a soft-enforcement tool be the engineer.
        allow_single_provider: Downgrades the cross-provider rule to a warning.
        expected_cao_version: CAO version the kit expects; doctor warns otherwise.
        project: Project slug when this is a project-scoped (effective) config; its
            profiles are named ``<project>_<role>-<tool>``. None for the user-level config.
    """

    roles: dict[str, Binding]
    allow_soft_engineer: bool = False  # lets a soft-enforcement tool be the engineer
    allow_single_provider: bool = False  # downgrades the cross-provider rule to a warning
    expected_cao_version: str = CAO_VERSION
    project: str | None = None


def default_path() -> Path:
    """Return the default config path.

    Returns:
        ``$CAOKIT_HOME/caokit.toml`` if set, else ``~/.config/caokit/caokit.toml``.
    """
    home = os.environ.get("CAOKIT_HOME")
    base = Path(home) if home else Path.home() / ".config" / "caokit"
    return base / "caokit.toml"


def _only(d: dict[str, Any], allowed: Iterable[str], where: str) -> None:
    """Reject keys not in ``allowed`` so typos fail loudly instead of being ignored."""
    allowed = set(allowed)
    for k in d:
        if k not in allowed:
            raise ConfigError(f"unknown key {where}.{k}" if where else f"unknown key {k}")


def _parse_project_name(raw: Any) -> str | None:
    """Validate the optional ``[project] name`` table, returning the slug or None."""
    if raw is None:
        return None
    _only(raw, {"name"}, "project")
    name = raw.get("name")
    if not isinstance(name, str):
        raise ConfigError("project.name must be a string")
    try:
        return validate_project_name(name)
    except ValueError as e:
        raise ConfigError(str(e)) from e


def parse_config(d: dict[str, Any]) -> Config:
    """Validate a parsed TOML dict and build a :class:`Config`.

    Tool names are not checked here; the roster rules report unknown or parked
    tools with a clearer message.

    Args:
        d: The dict produced by parsing ``caokit.toml``.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: Wrong schema, unknown/missing role, unknown key, or bad type.
    """
    _only(d, {"schema", "cao", "policy", "roles", "project"}, "")
    if d.get("schema") != SCHEMA:
        raise ConfigError(f"schema must be {SCHEMA} (got {d.get('schema')!r})")
    cao = d.get("cao", {})
    _only(cao, {"expected_version"}, "cao")
    pol = d.get("policy", {})
    _only(pol, {"allow_soft_engineer", "allow_single_provider"}, "policy")
    raw = d.get("roles", {})
    for r in raw:
        if r not in ROLES:
            raise ConfigError(f"unknown role: roles.{r} (valid: {', '.join(ROLES)})")
    roles: dict[str, Binding] = {}
    for r in ROLES:
        if r not in raw:
            raise ConfigError(f"missing role: roles.{r}")
        b = raw[r]
        _only(b, {"tool", "model"}, "roles." + r)
        if not isinstance(b.get("tool"), str) or not b["tool"]:
            raise ConfigError(f"roles.{r}.tool must be a non-empty string")
        m = b.get("model")
        if m is not None and (not isinstance(m, str) or not m):
            raise ConfigError(f"roles.{r}.model must be a non-empty string")
        roles[r] = Binding(b["tool"], m)
    for k in ("allow_soft_engineer", "allow_single_provider"):
        if not isinstance(pol.get(k, False), bool):
            raise ConfigError(f"policy.{k} must be true or false")
    return Config(
        roles=roles,
        allow_soft_engineer=pol.get("allow_soft_engineer", False),
        allow_single_provider=pol.get("allow_single_provider", False),
        expected_cao_version=cao.get("expected_version", CAO_VERSION),
        project=_parse_project_name(d.get("project")),
    )


def load_config(path: Path | None = None) -> Config:
    """Read and validate the config file.

    Args:
        path: File to read; the default location if None.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: The file is missing, is not valid TOML, or fails validation.
    """
    path = Path(path) if path else default_path()
    if not path.is_file():
        raise ConfigError(f"config not found: {path} (run `caokit company create`)")
    try:
        return parse_config(tomllib.loads(path.read_text(encoding="utf-8")))
    except ValueError as e:  # TOMLDecodeError subclasses ValueError
        raise ConfigError(f"invalid TOML in {path}: {e}") from e


def dump_config(c: Config) -> str:
    """Serialise a config to TOML text (hand-rolled: stdlib can only read TOML).

    Args:
        c: The configuration to write.

    Returns:
        TOML text that :func:`parse_config` round-trips.
    """
    q = json.dumps  # JSON string escaping is valid TOML basic-string escaping
    out = [
        f"schema = {SCHEMA}",
        "",
        "[cao]",
        f"expected_version = {q(c.expected_cao_version)}",
        "",
        "[policy]",
        f"allow_soft_engineer = {str(c.allow_soft_engineer).lower()}",
        f"allow_single_provider = {str(c.allow_single_provider).lower()}",
    ]
    if c.project:
        out[2:2] = ["[project]", f"name = {q(c.project)}", ""]
    for r in ROLES:
        b = c.roles[r]
        out += ["", f"[roles.{r}]", f"tool = {q(b.tool)}"]
        if b.model:  # omit entirely when unset so the tool default applies
            out.append(f"model = {q(b.model)}")
    return "\n".join(out) + "\n"
