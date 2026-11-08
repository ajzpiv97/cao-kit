"""caokit command line."""

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, schedule
from .adapters import ROLES, AdapterError, adapter_ids, load_adapter
from .company import CompanyError, create_company, parse_binding, write_company
from .config import Binding, ConfigError, default_path, load_config
from .doctor import format_report, run_doctor
from .init_project import InitError, init_project
from .install import (
    InstallError,
    cao_home,
    find_legacy,
    install_profiles,
    remove_legacy,
    uninstall_profiles,
)
from .launch import (
    build_launch_argv,
    build_send_argv,
    build_status_argv,
    build_stop_argv,
    session_id,
    session_name,
)
from .project import (
    check_effective,
    effective_config,
    load_overrides,
    resolve_project,
    set_keep_archived_days,
)
from .render import profile_name
from .reset import ResetError, plan, run_reset
from .tasks import (
    TaskError,
    archive_finished,
    format_tasks,
    load_tasks,
    prune_archive,
    with_blockers,
)


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
        cfg = create_company(
            bindings,
            a.allow_soft_engineer,
            a.allow_single_provider,
            allow_soft_general=a.allow_soft_general,
        )
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


def cmd_uninstall(a: argparse.Namespace) -> int:
    """Run ``caokit uninstall [--project REPO] [--yes]``: remove the roster's CAO profiles.

    Args:
        a: Parsed arguments (``config``, ``project``, ``yes``).

    Returns:
        0 on success or on a dry run, 1 if the config is invalid or a removal failed.
    """
    try:
        cfg = load_config(a.config)
        if a.project:
            cfg = effective_config(Path(a.project), cfg)
        res = uninstall_profiles(cfg, apply=a.yes)
    except (ConfigError, InstallError, AdapterError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    verb = "Removed" if a.yes else "Would remove"
    print(f"{verb}: {', '.join(res.removed) or 'nothing'}")
    if res.missing:
        print(f"Not installed: {', '.join(res.missing)}")
    if res.backup:
        print(f"Leftover agent-context copies moved to {res.backup}")
    if res.failed:
        print(f"FAILED: {', '.join(res.failed)}", file=sys.stderr)
        return 1
    if res.removed and not a.yes:
        print("Dry run only. Rerun with --yes to remove them.")
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


def cmd_tasks(a: argparse.Namespace) -> int:
    """Run ``caokit tasks [list|archive]``.

    Args:
        a: Parsed arguments (``action``, ``repo``, ``all``, ``delete``).

    Returns:
        0 on success, 1 if the folder is missing or the dependencies loop.
    """
    action, repo_arg = a.action, a.repo
    if action not in ("list", "archive", "prune", "policy", "schedule"):  # bare repo means list
        action, repo_arg = "list", action
    repo = Path(repo_arg).resolve()
    try:
        if action in ("prune", "policy", "schedule"):
            return _tasks_retention(action, repo, a)
        if action == "archive":
            done = archive_finished(repo, delete=a.delete)
            verb = "Deleted" if a.delete else "Archived"
            print(f"{verb} {len(done)} finished task(s).")
            for t in done:
                print(f"  {t.id} ({t.state})")
            return 0
        print(format_tasks(with_blockers(load_tasks(repo)), show_all=a.all))
    except (TaskError, ConfigError, schedule.ScheduleError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _run(argv: Sequence[str]) -> int:
    """Run ``argv`` with the terminal attached and return its exit code (127 if not found)."""
    try:
        return subprocess.call(list(argv))
    except FileNotFoundError:
        print(f"error: command not found: {argv[0]}", file=sys.stderr)
        return 127


def _session_of(a: argparse.Namespace) -> tuple[Path, str, str]:
    """Resolve ``(project, effective_general_profile, session_name)`` for a repo argument.

    Raises:
        ConfigError: If the user-level or project config is invalid.
    """
    repo = Path(a.repo).resolve()
    cfg, _ = resolve_project(repo, load_config(a.config), None, [])
    general = profile_name("general", cfg.roles["general"].tool, cfg.project)
    return repo, general, session_name(repo, cfg.project)


def cmd_launch(a: argparse.Namespace) -> int:
    """Run ``caokit launch [repo]``: start the project's General in a CAO session.

    Args:
        a: Parsed arguments (``repo``, ``prompt_file``, ``headless``, ``auto_approve``).

    Returns:
        The exit code of ``cao launch``, or 1 if the project or prompt file is unusable.
    """
    try:
        repo, general, name = _session_of(a)
        prompt = None
        if a.prompt_file:
            prompt = Path(a.prompt_file).read_text(encoding="utf-8")
            if not prompt.strip():
                raise ValueError(f"prompt file is empty: {a.prompt_file}")
        argv = build_launch_argv(
            repo,
            general,
            name,
            prompt=prompt,
            headless=a.headless,
            auto_approve=a.auto_approve,
        )
    except (ConfigError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return _run(argv)


def cmd_status(a: argparse.Namespace) -> int:
    """Run ``caokit status [repo]``: list sessions and show this project's workers."""
    try:
        _, _, name = _session_of(a)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    codes = [_run(argv) for argv in build_status_argv(session_id(name))]
    return max(codes)


def cmd_send(a: argparse.Namespace) -> int:
    """Run ``caokit send MESSAGE [--repo R]``: message the project's General."""
    try:
        _, _, name = _session_of(a)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return _run(build_send_argv(session_id(name), a.message, a.timeout))


def cmd_stop(a: argparse.Namespace) -> int:
    """Run ``caokit stop [repo]``: shut the project's session down (no confirmation prompt)."""
    try:
        _, _, name = _session_of(a)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return _run(build_stop_argv(session_id(name)))


def cmd_reset(a: argparse.Namespace) -> int:
    """Run ``caokit reset``: back up CAO's state and reinstall CAO and the profiles.

    Args:
        a: Parsed arguments (``yes``, ``config``).

    Returns:
        0 on success or on a dry run, 1 if the config is invalid or a step fails.
    """
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    home = cao_home()
    print("This will:")
    for i, step in enumerate(plan(cfg.expected_cao_version, home), 1):
        print(f"  {i}. {step}")
    if not a.yes:
        print("Dry run only. Nothing was changed; rerun with --yes to do it.")
        return 0

    def reinstall() -> None:
        res = install_profiles(cfg, home)
        if res.failed:
            raise ResetError("profile install failed: " + ", ".join(res.failed))

    try:
        res = run_reset(
            cfg.expected_cao_version,
            home,
            Path.home() / ".gemini" / "config" / "mcp_config.json",
            Path.home(),
            install_profiles=reinstall,
        )
    except ResetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for step in res.steps:
        print("  " + step)
    print(f"Reset complete. Backup: {res.backup}")
    return 0


def cmd_server(a: argparse.Namespace) -> int:
    """Run ``caokit server``: start the CAO server in the foreground (Ctrl-C stops it)."""
    print("Starting the CAO server (tmux backend). Leave this terminal running.")
    return _run(["cao-server"])


def _caokit_exe() -> str:
    """Return the absolute path of the ``caokit`` executable, for a cron entry.

    Raises:
        ValueError: ``caokit`` is not on PATH and the running script is not a usable file.
    """
    found = shutil.which("caokit")
    if found:
        return str(Path(found).absolute())
    me = Path(sys.argv[0])
    if me.is_file() and me.suffix != ".py" and os.access(me, os.X_OK):
        return str(me.absolute())
    raise ValueError("cannot find the caokit executable on PATH; install it with `uv tool install`")


def _tasks_retention(action: str, repo: Path, a: argparse.Namespace) -> int:
    """Handle ``tasks prune``, ``tasks policy`` and ``tasks schedule`` for one project.

    Raises:
        TaskError: The project has no tasks folder.
        ConfigError: The project file is missing or invalid.
        schedule.ScheduleError: The crontab could not be written.
    """
    if action == "policy":
        if a.keep_archived_days is None:
            days = load_overrides(repo).keep_archived_days
            print(f"keep_archived_days: {days if days else 'not set (archived tasks are kept)'}")
            return 0
        print(f"Wrote {set_keep_archived_days(repo, a.keep_archived_days)}")
        return 0
    if action == "prune":
        days = a.days
        if days is not None and days < 1:
            raise ValueError("--days must be a whole number of days, at least 1")
        if days is None:
            days = load_overrides(repo).keep_archived_days
        if days is None:
            print(
                "error: no retention set. Pass --days N, or run "
                "`caokit tasks policy --keep-archived-days N`.",
                file=sys.stderr,
            )
            return 1
        old = prune_archive(repo, days, apply=a.yes)
        verb = "Deleted" if a.yes else "Would delete"
        print(f"{verb} {len(old)} archived task(s) older than {days} day(s).")
        for p in old:
            print(f"  {p.name}")
        if old and not a.yes:
            print("Dry run only. Rerun with --yes to delete them.")
        return 0
    # schedule
    if a.remove:
        removed = schedule.remove(repo)
        print("Removed the cron entry." if removed else "No cron entry for this project.")
        return 0
    line = schedule.cron_line(_caokit_exe(), repo, a.at)
    if a.install:
        if a.keep_archived_days is None and load_overrides(repo).keep_archived_days is None:
            print(
                "error: set a retention first with `caokit tasks policy --keep-archived-days N`; "
                "the scheduled prune fails without one.",
                file=sys.stderr,
            )
            return 1
        if a.keep_archived_days is not None:  # the cron line carries no --days, so save it
            print(f"Wrote {set_keep_archived_days(repo, a.keep_archived_days)}")
        schedule.install(line, repo)
        print("Installed daily cron entry:")
    else:
        print("Cron entry (add it with --install):")
    print("  " + line)
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
    cc.add_argument("--allow-soft-general", action="store_true")
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
    un = sub.add_parser("uninstall", help="remove the roster's profiles from CAO")
    un.add_argument("--project", metavar="REPO", help="remove this project's namespaced profiles")
    un.add_argument("--yes", action="store_true", help="do it (default is a dry run)")
    un.set_defaults(fn=cmd_uninstall)
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
    tk = sub.add_parser("tasks", help="list open tasks and blockers, or archive finished ones")
    tk.add_argument(
        "action",
        nargs="?",
        default="list",
        help="list (default), archive, prune, policy or schedule",
    )
    tk.add_argument("repo", nargs="?", default=".")
    tk.add_argument("--all", action="store_true", help="list: include finished tasks")
    tk.add_argument("--delete", action="store_true", help="archive: delete instead of moving")
    tk.add_argument("--days", type=int, help="prune: keep archived tasks this many days")
    tk.add_argument("--yes", action="store_true", help="prune: delete (default is a dry run)")
    tk.add_argument(
        "--keep-archived-days", type=int, metavar="N", help="policy: set the retention in days"
    )
    tk.add_argument("--install", action="store_true", help="schedule: add the daily cron entry")
    tk.add_argument("--remove", action="store_true", help="schedule: remove the cron entry")
    tk.add_argument("--at", default=schedule.DEFAULT_TIME, help="schedule: time of day, HH:MM")
    tk.set_defaults(fn=cmd_tasks)
    lc = sub.add_parser("launch", help="start the project's General in a CAO session")
    lc.add_argument("repo", nargs="?", default=".")
    lc.add_argument("--prompt-file", metavar="FILE", help="send this file as the first message")
    lc.add_argument("--headless", action="store_true", help="start detached")
    lc.add_argument("--auto-approve", action="store_true", help="skip CAO's launch confirmation")
    lc.set_defaults(fn=cmd_launch)
    st = sub.add_parser("status", help="show sessions and this project's workers")
    st.add_argument("repo", nargs="?", default=".")
    st.set_defaults(fn=cmd_status)
    sd = sub.add_parser("send", help="send a message to the project's General")
    sd.add_argument("message")
    sd.add_argument("--repo", default=".")
    sd.add_argument("--timeout", type=int, default=600)
    sd.set_defaults(fn=cmd_send)
    sp = sub.add_parser("stop", help="shut the project's session down")
    sp.add_argument("repo", nargs="?", default=".")
    sp.set_defaults(fn=cmd_stop)
    rs = sub.add_parser("reset", help="back up CAO state, then reinstall CAO and the profiles")
    rs.add_argument("--yes", action="store_true", help="do it (default is a dry run)")
    rs.set_defaults(fn=cmd_reset)
    sub.add_parser("server", help="start the CAO server").set_defaults(fn=cmd_server)
    a = p.parse_args(argv)
    code: int = a.fn(a)  # each subcommand registered its handler via set_defaults(fn=...)
    return code


if __name__ == "__main__":
    sys.exit(main())
