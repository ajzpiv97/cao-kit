"""Project-level configuration: per-project overrides layered on the user-level company.

The user-level ``caokit.toml`` (``~/.config/caokit``) defines the default roster. A
project may add ``<repo>/.company/caokit.toml`` with a project name and overrides for
individual roles. The *effective* config is the user-level one with those overrides
applied, and its profiles are named ``<project>_<role>-<tool>`` so projects never
overwrite each other in CAO's machine-global profile store.

Example project file::

    schema = 1
    [project]
    name = "myapp"
    [policy]
    allow_soft_engineer = false
    [roles.engineer]
    model = "sonnet"            # tool omitted: keep the user-level tool
"""

import json
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import ROLES, AdapterError, Runner, default_runner, load_adapter, validate_model
from .config import POLICY_KEYS, SCHEMA, Binding, Config, ConfigError, _only
from .render import validate_project_name
from .roster import check_roster

# Lives under .company/, which the managed .gitignore block ignores (except contracts/).
PROJECT_FILE = Path(".company") / "caokit.toml"
_POLICY_KEYS = POLICY_KEYS


@dataclass
class Overrides:
    """A project's name and its per-role / policy overrides.

    Attributes:
        name: Project slug used to namespace profile names.
        roles: For each overridden role, only the keys given: ``tool`` and/or ``model``.
        policy: Policy switches the project sets explicitly.
        keep_archived_days: Days an archived task file is kept before ``tasks prune``
            deletes it; None keeps archived tasks forever.
    """

    name: str
    roles: dict[str, dict[str, str]] = field(default_factory=dict)
    policy: dict[str, bool] = field(default_factory=dict)
    keep_archived_days: int | None = None


def parse_overrides(d: dict[str, Any]) -> Overrides:
    """Validate a parsed project ``caokit.toml`` and build :class:`Overrides`.

    Args:
        d: The dict produced by parsing the project file.

    Returns:
        The validated overrides.

    Raises:
        ConfigError: Wrong schema, missing/invalid project name, unknown key or role,
            or a value of the wrong type.
    """
    _only(d, {"schema", "project", "policy", "roles", "tasks"}, "")
    if d.get("schema") != SCHEMA:
        raise ConfigError(f"schema must be {SCHEMA} (got {d.get('schema')!r})")
    proj = d.get("project")
    if not isinstance(proj, dict) or not isinstance(proj.get("name"), str):
        raise ConfigError("project.name is required (a string)")
    _only(proj, {"name"}, "project")
    try:
        name = validate_project_name(proj["name"])
    except ValueError as e:
        raise ConfigError(str(e)) from e
    pol = d.get("policy", {})
    _only(pol, _POLICY_KEYS, "policy")
    for k, v in pol.items():
        if not isinstance(v, bool):
            raise ConfigError(f"policy.{k} must be true or false")
    roles: dict[str, dict[str, str]] = {}
    for role, o in d.get("roles", {}).items():
        if role not in ROLES:
            raise ConfigError(f"unknown role: roles.{role} (valid: {', '.join(ROLES)})")
        _only(o, {"tool", "model"}, f"roles.{role}")
        for k, v in o.items():
            if not isinstance(v, str) or not v:
                raise ConfigError(f"roles.{role}.{k} must be a non-empty string")
        roles[role] = dict(o)
    tasks = d.get("tasks", {})
    _only(tasks, {"keep_archived_days"}, "tasks")
    days = tasks.get("keep_archived_days")
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or days < 1):
        raise ConfigError("tasks.keep_archived_days must be a whole number of days, at least 1")
    return Overrides(name=name, roles=roles, policy=dict(pol), keep_archived_days=days)


def load_overrides(repo: Path) -> Overrides:
    """Read and validate ``<repo>/.company/caokit.toml``.

    Args:
        repo: Project root.

    Returns:
        The validated overrides.

    Raises:
        ConfigError: The file is missing, is not valid TOML, or fails validation.
    """
    path = Path(repo) / PROJECT_FILE
    if not path.is_file():
        raise ConfigError(
            f"no project config at {path}; run `caokit init {repo} --name <project>` first"
        )
    try:
        return parse_overrides(tomllib.loads(path.read_text(encoding="utf-8")))
    except ValueError as e:  # TOMLDecodeError subclasses ValueError
        raise ConfigError(f"invalid TOML in {path}: {e}") from e


def dump_overrides(ov: Overrides) -> str:
    """Serialise overrides to TOML text.

    Args:
        ov: The overrides to write.

    Returns:
        TOML text that :func:`parse_overrides` round-trips.
    """
    q = json.dumps  # JSON string escaping is valid TOML basic-string escaping
    out = [f"schema = {SCHEMA}", "", "[project]", f"name = {q(ov.name)}"]
    if ov.policy:
        out += ["", "[policy]"] + [f"{k} = {str(v).lower()}" for k, v in ov.policy.items()]
    for role in ROLES:  # fixed order keeps the file stable across runs
        if role in ov.roles:
            out += ["", f"[roles.{role}]"] + [f"{k} = {q(v)}" for k, v in ov.roles[role].items()]
    if ov.keep_archived_days is not None:
        out += ["", "[tasks]", f"keep_archived_days = {ov.keep_archived_days}"]
    return "\n".join(out) + "\n"


def apply_overrides(base: Config, ov: Overrides) -> Config:
    """Layer a project's overrides on the user-level config.

    Merge rules, per role: a given ``tool``/``model`` replaces the base value. If the
    tool changes and no model is given, the base model is dropped (a model ID from one
    tool is meaningless for another), so the tool default applies until one is set.

    Args:
        base: The user-level configuration.
        ov: The project's overrides.

    Returns:
        A new config named for the project; ``base`` is not modified.
    """
    roles = {r: Binding(b.tool, b.model) for r, b in base.roles.items()}
    for role, o in ov.roles.items():
        b = base.roles[role]
        tool = o.get("tool", b.tool)
        if "model" in o:
            model: str | None = o["model"]
        elif tool != b.tool:
            model = None
        else:
            model = b.model
        roles[role] = Binding(tool, model)
    return Config(
        roles=roles,
        allow_soft_engineer=ov.policy.get("allow_soft_engineer", base.allow_soft_engineer),
        allow_soft_general=ov.policy.get("allow_soft_general", base.allow_soft_general),
        allow_single_provider=ov.policy.get("allow_single_provider", base.allow_single_provider),
        expected_cao_version=base.expected_cao_version,
        project=ov.name,
    )


def parse_override_specs(specs: Sequence[str]) -> dict[str, dict[str, str]]:
    """Parse ``--override`` CLI values into per-role overrides.

    Accepted forms: ``role=tool``, ``role=tool:model`` and ``role=:model`` (model only,
    keeping the user-level tool).

    Args:
        specs: Values such as ``engineer=claude:sonnet``.

    Returns:
        Mapping of role to the keys given for it.

    Raises:
        ConfigError: A spec is malformed or names an unknown role.
    """
    out: dict[str, dict[str, str]] = {}
    for spec in specs:
        role, sep, rest = spec.partition("=")
        if not sep or role not in ROLES or not rest:
            raise ConfigError(
                f"bad --override {spec!r}: use role=tool[:model] or role=:model "
                f"(roles: {', '.join(ROLES)})"
            )
        tool, _, model = rest.partition(":")
        entry: dict[str, str] = {}
        if tool:
            entry["tool"] = tool
        if model:
            entry["model"] = model
        out[role] = {**out.get(role, {}), **entry}
    return out


def resolve_project(
    repo: Path, base: Config, name: str | None, specs: Sequence[str]
) -> tuple[Config, Overrides | None]:
    """Work out the effective config for a project.

    With ``name`` or ``specs``, build new overrides (to be written by the caller).
    Otherwise load the project's existing file. With neither and no file, the project
    is not namespaced and the user-level config applies unchanged.

    Args:
        repo: Project root.
        base: The user-level configuration.
        name: Project slug from ``--name``, if given.
        specs: ``--override`` values, if any.

    Returns:
        ``(effective_config, new_overrides)``. ``new_overrides`` is None when nothing
        new needs writing.

    Raises:
        ConfigError: Overrides without a name, bad specs, or an invalid project file.
    """
    if name or specs:
        if not name:
            raise ConfigError("--override needs --name <project> so the profiles are namespaced")
        try:
            validate_project_name(name)
        except ValueError as e:
            raise ConfigError(str(e)) from e
        ov = Overrides(name=name, roles=parse_override_specs(specs))
        return apply_overrides(base, ov), ov
    if (Path(repo) / PROJECT_FILE).is_file():
        return apply_overrides(base, load_overrides(repo)), None
    return base, None


def effective_config(repo: Path, base: Config) -> Config:
    """Return the project's effective config (requires an existing project file).

    Args:
        repo: Project root.
        base: The user-level configuration.

    Returns:
        ``base`` with the project's overrides applied and its name set.

    Raises:
        ConfigError: The project file is missing or invalid.
    """
    return apply_overrides(base, load_overrides(repo))


def check_effective(
    cfg: Config, ov: Overrides | None, runner: Runner = default_runner
) -> tuple[list[str], list[str]]:
    """Run the roster rules and validate overridden models against their tools.

    Args:
        cfg: The effective config.
        ov: The overrides being applied, or None to check the roster rules only.
        runner: Command runner used to ask tools for their model lists.

    Returns:
        ``(errors, warnings)``.
    """
    res = check_roster(cfg)
    errors, warnings = list(res.errors), list(res.warnings)
    for role in ov.roles if ov else {}:
        b = cfg.roles[role]
        if not b.model:
            continue
        try:
            adapter = load_adapter(b.tool)
        except AdapterError:
            continue  # unknown tool is already reported by the roster rules
        e, w = validate_model(adapter, b.model, runner)
        errors += [f"roles.{role}: {x}" for x in e]
        warnings += [f"roles.{role}: {x}" for x in w]
    return errors, warnings


def set_keep_archived_days(repo: Path, days: int) -> Path:
    """Record how long archived tasks are kept in the project's ``caokit.toml``.

    Args:
        repo: Project root; it must already have a project file (``caokit init --name``).
        days: Days to keep an archived task, at least 1.

    Returns:
        The path written.

    Raises:
        ConfigError: No project file, an invalid existing file, or ``days`` below 1.
    """
    if days < 1:
        raise ConfigError("tasks.keep_archived_days must be a whole number of days, at least 1")
    ov = load_overrides(repo)
    ov.keep_archived_days = days
    path = Path(repo) / PROJECT_FILE
    path.write_text(dump_overrides(ov), encoding="utf-8")
    return path
