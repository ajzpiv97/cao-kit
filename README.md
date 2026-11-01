# CAO agent company kit (v0.1.0)

A small, local "company" of coding agents. You talk to **one** commanding agent (today
named the *captain*, Claude Code). It drafts task files, waits for your approval, then
delegates to specialist coding-agent CLIs through
[CAO](https://github.com/awslabs/cli-agent-orchestrator) (`cli-agent-orchestrator`),
using subscriptions you already pay for.

The kit is generic: it assumes no particular project, language or stack. A project brings its
own validation commands (test/CI command) and its own rules.

- **Platform:** macOS (Apple Silicon tested), tmux backend.
- **CAO:** exactly **2.5.4**, installed with `uv tool`.
- **Status:** validated end to end with a Claude + Antigravity roster (see [Validation](#validation)).

## caokit CLI (v1 slice, in development)

```bash
uv tool install git+https://github.com/<user>/cao-kit      # or: uv tool install --from . caokit
caokit doctor
caokit company create --general claude:sonnet --engineer claude:opus \
    --scout antigravity:gemini-3.8-flash-medium --inspector antigravity:gemini-4-argon-high
caokit install              # add --replace-legacy / --remove-legacy if CAO or old profiles object
caokit init /path/to/repo   # scaffolds .company/, ROSTER.md and merges .gitignore
```

Config lives in `~/.config/caokit/caokit.toml` (`$CAOKIT_HOME` or `--config` to override). Roles are
tool-agnostic; concrete CAO profiles are named `<role>-<tool>` (CAO allows only `[A-Za-z0-9_-]`).
The older scripts below still work for the v0 roster.

### Per-project setups

CAO's profile store is machine-global (profiles are not looked up in a project directory), so two projects
sharing `engineer-claude` would overwrite each other's model. Give a project its own namespaced profiles:

```bash
caokit init ~/proj-a --name proja                          # same roster as the user-level config
caokit init ~/proj-b --name projb --override engineer=:sonnet --override scout=claude:haiku
caokit install --project ~/proj-a                          # installs proja_general-claude, proja_engineer-claude, ...
caokit install --project ~/proj-b
cao launch --agents proja_general-claude --session-name proja --working-directory ~/proj-a
```

- Two layers: the user-level `caokit.toml`, then the project's `.company/caokit.toml` (git-ignored) with a
  `[project] name`, optional `[policy]`, and per-role `tool`/`model` overrides.
- Override forms: `role=tool`, `role=tool:model`, `role=:model` (keep the tool). Changing a role's tool
  without a model drops the user-level model (a model ID from one tool means nothing to another).
- Names are `<project>_<role>-<tool>`; the project is 1-24 lowercase letters, digits or `-`.
- All guardrails (cross-provider inspection, soft-engineer opt-in, model validation) re-run on the merged config.
- Without `--name`, `init` keeps today's behaviour: shared `<role>-<tool>` profiles.
- Each project is its own CAO session (one `cao-server` serves them all); give each a distinct `--session-name`.
- Not yet built: removing a project's profiles from CAO. Delete `<project>_*` from the profile store by hand.

### Developing caokit

```bash
export PYTHONPATH=src
uvx ruff check src tests && uvx ruff format --check src tests   # lint + format (Google docstrings enforced)
uvx mypy                                                          # strict types for src, lenient for tests
python3 -B -m unittest discover -s tests -t .                    # unit tests (a real-cao test runs if `cao` is installed)
uvx --with coverage coverage run --source=src -m unittest discover -s tests -t . && uvx --with coverage coverage report -m
```

Ruff lints and formats but does not type-check, so mypy covers types. Both target Python 3.11, the minimum
(`requires-python = ">=3.11"`); caokit has no runtime dependencies. `uv tool install` fetches a suitable
interpreter, so the system Python does not matter.

## Roster

| Profile | Provider | Job | Tool limits |
|---|---|---|---|
| `startup_captain` | `claude_code`, `permissionMode: auto` | Single entry point: task intake, dispatch, acceptance procedure, synthesis | Native: no Bash, Agent/Task, Monitor, web. Read/list/write + `cao-mcp-server` |
| `claude_engineer` | `claude_code`, auto | Implements; runs **only** the task's authorised validation commands | Web blocked. `execute_bash` also unlocks Claude's Agent/Task tools, so "no subagents" is instruction-only |
| `agy_researcher` | `antigravity_cli` (default render: `gemini-3.8-flash-medium`) | Research | Advisory only |
| `agy_reviewer` | `antigravity_cli` (default render: `gemini-4-argon-high`) | Reviews Claude-authored code; re-runs the authorised commands | Advisory only |
| `claude_reviewer` | `claude_code`, auto | Reviews research and non-source artifacts | Native: no shell, no subagents, no web |

Why this split: **Claude implements, Antigravity reviews Claude's code.** Claude's tool limits
are enforced natively by CAO. Antigravity's are **advisory**: CAO launches it with
`--dangerously-skip-permissions`, so review must come from a different provider than the author.
The Claude profiles do not set `model:`; they inherit your Claude Code default.

Codex was dropped from the roster (see [Parked: Codex](#parked-codex)).

## Prerequisites

`git`, `tmux`, `uv`, `python3` (3.9+), `cao`, `cao-server`, `cao-mcp-server`, `claude`, `agy`.

```bash
brew install tmux uv
uv tool install 'cli-agent-orchestrator==2.5.4'
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
./scripts/00-doctor.sh          # checks commands and versions
./scripts/97-cao-install-audit.sh   # proves there is exactly one CAO install
```

Change the CAO version only with `uv tool install --force 'cli-agent-orchestrator==X'`, never
`uv tool upgrade` or `cao update`. Log in to `claude` and `agy` **directly, outside CAO**, once
(send one harmless prompt each), so no login screen appears inside an orchestrated terminal.
`agy models` lists the exact model IDs.

## Quickstart

```bash
export KIT_DIR="$HOME/path/to/cao-agent-company-prototype"
export PROJECT_DIR="$HOME/path/to/your/git-repository"
cd "$KIT_DIR"

# 1. Render profiles (model IDs must match `agy models` exactly)
AGY_MODEL='gemini-3.8-flash-medium' AGY_REVIEW_MODEL='gemini-4-argon-high' \
  ./scripts/10-render-profiles.sh

# 2. Install them into CAO (validates, then installs the 5-profile roster)
./scripts/30-install-cao-profiles.sh

# 3. Scaffold .company/ into a git repository (does not touch application source)
./scripts/40-init-project.sh "$PROJECT_DIR"
#    then edit $PROJECT_DIR/.company/COMPANY.md (mission, repository description)

# 4. Start CAO (terminal A, leave running)
./scripts/50-start-server.sh

# 5. Launch (terminal B)
cd "$PROJECT_DIR" && cao launch --agents startup_captain --session-name agent-company
```

`AGY_MODEL` is required by the render step; `AGY_REVIEW_MODEL` defaults to `AGY_MODEL`.
Rendered output goes to `generated-profiles/` (do not hand-edit; edit `profiles/`).

For a hands-off smoke test instead of step 5, run
`./scripts/60-launch-prototype.sh "$PROJECT_DIR"` (headless TASK-0001; see
`workspace/.company/prompts/first-run.md`). Expect artifacts under `.company/`
(`artifacts/`, `research/`, `reviews/`, `decisions/`) and no application-source changes.

## Interacting with the captain

- `cao launch` **without** `--headless` attaches you to the captain's Claude Code inside tmux.
  This is the interactive chain-of-command mode. Workers are other tmux windows:
  `Ctrl-b w` lists them, `Ctrl-b d` detaches (session keeps running).
- Web UI with live terminals: `http://127.0.0.1:9889/` (root path only). `cao tui` also exists.
- **Don't type into the captain while it is mid-turn.** Worker reports queue and are delivered
  when it is idle. For check-ins use
  `./scripts/80-send.sh "<msg>"` or `cao session send cao-agent-company "<msg>" --timeout 600`.
- Session names get a `cao-` prefix (`agent-company` becomes `cao-agent-company`).
- Never use `cao launch --yolo` and never `allowedTools: ["*"]`: both bypass restrictions.

## Task workflow

1. **Intake.** You state the goal. The captain writes
   `.company/tasks/TASK-NNNN-<slug>.md` from the template with `State: PROPOSED`. Acceptance
   checks are marked "DRAFT – human must confirm", with open questions. The captain then **stops**.
2. **Approval.** Only your explicit "approved" moves it to `APPROVED`, logged in `DECISIONS.md`.
   You own the acceptance checks and the allowed-path review.
3. **Authorised validation commands.** The engineer and reviewer run exactly the commands the
   task lists and nothing else (no `rm`/cleanup, installs, network, or state-changing git). Both
   write a **Commands run** section with real output. The reviewer re-runs the commands itself and
   never reuses the author's output. Prefer no-artifact commands (`python3 -B -m unittest …`).
4. **Acceptance procedure.** The captain diffs every reported command against the allowlist and
   flags extras as a **contract breach**; if the reviewer's output is missing or identical to the
   author's, it asks the reviewer to confirm it ran the commands itself.
5. **Accept.** Only your "accept" moves a task to `ACCEPTED`.

Task files are the audit trail: archive them, don't delete them. Contracts live in `contracts/`
(copied into `.company/contracts/`). In projects, gitignore all of `.company/` except `contracts/`.

> The acceptance/command-allowlist rules (steps 3–4) were added 2026-11-01 and are **not yet
> proven live**; the earlier interactive run showed the problems they address.

## Validation

`./scripts/95-validate-e2e.sh` is the proof harness. It builds a throwaway repo (`taskly`
sample app) under `validation/`, preflights, starts the server, does a full-text profile drift
check (auto-reinstalling if needed), launches TASK-0001, polls the CAO API, collects evidence
and writes `evidence/ACCEPTANCE.md` with a PASS/FAIL verdict. Knobs:
`TIMEOUT_MIN=60 POLL_SEC=15 AUTO_NUDGE=1 STALL_MIN=10 KEEP_SESSION=0 FORCE_REPLACE=0 SKIP_AGY_MODELS=0`.
Stdlib only, Python 3.9+. `validation/` is local run evidence and is not committed.

## Scripts

| Script | Purpose |
|---|---|
| `00-doctor.sh` | Required commands and versions |
| `05-reset-cao.sh` | Clean reinstall: stop CAO, back up `~/.aws/cli-agent-orchestrator` to `~/cao-reset-backup-<ts>/`, reinstall CAO 2.5.4 (`CAO_VERSION=` overrides), install profiles |
| `10-render-profiles.sh` | Render `profiles/` into `generated-profiles/` (`AGY_MODEL`, `AGY_REVIEW_MODEL`) |
| `20-install-codex-profiles.sh` | Parked (Codex) |
| `30-install-cao-profiles.sh` | Validate and install the roster; fails on CAO's silent `Error:`; `REPLACE_LEGACY=1` replaces stale copies |
| `40-init-project.sh <repo>` | Copy `workspace/.company` into a git repo |
| `50-start-server.sh` | `cao-server --terminal tmux` |
| `60-launch-prototype.sh <repo>` | Headless TASK-0001 smoke test |
| `70-status.sh` / `80-send.sh "<msg>"` / `90-stop.sh` | Status / message the captain / stop the session |
| `95-validate-e2e.sh` | End-to-end proof harness (`validate_e2e.py`) |
| `96-ui-check.sh` | Diagnose the web UI |
| `97-cao-install-audit.sh` | Prove exactly one CAO install (`FIX=1` removes pip/pipx/brew copies) |

All scripts are macOS bash 3.2-safe (e.g. no `case` inside `$( … )`, no associative arrays).

## Safety model

- Claude profiles: CAO deny-lists (native) plus `permissionMode: auto`.
- Antigravity: restrictions are **advisory**; treat its profile as guidance, not a boundary.
- No path-level enforcement: any agent with write access can write anywhere in the repo.
  Use **one git worktree per writing task** before using the kit on a real project, and inspect
  `git diff` afterwards.
- No profile may deploy, merge, push, contact third parties, use production credentials, change
  billing, or run destructive git. The human commits.
- Human approval is required for source-changing tasks, merges, pushes, deployments, secrets,
  dependency changes and destructive actions.
- The kit holds no credentials by design.

## Parked: Codex

Codex was removed after every CAO failure turned out to be Codex-specific (MCP approval denied,
inherited `xhigh` reasoning, config drift). The profiles are kept in `profiles/disabled-codex/`
and the sandbox profile files in `codex/`; `scripts/20-install-codex-profiles.sh` installs them.
If Codex returns, the `send_message` callback needs:

```yaml
codexConfig:
  mcp_servers.cao-mcp-server.tools.send_message.approval_mode: "approve"
```

and an explicit `model_reasoning_effort`. Codex 0.134+ reads `~/.codex/NAME.config.toml`
files (see `codex/LEGACY-CODEX-PROFILES.md` for older versions).

## Planned (not implemented)

These are decided but **not part of v0.1.0**; nothing in the current profiles or scripts
implements them.

- **v1: chain-of-command rename and role × tool design.** "Captain" becomes **General**;
  profiles are split into tool-agnostic roles (`general`, `engineer`, `scout`, `inspector`) plus
  tool adapters (claude, antigravity, codex…), bound per project by a roster
  (`.company/ROSTER.md`). Guardrails: an engineer's work must be inspected by a different tool,
  and soft-enforcement tools may not be engineers without an explicit opt-in.
- **v1: `caokit` Python CLI** (`uv tool install git+…`) replacing the bash scripts and the
  `AGY_MODEL` env vars with a `caokit.toml` config; `doctor`, `company create`, `install`,
  `init`, `validate`, `close`.
- Evaluate CAO's `use_worktree` for one worktree per task.

## More

`TROUBLESHOOTING.md`, `SOURCES.md`, `CHANGELOG.md`.

## License

MIT, see `LICENSE`.
