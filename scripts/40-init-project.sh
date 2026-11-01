#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s /absolute/path/to/git-repository\n' "$0" >&2
  exit 1
fi

TARGET="$(cd "$1" 2>/dev/null && pwd || true)"
if [ -z "$TARGET" ] || [ ! -d "$TARGET" ]; then
  printf 'Target directory does not exist: %s\n' "$1" >&2
  exit 1
fi

if ! git -C "$TARGET" rev-parse --show-toplevel >/dev/null 2>&1; then
  printf 'Target is not inside a Git repository: %s\n' "$TARGET" >&2
  printf '%s\n' 'Initialize Git or choose a low-risk existing repository.' >&2
  exit 1
fi

if [ -e "$TARGET/.company" ] && [ "${FORCE:-0}" != "1" ]; then
  printf 'Refusing to overwrite existing directory: %s/.company\n' "$TARGET" >&2
  printf '%s\n' 'Back it up/merge it manually, or rerun with FORCE=1.' >&2
  exit 1
fi

if [ -e "$TARGET/.company" ]; then
  mv "$TARGET/.company" "$TARGET/.company.backup.$(date +%Y%m%d%H%M%S)"
fi

cp -R "$ROOT/workspace/.company" "$TARGET/.company"
printf 'Initialized %s/.company\n' "$TARGET"
printf '%s\n' 'Review .company/COMPANY.md and .company/prompts/first-run.md before launching.'
