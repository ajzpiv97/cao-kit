"""caokit command line."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .adapters import ROLES, AdapterError, adapter_ids, load_adapter
from .company import CompanyError, create_company, parse_binding, write_company
from .config import Binding, ConfigError, default_path, load_config
from .doctor import format_report, run_doctor
from .init_project import InitError, init_project
from .install import InstallError, cao_home, find_legacy, install_profiles, remove_legacy
from .project import check_effective, effective_config, resolve_project
from .render import profile_name


def _ask(prompt: str, default: str) -> str:
    """Prompt on stdin, returning ``default`` when the answer is blank.

    Args:
        prompt: Question text.
        default: Value shown in brackets and used for an empty answer.

    Returns:
        The stripped answer or the default.
    """
    ans = input(f"{prompt} [{default}]: ").strip()
    return ans or default


def _interactive_bindings() -> dict[str, Binding]:
    """Ask for a tool and model per role, offering the adapter's recommendation.

    Returns:
        One :class:`Binding` per role. A model answer of ``none`` means "use the
        tool's own default" and is stored as None.
    """
    print("Pick a tool and model per role. Enter accepts the recommendation.")
    active = ", ".join(t for t in adapter_ids() if load_adapter(t).status == "active")
    print(f"Tools: {active} (codex is parked)")
    out: dict[str, Binding] = {}
    for role in ROLES:
        # Claude does the building roles; Antigravity gives the independent second opinion.
        default_tool = "claude" if role in ("general", "engineer") else "antigravity"
        tool = _ask(f"{role} tool", default_tool)
        try:
            rec = load_adapter(tool).roles[role].recommended_model or "none"
        except AdapterError:
            rec = "none"  # unknown tool: roster validation will report it with a clear error
        model = _ask(f"{role} model (or 'none' for the tool default)", rec)
        out[role] = Binding(tool, None if model == "none" else model)
    return out


def cmd_doctor(a: argparse.Namespace) -> int:
    """Run ``caokit doctor``.

    Args:
        a: Parsed arguments (uses ``config``).

    Returns:
        1 if any check failed, else 0.
    """
    rep = run_doctor(a.config)
    print(format_report(rep))
    return 1 if rep.failed else 0


def cmd_company_create(a: argparse.Namespace) -> int:
    """Run ``caokit company create``.

    Args:
        a: Parsed arguments (role specs, policy flags, ``force``, ``config``).

    Returns:
        0 on success, 1 if the roster is invalid or the file cannot be written,
        2 if no roles were given and stdin is not a terminal.
    """
    bindings: dict[str, Binding] = {}
    for role in ROLES:
        spec = getattr(a, role)
        if spec:
            bindings[role] = parse_binding(spec)
    if not bindings:
        if not sys.stdin.isatty():
            # Never block on input() in a pipe or CI job.
            print(
                "error: pass --general/--engineer/--scout/--inspector (tool[:model]) "
                "or run interactively",
                file=sys.stderr,
            )
            return 2
        bindings = _interactive_bindings()
    try:
        cfg = create_company(bindings, a.allow_soft_engineer, a.allow_single_provider)
        path = write_company(cfg, a.config, a.force)
    except CompanyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {path}\nNext: caokit install")
    return 0


def cmd_install(a: argparse.Namespace) -> int:
    """Run ``caokit install``.

    Args:
        a: Parsed arguments (``config``, ``project``, ``replace_legacy``,
            ``remove_legacy``).

    Returns:
        0 on success, 1 on a config/roster error or if any profile failed to install.
    """
    try:
        cfg = load_config(a.config)
        if a.project:
            # Project mode: the user-level config plus the project's overrides, installed
            # under <project>_<role>-<tool> names so other projects are not affected.
            cfg = effective_config(Path(a.project), cfg)
        home = cao_home()
        legacy = [] if a.project else find_legacy(home)  # legacy cleanup is machine-wide only
        res = install_profiles(cfg, home, replace_legacy=a.replace_legacy)
    except (ConfigError, InstallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if res.failed:
        print(f"FAILED: {', '.join(res.failed)}", file=sys.stderr)
        print(
            'If the error mentions "without CAO source provenance", rerun with --replace-legacy.',
            file=sys.stderr,
        )
        return 1
    if legacy:
        print(f"Legacy profiles still installed: {', '.join(legacy)}")
        do = a.remove_legacy
        # Only ask interactively; in a pipe, never move files without the explicit flag.
        if not do and sys.stdin.isatty():
            do = input(f"Move them to a backup folder under {home}? [y/N] ").strip().lower() == "y"
        if do:
            print(f"Moved to {remove_legacy(home, legacy)}")
        else:
            print("Left in place. Run `caokit install --remove-legacy` to move them to a backup.")
    return 0


def cmd_init(a: argparse.Namespace) -> int:
    """Run ``caokit init <repo>``.

    Args:
        a: Parsed arguments (``repo``, ``config``, ``name``, ``override``,
            ``force_project``).

    Returns:
        0 on success, 1 if the config or overrides are bad, or the target is not a git
        repo.
    """
    try:
        base = load_config(a.config)
        repo = Path(a.repo)
        cfg, new_overrides = resolve_project(repo, base, a.name, a.override)
        if cfg.project:
            errors, warnings = check_effective(cfg, new_overrides)
            for w in warnings:
                print("WARNING: " + w)
            if errors:
                print("error: " + "\n       ".join(errors), file=sys.stderr)
                return 1
        res = init_project(repo, cfg, overrides=new_overrides, force_project=a.force_project)
    except (ConfigError, InitError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Created {len(res.created)} file(s), kept {len(res.kept)} existing.")
    for k in res.kept:
        print(f"  kept: {k}")
    for w in res.warnings:
        print("WARNING: " + w)
    if res.suggestion:
        shown = res.suggestion.command or "(none) " + res.suggestion.reason
        print(f"Suggested validation command (confirm at task approval): {shown}")
        if res.suggestion.note:
            print("  note: " + res.suggestion.note)
    else:
        print("No validation command detected; supply one at task approval.")
    print(
        ".gitignore updated (caokit block). Review `git status`, then commit contracts/ yourself."
    )
    if cfg.project:
        general = profile_name("general", cfg.roles["general"].tool, cfg.project)
        repo_abs = Path(a.repo).resolve()
        print(f"Project '{cfg.project}': profiles are namespaced. Next:")
        print(f"  caokit install --project {repo_abs}")
        print(
            f"  cao launch --agents {general} --session-name {cfg.project} "
            f"--working-directory {repo_abs}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``caokit`` console script.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` if None.

    Returns:
        The process exit code of the chosen subcommand.
    """
    p = argparse.ArgumentParser(prog="caokit", description="CAO chain-of-command agent company kit")
    p.add_argument("--version", action="version", version="caokit " + __version__)
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"path to caokit.toml (default: {default_path()})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check CLIs, CAO and config").set_defaults(fn=cmd_doctor)
    co = sub.add_parser("company", help="manage the company roster").add_subparsers(
        dest="sub", required=True
    )
    cc = co.add_parser("create", help="write caokit.toml")
    for role in ROLES:
        cc.add_argument("--" + role, metavar="TOOL[:MODEL]")
    cc.add_argument("--allow-soft-engineer", action="store_true")
    cc.add_argument("--allow-single-provider", action="store_true")
    cc.add_argument("--force", action="store_true")
    cc.set_defaults(fn=cmd_company_create)
    ins = sub.add_parser("install", help="render and install CAO profiles")
    ins.add_argument(
        "--replace-legacy", action="store_true", help="back up stale CAO copies and retry"
    )
    ins.add_argument(
        "--remove-legacy", action="store_true", help="move old pre-v1 profiles to a backup"
    )
    ins.add_argument(
        "--project",
        metavar="REPO",
        help="install this project's namespaced profiles (needs .company/caokit.toml)",
    )
    ins.set_defaults(fn=cmd_install)
    ini = sub.add_parser("init", help="scaffold .company/ in a git repo")
    ini.add_argument("repo")
    ini.add_argument("--name", metavar="PROJECT", help="project slug; namespaces its profiles")
    ini.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="ROLE=TOOL[:MODEL]",
        help="override a role for this project (repeatable); ROLE=:MODEL keeps the tool",
    )
    ini.add_argument(
        "--force-project", action="store_true", help="overwrite an existing .company/caokit.toml"
    )
    ini.set_defaults(fn=cmd_init)
    a = p.parse_args(argv)
    code: int = a.fn(a)  # each subcommand registered its handler via set_defaults(fn=...)
    return code


if __name__ == "__main__":
    sys.exit(main())
