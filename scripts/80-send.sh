#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  printf 'Usage: %s message to captain\n' "$0" >&2
  exit 1
fi

cao session send cao-agent-company "$*" --timeout 600
