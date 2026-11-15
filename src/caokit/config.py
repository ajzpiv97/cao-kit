"""caokit.toml: load, validate and dump the company configuration."""

import json
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import ROLE_ID_RE, ROLES, ordered_roles
from .render import validate_project_name

SCHEMA = 1
POLICY_KEYS = ("allow_soft_engineer", "allow_soft_general", "allow_single_provider")
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
        roles: Binding for each role: the four built-in ones, then any custom roles.
        allow_soft_engineer: Lets a soft-enforcement tool be the engineer.
        allow_soft_general: Lets a soft-enforcement tool be the General.
        allow_single_provider: Downgrades the cross-provider rule to a warning.
        expected_cao_version: CAO version the kit expects; doctor warns otherwise.
        project: Project slug when this is a project-scoped (effective) config; its
            profiles are named ``<project>_<role>-<tool>``. None for the user-level config.
        role_dirs: Folders searched, in order, for a custom role's ``<role>.md``.
    """

    roles: dict[str, Binding]
    allow_soft_engineer: bool = False  # lets a soft-enforcement tool be the engineer
    allow_soft_general: bool = False  # lets a soft-enforcement tool be the General
    allow_single_provider: bool = False  # downgrades the cross-provider rule to a warning
    expected_cao_version: str = CAO_VERSION
    project: str | None = None
    # Where the files are, not what the company is: two configs differing only here are equal.
    role_dirs: tuple[Path, ...] = field(default=(), compare=False)

    def custom_roles(self) -> list[str]:
        """Return the roles bound beyond the four built-in ones, by name."""
        return [r for r in self.roles if r not in ROLES]


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
    _only(pol, set(POLICY_KEYS), "policy")
    raw = d.get("roles", {})
    for r in raw:
        if r not in ROLES and not ROLE_ID_RE.match(r):
            raise ConfigError(
                f"invalid role name: roles.{r} (a custom role uses lowercase letters and "
                f"digits only; built-in: {', '.join(ROLES)})"
            )
    roles: dict[str, Binding] = {}
    for r in ordered_roles({*ROLES, *raw}):
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
    for k in POLICY_KEYS:
        if not isinstance(pol.get(k, False), bool):
            raise ConfigError(f"policy.{k} must be true or false")
    return Config(
        roles=roles,
        allow_soft_engineer=pol.get("allow_soft_engineer", False),
        allow_soft_general=pol.get("allow_soft_general", False),
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
        cfg = parse_config(tomllib.loads(path.read_text(encoding="utf-8")))
    except ValueError as e:  # TOMLDecodeError subclasses ValueError
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    cfg.role_dirs = (roles_dir(path),)
    return cfg


def roles_dir(config_path: Path | None = None) -> Path:
    """Return the folder holding user-level custom role files, next to ``caokit.toml``."""
    return (Path(config_path) if config_path else default_path()).parent / "roles"


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
        f"allow_soft_general = {str(c.allow_soft_general).lower()}",
        f"allow_single_provider = {str(c.allow_single_provider).lower()}",
    ]
    if c.project:
        out[2:2] = ["[project]", f"name = {q(c.project)}", ""]
    for r in ordered_roles(c.roles):
        b = c.roles[r]
        out += ["", f"[roles.{r}]", f"tool = {q(b.tool)}"]
        if b.model:  # omit entirely when unset so the tool default applies
            out.append(f"model = {q(b.model)}")
    return "\n".join(out) + "\n"
