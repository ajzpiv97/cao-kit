#!/usr/bin/env bash
# Diagnose "{"detail":"Not Found"}" on the CAO web UI. Read-only: changes nothing.
# Writes validation/ui-check.txt so it can be reviewed afterwards.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/validation/ui-check.txt"
mkdir -p "$ROOT/validation"
PORT="${CAO_API_PORT:-9889}"
{
  echo "== date"; date
  echo; echo "== what is listening on :$PORT"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>&1 || echo "(nothing listening)"
  for pid in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null); do
    echo "-- pid $pid: $(ps -o command= -p "$pid")"
    echo "   started: $(ps -o lstart= -p "$pid")"
  done
  echo; echo "== every cao-server process"
  ps -axo pid=,lstart=,command= | grep -E '(^|/)cao-server( |$)' | grep -v grep || echo "(none)"
  echo; echo "== every cao / cao-server on PATH (first one wins)"
  type -a cao cao-server 2>&1
  for c in $(type -ap cao-server); do
    echo "-- $c -> $(readlink "$c" 2>/dev/null || echo '(not a symlink)')"
    echo "   shebang: $(head -1 "$c" 2>/dev/null)"
  done
  echo; echo "== package that the first cao-server would load"
  PY="$(head -1 "$(command -v cao-server)" 2>/dev/null | sed 's/^#!//')"
  echo "python: $PY"
  if [ -n "$PY" ] && [ -x "${PY%% *}" ]; then
    "${PY%% *}" - <<'PYEOF'
import importlib.metadata as m, importlib.resources as r, pathlib
print("version:", m.version("cli-agent-orchestrator"))
w = pathlib.Path(str(r.files("cli_agent_orchestrator") / "web_ui"))
print("web_ui dir:", w)
print("index.html present:", (w / "index.html").exists())
print("assets:", sorted(p.name for p in (w / "assets").glob("*")) if (w / "assets").exists() else "none")
PYEOF
  fi
  echo; echo "== HTTP probes"
  for path in /health / /index.html /dash /ui; do
    code="$(curl -s -o /tmp/cao-ui-probe.$$ -w '%{http_code} %{content_type}' "http://127.0.0.1:$PORT$path" 2>&1)"
    echo "GET $path -> $code | $(head -c 120 /tmp/cao-ui-probe.$$ 2>/dev/null | tr '\n' ' ')"
  done
  rm -f /tmp/cao-ui-probe.$$
  echo; echo "== tmux sessions"; tmux ls 2>&1
} > "$OUT" 2>&1
cat "$OUT"
echo; echo "Saved to $OUT"
