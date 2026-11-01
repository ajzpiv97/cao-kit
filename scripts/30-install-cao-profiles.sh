#!/usr/bin/env bash
set -euo pipefail

# Install/refresh the kit's CAO profiles.
#
# CAO 2.5.x quirk: `cao install` prints "Error: ..." but EXITS 0 when it refuses
# to overwrite a profile copy installed by an older CAO version ("installed copy
# without CAO source provenance"). This script treats that output as failure.
#
# REPLACE_LEGACY=1 moves those stale copies (agent-context/<name>.md and
# agent-store/<name>.md) into a timestamped backup folder and retries once.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILES="$ROOT/generated-profiles"
CAO_HOME="${CAO_HOME_DIR:-$HOME/.aws/cli-agent-orchestrator}"

if [ ! -f "$PROFILES/agy_researcher.md" ]; then
  printf '%s\n' 'Rendered profiles are missing.' >&2
  printf '%s\n' "Run: AGY_MODEL='exact model from agy models' ./scripts/10-render-profiles.sh" >&2
  exit 1
fi

profiles=(
  startup_captain
  claude_engineer
  agy_researcher
  agy_reviewer
  claude_reviewer
)

backup_dir=""
install_one() {
  local name="$1" file="$PROFILES/$1.md" out
  out="$(cao install "$file" 2>&1)" || { printf '%s\n' "$out"; return 1; }
  printf '%s\n' "$out"
  case "$out" in
    *"Error:"*) return 1 ;;
  esac
  return 0
}

failed=()
for name in "${profiles[@]}"; do
  file="$PROFILES/$name.md"
  printf '\nValidating %s\n' "$file"
  cao profile validate "$file" || true
  printf 'Installing %s\n' "$name"
  if install_one "$name"; then
    continue
  fi
  if [ "${REPLACE_LEGACY:-0}" = "1" ]; then
    [ -n "$backup_dir" ] || backup_dir="$CAO_HOME/backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$backup_dir/agent-context" "$backup_dir/agent-store"
    for sub in agent-context agent-store; do
      if [ -e "$CAO_HOME/$sub/$name.md" ]; then
        mv "$CAO_HOME/$sub/$name.md" "$backup_dir/$sub/$name.md"
        printf '  moved stale %s/%s.md -> %s\n' "$sub" "$name" "$backup_dir/$sub/"
      fi
    done
    printf 'Retrying %s\n' "$name"
    install_one "$name" || failed+=("$name")
  else
    failed+=("$name")
  fi
done

if [ "${#failed[@]}" -ne 0 ]; then
  printf '\nFAILED to install: %s\n' "${failed[*]}" >&2
  printf '%s\n' 'If the error mentions "without CAO source provenance", rerun with:' >&2
  printf '%s\n' '  REPLACE_LEGACY=1 ./scripts/30-install-cao-profiles.sh' >&2
  exit 1
fi

printf '\nInstalled profiles:\n'
for name in "${profiles[@]}"; do
  cao profile show "$name" >/dev/null
  printf '  - %s\n' "$name"
done
[ -z "$backup_dir" ] || printf '\nStale copies backed up in %s\n' "$backup_dir"
