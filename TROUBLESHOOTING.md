# Troubleshooting

## `Failed to connect to cao-server` or port 9889 timeout

1. Keep the server running in a separate terminal:

   ```bash
   cao-server --terminal tmux
   ```

2. Check that the process exists:

   ```bash
   ps aux | grep '[c]ao-server'
   ```

3. Clean stale prototype sessions, then restart the server:

   ```bash
   cao shutdown --all
   tmux list-sessions
   ```

4. Do not run a second CAO server on the same port.

## Antigravity initializes forever or times out

Run these directly, outside CAO:

```bash
agy
agy --version
agy models
```

Finish every login/onboarding screen. Then ensure the server was started with:

```bash
cao-server --terminal tmux
```

Antigravity should not be tested through the `herdr` backend.

Also verify that `generated-profiles/agy_researcher.md` and `generated-profiles/agy_reviewer.md` contain an exact model string from `agy models` rather than `__AGY_MODEL__`. There is no agy model env var: `AGY_MODEL` / `AGY_REVIEW_MODEL` are inputs to `10-render-profiles.sh` only.

## `cao install` printed `Error: ...` but exited 0

CAO 2.5.x refuses to overwrite profile copies written by an older CAO ("installed copy without CAO
source provenance") yet **exits 0**. `scripts/30-install-cao-profiles.sh` greps for `Error:` and
fails. To replace the stale copies (backs up `agent-context/<n>.md` and `agent-store/<n>.md`, then retries):

```bash
REPLACE_LEGACY=1 ./scripts/30-install-cao-profiles.sh
```

Check an installed profile matches the source byte for byte:
`diff generated-profiles/<n>.md ~/.aws/cli-agent-orchestrator/agent-store/<n>.md`.
Leftover `codex_engineer` / `codex_reviewer` in `agent-store/` are harmless; they are not in the roster.

## A script fails to parse under macOS `/bin/bash` (3.2)

`case ... in a|b) ...;; esac` **inside `$( ... )`** does not parse in bash 3.2. Put the `case` in a
function and call that. Also avoid associative arrays and `mapfile`, and watch empty arrays under `set -u`.

## The web UI shows nothing / 404

The UI is served only at the root: `http://127.0.0.1:9889/` (not a sub-path). Run `./scripts/96-ui-check.sh`
to diagnose; output goes to `validation/ui-check.txt`.

## The captain ignores my message

Don't type into the captain while it is mid-turn. Worker reports queue and are delivered when it is
idle. Use `cao session send cao-agent-company "<msg>" --timeout 600` (or `./scripts/80-send.sh`) for check-ins.

## `95-validate-e2e.sh` says "A 'cao-agent-company' session is already running"

The harness refuses to start next to a live session of the same name. Stop it with
`./scripts/90-stop.sh`, or rerun with `FORCE_REPLACE=1` (this shuts that session down). Use
`KEEP_SESSION=1` to keep the harness's own session up for inspection afterwards.

## `cao launch --headless` errors after 300 seconds

Without `--async`, headless launch polls 300s, then errors while the session keeps running.
`60-launch-prototype.sh` has this flaw (known issue; the session is fine, check it with `70-status.sh`).

## `cao profile validate` warns about `fs_write` or `role: researcher`

Both are false positives. The validator's vocabulary comes from role defaults; the runtime mapping
honours `fs_write`, and explicit `allowedTools` take precedence over a custom role.

## There seem to be two CAO installs

Run `./scripts/97-cao-install-audit.sh` (`FIX=1` removes pip/pipx/brew copies). Duplicate PATH entries
are harmless.

## A CAO profile is missing

```bash
cd /path/to/cao-agent-company-prototype
./scripts/30-install-cao-profiles.sh
cao profile list
cao profile validate startup_captain
```

## The session name cannot be found

CAO prefixes custom session names with `cao-`:

```bash
cao session list
cao session status cao-agent-company --workers
```

## A worker completed but the captain did not react

Messages are queued and normally delivered when the receiver reaches an idle/completed state. Check status, then nudge the captain without asking it to repeat completed work:

```bash
cao session status cao-agent-company --workers
cao session send cao-agent-company \
  'Reconcile TASK-0001 from existing callbacks and artifact files. Do not rerun completed tasks.' \
  --timeout 600
```

## A long worker result appears truncated

The operating contract deliberately requires file-based artifacts. Ask the worker for only the path and a short summary:

```bash
cao session send cao-agent-company \
  'Use the existing worker. Ask it to write its full result to the contracted artifact path and return only status, path, and five findings.'
```

## Claude Code login or trust prompt appears inside CAO

Authenticate directly first:

```bash
claude
```

Then verify:

```bash
claude --version
```

The Claude profiles (`startup_captain`, `claude_engineer`, `claude_reviewer`) set `permissionMode: auto` so CAO uses a permission mode rather than unconditional permission bypass.

## A provider command works in Terminal but not under CAO

This is usually a `PATH` mismatch. Check all resolved paths in the same shell that starts `cao-server`:

```bash
command -v cao-server
command -v cao-mcp-server
command -v claude
command -v agy
```

Start `cao-server` from that shell.

## Reset just this prototype

```bash
cao shutdown --session cao-agent-company || true
cd /path/to/cao-agent-company-prototype
./scripts/30-install-cao-profiles.sh
```

The files under the target repository's `.company/` directory are persistent project artifacts; CAO shutdown does not delete them.

## Parked: Codex

Codex is not in the current roster; the profiles live in `profiles/disabled-codex/`. These notes apply
only if it returns.

### Codex shows an approval dialog and never completes

The CAO worker must use a non-interactive Codex profile:

```text
approval_policy = "never"
```

Check the files:

```bash
cat ~/.codex/cao_engineer.config.toml
cat ~/.codex/cao_reviewer.config.toml
```

For Codex 0.134.0 or newer, profile files must be separate files named exactly:

```text
~/.codex/cao_engineer.config.toml
~/.codex/cao_reviewer.config.toml
```

Do not use `cao launch --yolo` and do not set `allowedTools: ["*"]`; either causes CAO to bypass the configured Codex sandbox.


### Codex callback denied (`send_message`)

codex >=0.16x requires approval for MCP tools without `readOnlyHint`; with `approval_policy="never"` that
becomes a hard deny, so the worker's callback fails. Fix (already in the parked profiles):

```yaml
codexConfig:
  mcp_servers.cao-mcp-server.tools.send_message.approval_mode: "approve"
```

Also set `model_reasoning_effort`; the global Codex config may otherwise give `xhigh`.
