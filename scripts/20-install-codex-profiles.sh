#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$DEST"

install_one() {
  local source="$1"
  local target="$2"

  if [ -e "$target" ] && [ "${FORCE:-0}" != "1" ]; then
    printf 'Refusing to overwrite existing file: %s\n' "$target" >&2
    printf '%s\n' 'Review it manually or rerun with FORCE=1.' >&2
    exit 1
  fi

  if [ -e "$target" ]; then
    cp "$target" "$target.backup.$(date +%Y%m%d%H%M%S)"
  fi

  install -m 600 "$source" "$target"
  printf 'Installed %s\n' "$target"
}

install_one "$ROOT/codex/cao_engineer.config.toml" "$DEST/cao_engineer.config.toml"
install_one "$ROOT/codex/cao_reviewer.config.toml" "$DEST/cao_reviewer.config.toml"

printf '\nCodex profile files installed.\n'
printf '%s\n' 'CAO will pass --profile cao_engineer or --profile cao_reviewer.'
printf '%s\n' 'For Codex older than 0.134.0, read codex/LEGACY-CODEX-PROFILES.md.'
