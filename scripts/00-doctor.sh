#!/usr/bin/env bash
set -u

missing=0

check_command() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf '[ok]   %-16s %s\n' "$name" "$(command -v "$name")"
  else
    printf '[miss] %-16s not found on PATH\n' "$name"
    missing=1
  fi
}

printf '%s\n' 'CAO agent-company prerequisite check'
printf '%s\n' '------------------------------------'

for cmd in git tmux uv cao cao-server cao-mcp-server claude agy python3; do
  check_command "$cmd"
done

printf '\nVersions:\n'
command -v git >/dev/null 2>&1 && git --version || true
command -v tmux >/dev/null 2>&1 && tmux -V || true
command -v uv >/dev/null 2>&1 && uv --version || true
command -v cao >/dev/null 2>&1 && cao --version || true
command -v claude >/dev/null 2>&1 && claude --version || true
command -v agy >/dev/null 2>&1 && agy --version || true
command -v python3 >/dev/null 2>&1 && python3 --version || true

if command -v cao >/dev/null 2>&1; then
  cao_version="$(cao --version 2>/dev/null || true)"
  case "$cao_version" in
    *2.5.0*)
      printf '\n[ok] CAO 2.5.0 detected.\n'
      ;;
    *)
      printf '\n[warn] This kit was written against CAO 2.5.0. Detected: %s\n' "$cao_version"
      printf '[warn] Review profile and CLI compatibility before continuing.\n'
      ;;
  esac
fi

printf '\nManual authentication checks still required:\n'
printf '%s\n' '  1. Run claude directly and complete login.'
printf '%s\n' '  2. Run agy directly, finish onboarding, then run: agy models'

if [ "$missing" -ne 0 ]; then
  printf '\nOne or more prerequisites are missing. Fix them, open a new shell, and rerun this script.\n' >&2
  exit 1
fi

printf '\nAll required commands are present.\n'
