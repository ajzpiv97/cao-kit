# Changelog

## Unreleased

### Added
- Per-task git worktrees through CAO's `use_worktree`: `caokit tasks policy --worktrees on|off`, `caokit worktrees` to list the `cao/*` branches, and a launch check that the repo is a git root with a commit. The General dispatches each engineer into its own worktree, keeps the terminal until acceptance, and sends rework to the same terminal; the engineer commits on its branch; the inspector reviews inside the checkout; the human merges. Reinstall profiles after turning it on.

## v0.2.1 (2026-11-08)

### Fixed
- `status`, `send` and `stop` targeted `cao-cao-<name>` for projects whose session name starts with `cao-`; `stop` reported success while the session kept running.
- Session names carry a short hash of the project path (two checkouts called `app` no longer share a session).
- A launch or send message starting with `-` is no longer parsed as a `cao` option; an empty prompt file is an error.
- `reset` checks the roster and `uv` before moving anything, reports a hung or missing tool as an error naming the backup, installs CAO with a 15 minute timeout, refuses a symlinked or home-level CAO folder, and uses unique backup folders.
- `tasks schedule --install` no longer treats an unreadable crontab as empty, escapes `%` in paths, always uses an absolute `caokit` path, and saves `--keep-archived-days`.
- `tasks prune --days` below 1 is rejected; `uninstall` reports an unknown adapter as an error.

### Added
- `caokit launch --async`.

## v0.2.0 (2026-11-02): caokit replaces the bash kit

New Python CLI `caokit` (Python >= 3.11, no runtime dependencies, `uv tool install`), replacing hardcoded profile names with roles.

### Removed (replaced by `caokit`)
- Legacy profiles (`profiles/`, `generated-profiles/`), the Codex files (`codex/`), and the duplicated scaffold
  (`workspace/`, `contracts/`, `templates/`). The packaged scaffold in `src/caokit/data/scaffold` is the only copy.
- Scripts `00`, `05`, `10`, `20`, `30`, `40`, `50`, `60`, `70`, `80`, `90`, `96`, `97`. Use `caokit doctor`, `reset`,
  `install`, `init`, `server`, `launch`, `status`, `send` and `stop`. `95-validate-e2e.sh` and `token_usage.py` stay as dev tools.
- `validate_e2e.py` now runs entirely through `caokit` (project `e2e`, pinned roster).

### Added
- `caokit launch`, `status`, `send`, `stop`, `server`, `reset`, `uninstall`.
- `caokit doctor` also probes the CAO server and its web UI.
- `allow_soft_general` policy: `general` can be bound to a soft-enforcement tool such as Antigravity with `--allow-soft-general`.
- `caokit tasks policy|prune|schedule`: per-project retention for archived tasks and an opt-in cron entry.
- General role: update task state when a review returns; the cost estimate covers the General's own work; condensed command output is handled.
- `token_usage.py` labels a session by what it writes, not what it reads.

- `caokit doctor`: CLIs, auth, CAO version and single-install audit, roster check.
- `caokit company create`: writes `caokit.toml` (role -> tool + model). Models are validated against
  the tool (`agy models`); guardrails: cross-provider inspection (tool and model vendor), soft-enforcement
  engineer or General needs `--allow-soft-engineer` / `--allow-soft-general`, Codex is parked.
- `caokit install`: renders `<role>-<tool>` profiles, validates, installs, treats CAO's `Error:`-with-exit-0
  as failure, verifies the stored copy byte for byte, can move legacy profiles to a backup.
- `caokit init <repo>`: scaffolds `.company/`, writes `ROSTER.md` (with an unconfirmed suggested validation
  command), merges the project `.gitignore` (ignore `.company/*` except `contracts/`).
- Per-project setups: `caokit init <repo> --name <project> [--override role=tool:model]` writes
  `.company/caokit.toml` (git-ignored) and a namespaced `ROSTER.md`; `caokit install --project <repo>` installs
  `<project>_<role>-<tool>` profiles so projects never overwrite each other in CAO's global store.
  Measured on CAO 2.5.4: reinstalling the same name with another model silently replaces it, and a per-call
  model override is ignored for Antigravity profiles that pin a model, hence namespaced profiles.
- Not yet built: `validate`, `close`. 

## v0.1.0 — baseline (2026-11-01)

First published baseline of the CAO agent company kit. No behaviour changes from the validated state.

### Roster
- Claude Code + Antigravity (`agy`): `startup_captain`, `claude_engineer`, `claude_reviewer`,
  `agy_researcher` (`gemini-3.8-flash-medium`), `agy_reviewer` (`gemini-4-argon-high`).
- Codex dropped from the roster; profiles parked in `profiles/disabled-codex/`.
- Pinned to CAO **2.5.4** (installed with `uv tool`).

### Rules encoded in profiles, template and contracts
- Task intake: goal -> `PROPOSED` task file -> human approval -> `APPROVED`.
- Authorised validation commands, "Commands run" sections, independent reviewer re-run.
- Captain acceptance procedure (command-allowlist diff, contract-breach flagging). Not yet proven live.

### Validation evidence
- Claude + Antigravity roster: PASS, no nudge, ~6 min (`run-20261031-162009`).
- Earlier Codex-era runs failed for Codex-specific reasons (MCP approval deny, stale profile install);
  one passed after reset (`run-20261031-144118`).
- Interactive TASK-0002 in a separate repo worked end to end but exposed unauthorised `rm`
  commands and non-independent reviewer output, which led to the command-allowlist rules above.

### Known gotchas (documented in TROUBLESHOOTING.md)
- `cao install` prints `Error:` yet exits 0 on refusal; `REPLACE_LEGACY=1` handles it.
- macOS bash 3.2: no `case` inside `$( ... )`.
- Web UI only at `/`; do not type into the captain mid-turn; `--headless` without `--async` times out at 300s.

### Housekeeping
- `README.md` rewritten for the current roster (QUICKSTART folded in); `TROUBLESHOOTING.md` updated.
- Smoke-test task renamed `TASK-0001-two-provider-smoke-test.md`; scaffold/text references updated.

### Planned (not in this release)
- v1: General/engineer/scout/inspector roles decoupled from tools; `caokit` Python CLI.
