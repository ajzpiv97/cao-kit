"""Roster rules (guardrails) that decide whether a Config is allowed."""

from dataclasses import dataclass, field

from .adapters import ROLES, Adapter, AdapterError, load_adapter, vendor_of
from .config import Config
from .render import check_role_text, load_role


@dataclass
class Result:
    """Outcome of checking a roster: errors block, warnings inform.

    Attributes:
        errors: Violations that must stop `company create` and `install`.
        warnings: Risks the user should see but may accept.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_roster(cfg: Config) -> Result:
    """Apply every guardrail to ``cfg`` and return all errors and warnings.

    Rules: tools must exist and not be parked; a tool must be allowed to fill
    the role; a soft-enforcement engineer or General needs an explicit opt-in; the
    inspector must be independent of the engineer (different tool and model
    vendor); a single-provider setup is flagged. A custom role must have a usable
    role file, and on a soft-enforcement tool its limits are flagged as advisory.

    Args:
        cfg: The configuration to check.

    Returns:
        All errors and warnings found; never raises for a bad roster.
    """
    res = Result()
    adapters: dict[str, Adapter] = {}
    for role, b in cfg.roles.items():
        try:
            a = load_adapter(b.tool)
        except AdapterError:
            res.errors.append(f"roles.{role}: unknown tool {b.tool!r}")
            continue
        adapters[role] = a
        if a.status == "parked":
            res.errors.append(f"roles.{role}: tool {b.tool!r} is parked and cannot be selected")
            continue  # no point checking capabilities of an unselectable tool
        if role not in ROLES:
            _check_custom_role(cfg, role, a, res)
        if not a.cap(role).can_fill:
            res.errors.append(f"roles.{role}: tool {b.tool!r} cannot fill the {role} role")
        # Soft enforcement means CAO cannot deny tools. The engineer has write + shell, and the
        # General is meant to have neither, so both need an explicit opt-in.
        opt_in = {"engineer": cfg.allow_soft_engineer, "general": cfg.allow_soft_general}
        if role in opt_in and a.enforcement == "soft":
            if not opt_in[role]:
                res.errors.append(
                    f"roles.{role}: tool {b.tool!r} has soft enforcement (tool limits are "
                    f"advisory); pass --allow-soft-{role} to accept this"
                )
            else:
                res.warnings.append(
                    f"{role} uses {b.tool!r}: its tool limits are advisory only, nothing "
                    "stops it from writing or running anything it can reach"
                )
    if "engineer" in adapters and "inspector" in adapters:
        _check_cross_provider(cfg, adapters, res)
    if len({b.tool for b in cfg.roles.values()}) == 1:
        res.warnings.append(
            "single provider in use: independent cross-provider review is not possible"
        )
    return res


def _check_custom_role(cfg: Config, role: str, adapter: Adapter, res: Result) -> None:
    """Check a custom role's file, and flag advisory limits on a soft-enforcement tool."""
    try:
        errors, warnings = check_role_text(load_role(role, cfg.role_dirs))
    except ValueError as e:
        res.errors.append(f"roles.{role}: {e}")
        return
    res.errors += [f"roles.{role}: {e}" for e in errors]
    res.warnings += [f"roles.{role}: {w}" for w in warnings]
    if adapter.enforcement == "soft":
        res.warnings.append(
            f"custom role {role} uses {adapter.id!r}: the tool limits in its role file are "
            "advisory only"
        )


def _check_cross_provider(cfg: Config, adapters: dict[str, Adapter], res: Result) -> None:
    """Require the inspector to differ from the engineer in tool AND model vendor.

    Args:
        cfg: The configuration being checked.
        adapters: Loaded adapters keyed by role (engineer and inspector present).
        res: Result to append errors or warnings to.
    """
    eb, ib = cfg.roles["engineer"], cfg.roles["inspector"]
    problems: list[str] = []
    if eb.tool == ib.tool:
        problems.append(f"engineer and inspector both use tool {eb.tool!r}")
    # Vendor check catches e.g. an Antigravity inspector running a Claude model.
    ev = vendor_of(adapters["engineer"], eb.model)
    iv = vendor_of(adapters["inspector"], ib.model)
    if ev == iv:
        problems.append(f"engineer and inspector models are the same vendor ({ev})")
    for p in problems:
        msg = "cross-provider inspection violated: " + p
        if cfg.allow_single_provider:
            res.warnings.append(msg)
        else:
            res.errors.append(msg + " (--allow-single-provider to override)")
