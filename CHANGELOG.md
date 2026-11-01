# Changelog

## Unreleased: caokit v1 slice

New Python CLI `caokit` (Python >= 3.11, no runtime dependencies, `uv tool install`), replacing hardcoded profile names with roles.
The bash scripts and the v0.1.0 profiles keep working unchanged.

- `caokit doctor`: CLIs, auth, CAO version and single-install audit, roster check.
- `caokit company create`: writes `caokit.toml` (role -> tool + model). Models are validated against
  the tool (`agy models`); guardrails: cross-provider inspection (tool and model vendor), soft-enforcement
  engineer needs `--allow-soft-engineer`, `general` is Claude-only, Codex is parked.
- `caokit install`: renders `<role>-<tool>` profiles, validates, installs, treats CAO's `Error:`-with-exit-0
  as failure, verifies the stored copy byte for byte, can move legacy profiles to a backup.
- `caokit init <repo>`: scaffolds `.company/`, writes `ROSTER.md` (with an unconfirmed suggested validation
  command), merges the project `.gitignore` (ignore `.company/*` except `contracts/`).
- Per-project setups: `caokit init <repo> --name <project> [--override role=tool:model]` writes
  `.company/caokit.toml` (git-ignored) and a namespaced `ROSTER.md`; `caokit install --project <repo>` installs
  `<project>_<role>-<tool>` profiles so projects never overwrite each other in CAO's global store.
  Measured on CAO 2.5.4: reinstalling the same name with another model silently replaces it, and a per-call
  model override is ignored for Antigravity profiles that pin a model, hence namespaced profiles.
- Not yet ported: validate, close, reset, audit, ui-check, up/down/send. No command removes a project's profiles yet.

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
