#!/usr/bin/env bash
# Clean reinstall of CAO and this kit's profiles.
#
# Nothing is deleted: CAO state and the Antigravity MCP
# config are MOVED/COPIED into ~/cao-reset-backup-<timestamp>/ first. Once a
# validation run passes you can remove that folder yourself.
#
#   ./scripts/05-reset-cao.sh                 # pins CAO 2.5.4
#   CAO_VERSION=2.5.3 ./scripts/05-reset-cao.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAO_VERSION="${CAO_VERSION:-2.5.4}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/cao-reset-backup-$TS"
CAO_HOME="${CAO_HOME_DIR:-$HOME/.aws/cli-agent-orchestrator}"
AGY_MCP="$HOME/.gemini/config/mcp_config.json"
mkdir -p "$BACKUP"

say() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; printf 'Backup so far: %s\n' "$BACKUP" >&2; exit 1; }

say "1/6 Stop CAO sessions and server"
if command -v cao >/dev/null 2>&1; then cao shutdown --all >/dev/null 2>&1 || true; fi
# Only the real server: argv[0] (or argv[1] after a python interpreter) ends in
# /cao-server. A plain `pkill -f cao-server` would also hit any shell, editor or
# script whose command line merely mentions the word.
cao_server_pids() {
  ps -axo pid=,command= | awk '{
    a1=$2; a2=$3
    if (a1 ~ /(^|\/)cao-server$/ || (a1 ~ /[Pp]ython/ && a2 ~ /(^|\/)cao-server$/)) print $1
  }'
}
for pid in $(cao_server_pids); do kill "$pid" 2>/dev/null && printf '  stopped cao-server pid %s\n' "$pid"; done
sleep 2
if command -v tmux >/dev/null 2>&1; then
  tmux list-sessions -F '#{session_name}' 2>/dev/null | grep '^cao-' | while read -r s; do
    tmux kill-session -t "$s" && printf '  killed tmux session %s\n' "$s"
  done || true
fi
if [ -n "$(cao_server_pids)" ]; then
  die "cao-server still running (pids: $(cao_server_pids | tr '\n' ' ')). Stop it and rerun."
fi
echo "  stopped"

say "2/6 Move CAO state aside: $CAO_HOME"
if [ -d "$CAO_HOME" ]; then
  mv "$CAO_HOME" "$BACKUP/cli-agent-orchestrator"
  printf '  moved to %s/cli-agent-orchestrator\n' "$BACKUP"
else
  echo "  (none found)"
fi

say "3/6 Remove CAO entries from Antigravity MCP config"
if [ -f "$AGY_MCP" ]; then
  cp "$AGY_MCP" "$BACKUP/gemini-mcp_config.json"
  python3 - "$AGY_MCP" <<'PY'
import json, sys
p = sys.argv[1]
try:
    cfg = json.load(open(p))
except Exception as e:
    print("  could not parse, left unchanged:", e); sys.exit(0)
servers = cfg.get("mcpServers") or {}
drop = [k for k, v in servers.items()
        if k.startswith("cao") or "cao-mcp-server" in json.dumps(v)]
for k in drop:
    servers.pop(k)
json.dump(cfg, open(p, "w"), indent=2)
print("  removed:", ", ".join(drop) if drop else "nothing (no CAO entries)")
PY
else
  echo "  (no $AGY_MCP)"
fi

say "4/6 Uninstall CAO"
uv tool uninstall cli-agent-orchestrator 2>&1 | sed 's/^/  /' || true
hash -r
if command -v cao >/dev/null 2>&1; then
  die "'cao' is still on PATH at $(command -v cao) - it was installed some other way (pip/pipx?). Remove it, then rerun."
fi
echo "  uninstalled"

say "5/6 Install CAO $CAO_VERSION"
uv tool install "cli-agent-orchestrator==$CAO_VERSION" 2>&1 | sed 's/^/  /'
hash -r
for c in cao cao-server cao-mcp-server; do
  command -v "$c" >/dev/null 2>&1 || die "$c not on PATH after install (is ~/.local/bin on PATH?)"
done
v="$(cao --version)"
case "$v" in *"$CAO_VERSION"*) echo "  $v" ;; *) die "unexpected version: $v" ;; esac
cao init 2>&1 | tail -1 | sed 's/^/  /'

say "6/6 Install CAO profiles"
"$ROOT/scripts/30-install-cao-profiles.sh" > "$BACKUP/install-profiles.log" 2>&1 \
  || { cat "$BACKUP/install-profiles.log"; die "profile install failed"; }
STORE="$CAO_HOME/agent-store"
for n in startup_captain claude_engineer agy_researcher agy_reviewer claude_reviewer; do
  [ -f "$STORE/$n.md" ] || die "$n not in $STORE"
  prov="$(cao profile show "$n" | awk '/provider:/{print $2; exit}')"
  printf '  %-16s provider=%s\n' "$n" "$prov"
done
grep -q 'Task intake procedure' "$STORE/startup_captain.md" \
  || die "startup_captain installed WITHOUT the task intake procedure"
echo "  Captain has the task intake procedure"

printf '\nReset complete. Backup: %s\n' "$BACKUP"
printf 'Next:  ./scripts/95-validate-e2e.sh\n'
