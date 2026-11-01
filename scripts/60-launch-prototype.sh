#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s /absolute/path/to/initialized-repository\n' "$0" >&2
  exit 1
fi

TARGET="$(cd "$1" 2>/dev/null && pwd || true)"
if [ -z "$TARGET" ] || [ ! -f "$TARGET/.company/prompts/first-run.md" ]; then
  printf 'Initialized .company workspace not found in: %s\n' "$1" >&2
  exit 1
fi

PROMPT="$(cat "$TARGET/.company/prompts/first-run.md")"

cd "$TARGET"

printf '%s\n' 'Launching headless CAO session: cao-agent-company'
printf 'Working directory: %s\n' "$TARGET"

cao launch "$PROMPT" \
  --agents startup_captain \
  --session-name agent-company \
  --working-directory "$TARGET" \
  --headless \
  --auto-approve

printf '\nSession launched. Observe it with:\n'
printf '%s\n' '  cao session status cao-agent-company --workers'
