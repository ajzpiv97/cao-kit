#!/usr/bin/env bash
# One-command end-to-end proof that the CAO Claude + Antigravity company works.
# Creates a throwaway repo under validation/, runs TASK-0001 through the real
# scripts (40-init, 60-launch), watches CAO, and writes evidence/ACCEPTANCE.md.
# Knobs: TIMEOUT_MIN, POLL_SEC, AUTO_NUDGE, STALL_MIN, KEEP_SESSION, FORCE_REPLACE,
#        SKIP_AGY_MODELS (see scripts/validate_e2e.py header).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/validate_e2e.py" "$@"
