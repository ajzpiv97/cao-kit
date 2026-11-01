# caokit v1 slice Implementation Plan

> **For agentic workers:** use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** `caokit doctor | company create | install | init <repo>` plus project `.gitignore` merge, as a `uv tool`-installable Python CLI.

**Architecture:** Pure modules (config, adapters, roster rules, render, gitignore, stack detect, launch argv) tested with `unittest`; thin side-effect modules (doctor, install, init) shell out to `cao`/CLIs. Roles are tool-agnostic markdown; adapters are declarative TOML; concrete CAO profiles are `<role>-<tool>`.

**Tech Stack:** Python >=3.11 (revised from 3.9 on 2026-11-01: 3.9/3.10 are EOL; drops `tomli`), stdlib only, setuptools, `unittest`.

**Spec:** the approved proposal in this conversation (2026-11-01).

## Global Constraints

- Python `>=3.11`; stdlib only (`tomllib`).
- CAO stays `2.5.4`; never `--yolo`, never `allowedTools: ["*"]`.
- Profile names match `^[A-Za-z0-9_-]{1,64}$`; concrete name = `<role>-<tool>`.
- Roles: general, engineer, scout, inspector. Tools: claude, antigravity, codex (parked, rejected).
- `general` is Claude-only. Soft-enforcement tool as engineer needs `--allow-soft-engineer`.
- Cross-provider rule compares tool AND model vendor.
- Config at `$CAOKIT_HOME/caokit.toml` (default `~/.config/caokit/caokit.toml`).
- Any launch builds argv with `--working-directory <abs path>`.
- Legacy dirs (`profiles/`, `contracts/`, `scripts/`) untouched; no git commit/push/tag.
- Remaining shell must be bash 3.2-safe (none added).

## Review Focus

- Existing `.gitignore` without trailing newline / with CRLF / with user rules already ignoring `.company` -> block appended correctly, user content intact.
- `caokit.toml` with unknown role/tool, missing role, extra keys -> clear error naming the field.
- `agy models` unavailable (not logged in) -> model validation error, not a traceback.
- `cao install` printing `Error:` with exit 0 -> install fails.
- `init` on non-git dir or existing `.company/` -> refuses / never overwrites files.

## File Structure

- `pyproject.toml`, `src/caokit/{__init__,cli}.py`
- `src/caokit/config.py` load/validate/dump `caokit.toml`
- `src/caokit/adapters.py` load adapter TOML, model/vendor helpers
- `src/caokit/roster.py` roster rules (guardrails)
- `src/caokit/render.py` role+adapter -> profile text, names
- `src/caokit/gitignore.py`, `src/caokit/stack.py`, `src/caokit/launch.py`
- `src/caokit/doctor.py`, `src/caokit/install.py`, `src/caokit/init_project.py`, `src/caokit/company.py`
- `src/caokit/data/{roles,adapters,contracts,scaffold}/`
- `tests/test_*.py`

## Tasks

### Task 1: Package skeleton + gitignore merge
- Create `pyproject.toml` (console script `caokit = caokit.cli:main`, package-data), `src/caokit/gitignore.py`, `tests/test_gitignore.py`.
- Produces: `merge_gitignore(existing: str) -> str` (marked block `# >>> caokit >>>`/`# <<< caokit <<<` with `.company/*` and `!.company/contracts/`; idempotent; preserves CRLF and missing trailing newline).
- [ ] Tests: empty, existing rules kept, no trailing newline, CRLF, idempotent twice, block replaced in place.
- [ ] Implement; run `python3 -m unittest tests.test_gitignore -v`.

### Task 2: Adapters + config + roster rules
- Create `adapters.py`, `config.py`, `roster.py`, adapter TOMLs, tests.
- Produces: `load_adapter(id) -> Adapter`; `Config` dataclass; `load_config(path)`, `dump_config(cfg) -> str`; `check_roster(cfg, adapters) -> (errors, warnings)`; `vendor_of(adapter, model) -> str`.
- [ ] Tests: valid roster passes; same tool engineer/inspector errors; antigravity `claude-*` inspector vs claude engineer errors (vendor); soft engineer errors without flag, warns with; antigravity general errors; codex rejected; unknown role/tool/missing role errors; roundtrip dump/load.
- [ ] Implement.

### Task 3: Render
- Create `render.py`, `data/roles/*.md` (from current profiles, "captain" -> General, roster-driven), tests.
- Produces: `profile_name(role, tool) -> str`; `render_profile(role_md, adapter, role, model) -> str`.
- [ ] Tests: name regex valid; frontmatter has provider/model, no model when unset; antigravity notes appended; output deterministic.
- [ ] Implement; verify with real `cao profile validate` in Task 5.

### Task 4: Stack detection + launch argv + ROSTER.md
- Create `stack.py` (`suggest_validation(repo: Path) -> Optional[str]`), `launch.py` (`build_launch_argv(project: Path, profile: str) -> list`), roster markdown renderer, tests.
- [ ] Tests: pytest config -> `python3 -B -m pytest -p no:cacheprovider -q`; unittest layout -> `python3 -B -m unittest`; package.json test script; Makefile `test`; none -> None; argv contains absolute `--working-directory` and never `--yolo`.

### Task 5: doctor, company create, install, init + CLI
- Create `doctor.py`, `company.py`, `install.py`, `init_project.py`, `cli.py`, tests with fake runner injection.
- [ ] Tests: `init` scaffolds, never overwrites, merges gitignore, refuses non-git; `install` fails on `Error:` output with exit 0; `company create` flag-driven writes config and enforces guardrails.
- [ ] Real-command verification: `caokit doctor`; `cao profile validate` on rendered profiles; `caokit install` against a temp `HOME`; `caokit init` on a temp git repo.
- [ ] Update `CHANGELOG.md` (unreleased) and README section.
