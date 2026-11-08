# Troubleshooting

## `Failed to connect to cao-server` or port 9889 timeout

1. Keep the server running in a separate terminal:

   ```bash
   caokit server
   ```

   `caokit doctor` reports whether the server answers and serves its web UI.

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

Also verify that the models in your `caokit.toml` appear verbatim in `agy models`. `caokit company create` checks this when it writes the file.

## `cao install` printed `Error: ...` but exited 0

CAO 2.5.x refuses to overwrite profile copies written by an older CAO ("installed copy without CAO
source provenance") yet **exits 0**. `caokit install` treats that `Error:` as a failure and verifies the stored copy byte for byte. To replace the stale copies (it backs them up first, then retries):

```bash
caokit install --replace-legacy          # add --project REPO for a project's profiles
```

Leftover pre-v1 profiles (`startup_captain`, `claude_engineer` and the others) in `agent-store/` are harmless; move them to a backup with `caokit install --remove-legacy`.

## `caokit install` refuses a profile because of a file in `~/.kiro/agents`

CAO also records Kiro agent files. If `~/.kiro/agents/<name>.json` exists for a profile that is no longer installed, CAO refuses to install a profile with the same name and tells you to delete the file. macOS is case-insensitive, so `proja` collides with a leftover `projA`. Delete that one file by hand after checking it is a leftover, then rerun the install. `caokit uninstall` does not touch `~/.kiro`.

## The web UI shows nothing / 404

The UI is served only at the root: `http://127.0.0.1:9889/` (not a sub-path). Run `caokit doctor`: it
probes the server and reports when `/` does not answer 200. That is usually an old `cao-server` process
from a previous CAO install, so stop your sessions with `caokit stop`, stop that process, and run
`caokit server` again.

## The General ignores my message

Don't type into the General while it is mid-turn. Worker reports queue and are delivered when it is
idle. Use `caokit send "<msg>" --repo <project>` for check-ins. A bare word such as "confirm" is not
treated as approval: the General asks what you meant.

## `95-validate-e2e.sh` says "A 'cao-e2e' session is already running"

The harness refuses to start next to a live session of the same name. Stop it with
`caokit stop <harness repo>`, or rerun with `FORCE_REPLACE=1` (this shuts that session down). Use
`KEEP_SESSION=1` to keep the harness's own session up for inspection afterwards.

## `cao launch --headless` errors after 300 seconds

With `--headless` **and a first message**, `cao launch` waits up to 300s for the General's reply, then errors while the
session keeps running. Without a message (and for attached launches) it does not wait.
`caokit launch --headless --prompt-file F` behaves the same; add `--async` to return once the prompt is delivered.
Check the session with `caokit status`. Measured on 2026-11-08: a headless launch with no prompt returned in 12s and one
with a one-line prompt in 23s; the 300s error itself was not reproduced.

## `cao profile validate` warns about `fs_write` or `role: researcher`

Both are false positives. CAO's validator builds its vocabulary from its built-in role defaults, and the
`supervisor` role has no `fs_write`. The runtime mapping honours `fs_write` (it maps to Claude's `Edit`,
`Write` and `NotebookEdit`), and explicit `allowedTools` take precedence over a custom role. **Keep
`fs_write` in the General's profile**: without it CAO denies those tools and the General cannot write
`.company/` files.

## There seem to be two CAO installs

Run `caokit doctor`: it fails when it finds a pipx or pip copy next to the uv tool and tells you which.
Remove the extra copy yourself (`pipx uninstall cli-agent-orchestrator`). Duplicate PATH entries are harmless.

## A CAO profile is missing

```bash
caokit install                     # add --project REPO for a namespaced project
cao profile list
cao profile validate <profile>
```

## The session name cannot be found

CAO prefixes custom session names with `cao-`:

```bash
caokit status <project>
```

## A worker completed but the General did not react

Messages are queued and normally delivered when the receiver reaches an idle/completed state. Check status, then nudge the General without asking it to repeat completed work:

```bash
caokit status <project>
caokit send --repo <project> \
  'Reconcile TASK-0001 from existing callbacks and artifact files. Do not rerun completed tasks.' \
```

## A long worker result appears truncated

The operating contract deliberately requires file-based artifacts. Ask the worker for only the path and a short summary:

```bash
caokit send --repo <project> \
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

The Claude roles (`general`, `engineer`) set `permissionMode: auto` so CAO uses a permission mode rather than unconditional permission bypass.

## A provider command works in Terminal but not under CAO

This is usually a `PATH` mismatch. Check all resolved paths in the same shell that starts `cao-server`:

```bash
command -v cao-server
command -v cao-mcp-server
command -v claude
command -v agy
```

Start `cao-server` from that shell.

## Reset just one project

```bash
caokit stop <project>
caokit install --project <project>
```

For a full clean reinstall of CAO itself, run `caokit reset` (a dry run) and then `caokit reset --yes`. It moves CAO's state into `~/cao-reset-backup-<timestamp>/` and does not delete it.

The files under the target repository's `.company/` directory are persistent project artifacts; CAO shutdown does not delete them.

## Parked: Codex

Codex is not in the current roster and cannot be selected. These notes apply only if it returns.

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
