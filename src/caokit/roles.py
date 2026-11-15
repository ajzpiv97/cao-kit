"""Custom roles: add, remove and list roles beyond the four built-in ones.

A custom role is a role file (``<role>.md``, the same format as the built-in ones) plus a
binding to a tool in ``caokit.toml``. User-level files live next to the user config in
``roles/``; a project's live in ``.company/roles/`` and are found first.
"""

import contextlib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .adapters import (
    ROLE_ID_RE,
    ROLES,
    AdapterError,
    Runner,
    default_runner,
    load_adapter,
    validate_model,
)
from .config import Binding, Config, ConfigError, default_path, dump_config, load_config, roles_dir
from .init_project import write_roster
from .project import (
    PROJECT_FILE,
    PROJECT_ROLES,
    apply_overrides,
    dump_overrides,
    load_overrides,
)
from .render import load_role, role_description, role_file
from .roster import check_roster


class RoleError(Exception):
    """Raised when a custom role cannot be added or removed."""


@dataclass
class RoleInfo:
    """One row of ``caokit role list``.

    Attributes:
        name: Role ID.
        builtin: True for the four roles that ship with caokit.
        binding: The tool and model bound to it, or None for a role file nothing binds.
        file: The custom role's file, or None for a built-in role or a missing file.
        description: The role file's ``description``.
    """

    name: str
    builtin: bool
    binding: Binding | None
    file: Path | None
    description: str


@dataclass
class AddResult:
    """What ``add_role`` wrote."""

    role_file: Path
    created: bool  # False when an existing role file was used
    config_file: Path
    warnings: list[str] = field(default_factory=list)


def template(role: str) -> str:
    """Return the starter role file for a new custom role."""
    text = (resources.files("caokit") / "data" / "role_template.md").read_text(encoding="utf-8")
    return text.replace("__ROLE__", role).replace("__TITLE__", role.capitalize())


def list_roles(cfg: Config) -> list[RoleInfo]:
    """List every role ``cfg`` binds, then custom role files that nothing binds yet."""
    out = []
    for role, b in cfg.roles.items():
        try:
            desc = role_description(load_role(role, cfg.role_dirs))
        except ValueError:
            desc = ""
        path = None if role in ROLES else role_file(role, cfg.role_dirs)
        out.append(RoleInfo(role, role in ROLES, b, path, desc))
    seen = set(cfg.roles)
    for d in cfg.role_dirs:
        for path in sorted(d.glob("*.md")) if d.is_dir() else []:
            if ROLE_ID_RE.match(path.stem) and path.stem not in seen and path.stem not in ROLES:
                seen.add(path.stem)
                desc = role_description(path.read_text(encoding="utf-8"))
                out.append(RoleInfo(path.stem, False, None, path, desc))
    return out


def _check_name(role: str) -> None:
    if role in ROLES:
        raise RoleError(f"{role} is a built-in role; its file ships with caokit")
    if not ROLE_ID_RE.match(role):
        raise RoleError(f"invalid role name {role!r}: use lowercase letters and digits only")


def add_role(
    role: str,
    binding: Binding,
    config_path: Path | None = None,
    repo: Path | None = None,
    source: Path | None = None,
    runner: Runner = default_runner,
) -> AddResult:
    """Create a custom role's file if needed and bind the role to a tool.

    The roster rules and the model check run before the config is written. If they fail,
    a role file created by this call is removed again and nothing else changes.

    Args:
        role: New role ID (lowercase letters and digits, not a built-in name).
        binding: The tool, and optionally the model, that fills it.
        config_path: User-level ``caokit.toml`` (default location if None).
        repo: Project root to add the role to that project only; None for user level.
        source: An existing role file to copy; the starter template is used if None and
            no file for this role exists yet.
        runner: Command runner used to ask a tool for its model list.

    Returns:
        The role file, whether it was created, the config file written, and warnings.

    Raises:
        RoleError: Bad name, unreadable source, or the roster rules reject the role.
        ConfigError: The user-level or project config is missing or invalid.
    """
    _check_name(role)
    config_path = Path(config_path) if config_path else default_path()
    base = load_config(config_path)
    target = (Path(repo) / PROJECT_ROLES if repo else roles_dir(config_path)) / (role + ".md")
    if repo:
        ov = load_overrides(repo)
        ov.roles[role] = {"tool": binding.tool}
        if binding.model:
            ov.roles[role]["model"] = binding.model
        cfg = apply_overrides(base, ov, repo)
        config_file, config_text = Path(repo) / PROJECT_FILE, dump_overrides(ov)
    else:
        base.roles[role] = binding
        cfg = base
        config_file, config_text = config_path, dump_config(base)

    created = False
    if source is not None:
        if target.exists():
            raise RoleError(f"{target} already exists; edit it, or omit --from to keep it")
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as e:
            raise RoleError(f"cannot read {source}: {e}") from e
        created = True
    elif role_file(role, cfg.role_dirs) is None:
        text, created = template(role), True
    if created:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    res = check_roster(cfg)
    errors, warnings = list(res.errors), list(res.warnings)
    if binding.model:
        try:
            adapter = load_adapter(binding.tool)
        except AdapterError:
            adapter = None  # unknown tool is already reported by the roster rules
        if adapter is not None:
            bad, advice = validate_model(adapter, binding.model, runner)
            errors += [f"roles.{role}: {x}" for x in bad]
            warnings += [f"roles.{role}: {x}" for x in advice]
    if errors:
        if created:
            target.unlink()
        raise RoleError("\n".join(errors))
    config_file.write_text(config_text, encoding="utf-8")
    if repo:
        write_roster(Path(repo), cfg, runner)
    found = role_file(role, cfg.role_dirs)
    assert found is not None  # the roster rules above reject a role without a file
    return AddResult(found, created, config_file, warnings)


def remove_role(role: str, config_path: Path | None = None, repo: Path | None = None) -> Path:
    """Unbind a custom role. Its role file is kept so it can be added again.

    Args:
        role: Custom role ID.
        config_path: User-level ``caokit.toml`` (default location if None).
        repo: Project root to remove the role from that project's file; None for user level.

    Returns:
        The config file written.

    Raises:
        RoleError: Bad name, or the role is not bound in that file.
        ConfigError: The user-level or project config is missing or invalid.
    """
    _check_name(role)
    config_path = Path(config_path) if config_path else default_path()
    base = load_config(config_path)
    if repo:
        ov = load_overrides(repo)
        if role not in ov.roles:
            raise RoleError(f"{role} is not bound in {Path(repo) / PROJECT_FILE}")
        del ov.roles[role]
        path = Path(repo) / PROJECT_FILE
        path.write_text(dump_overrides(ov), encoding="utf-8")
        # A problem in the remaining overrides is reported by the next command that loads them.
        with contextlib.suppress(ConfigError):
            write_roster(Path(repo), apply_overrides(base, ov, repo), default_runner)
        return path
    if role not in base.roles:
        raise RoleError(f"{role} is not bound in {config_path}")
    del base.roles[role]
    config_path.write_text(dump_config(base), encoding="utf-8")
    return config_path
