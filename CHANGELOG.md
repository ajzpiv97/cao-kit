# Changelog

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
