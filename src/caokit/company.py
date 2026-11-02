"""`caokit company create`: build, check and write caokit.toml."""

from collections.abc import Callable
from pathlib import Path

from .adapters import ROLES, AdapterError, Runner, default_runner, load_adapter, validate_model
from .config import Binding, Config, default_path, dump_config
from .roster import check_roster


class CompanyError(Exception):
    """Raised when a company cannot be created (bad roster, bad model, file exists)."""


def parse_binding(spec: str) -> Binding:
    """Parse a ``tool`` or ``tool:model`` command-line spec.

    Args:
        spec: For example ``claude`` or ``antigravity:gemini-4-argon-high``.

    Returns:
        The binding; ``model`` is None when no ``:model`` part is given.

    Raises:
        CompanyError: The tool part is empty.
    """
    # partition on the first ":" only, so model IDs may not contain one but tools never do.
    tool, _, model = spec.partition(":")
    if not tool:
        raise CompanyError(f"empty tool in {spec!r}")
    return Binding(tool, model or None)


def create_company(
    bindings: dict[str, Binding],
    allow_soft_engineer: bool = False,
    allow_single_provider: bool = False,
    allow_soft_general: bool = False,
    runner: Runner = default_runner,
    out: Callable[[str], None] = print,
) -> Config:
    """Build a config from role bindings and check every guardrail.

    Roster rules and model validation both run before anything is returned, so
    all problems are reported together. Overriding a recommended model only
    warns; an unlisted or unverifiable model is an error.

    Args:
        bindings: Role name to binding; every role in ``ROLES`` must be present.
        allow_soft_engineer: Accept a soft-enforcement tool as engineer.
        allow_single_provider: Downgrade the cross-provider rule to a warning.
        allow_soft_general: Accept a soft-enforcement tool as the General.
        runner: Command runner used to validate models (injectable for tests).
        out: Sink for warnings and recommendation notes.

    Returns:
        The validated :class:`Config` (not yet written to disk).

    Raises:
        CompanyError: A role is missing, the roster breaks a guardrail, or a
            model ID is rejected. The message lists every problem.
    """
    cfg = Config(
        roles=dict(bindings),
        allow_soft_engineer=allow_soft_engineer,
        allow_single_provider=allow_single_provider,
        allow_soft_general=allow_soft_general,
    )
    errors: list[str] = [f"role {role} has no tool" for role in ROLES if role not in cfg.roles]
    if errors:
        raise CompanyError("\n".join(errors))  # cannot check a partial roster
    r = check_roster(cfg)
    errors += r.errors
    for role in ROLES:
        b = cfg.roles[role]
        try:
            a = load_adapter(b.tool)
        except AdapterError:
            continue  # already reported by check_roster as an unknown tool
        rec = a.roles[role].recommended_model
        if b.model:
            e, w = validate_model(a, b.model, runner)
            errors += [f"roles.{role}: {x}" for x in e]
            r.warnings += [f"roles.{role}: {x}" for x in w]
            if rec and b.model != rec:  # advice only: the user's choice wins
                r.warnings.append(f"roles.{role}: {b.model} is not the recommended model ({rec})")
        elif rec:
            out(f"  note: roles.{role} has no model set; recommended for {a.id} is {rec}")
    for warning in r.warnings:
        out("WARNING: " + warning)
    if errors:
        raise CompanyError("\n".join(errors))
    return cfg


def write_company(cfg: Config, path: Path | None = None, force: bool = False) -> Path:
    """Write ``cfg`` as caokit.toml, creating parent directories.

    Args:
        cfg: The validated configuration.
        path: Destination (default: :func:`caokit.config.default_path`).
        force: Overwrite an existing file.

    Returns:
        The path written.

    Raises:
        CompanyError: The file exists and ``force`` is False.
    """
    path = Path(path) if path else default_path()
    if path.exists() and not force:
        raise CompanyError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_config(cfg), encoding="utf-8")
    return path
