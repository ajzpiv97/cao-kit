#!/usr/bin/env bash
set -euo pipefail
# Render every profile in profiles/ into generated-profiles/.
#   *.md           copied as-is
#   *.md.template  "__AGY_MODEL__" replaced with the Antigravity model:
#                  agy_reviewer uses AGY_REVIEW_MODEL (defaults to AGY_MODEL),
#                  everything else uses AGY_MODEL.
#
#   AGY_MODEL='exact name from `agy models`' ./scripts/10-render-profiles.sh
#   AGY_MODEL='...' AGY_REVIEW_MODEL='stronger model' ./scripts/10-render-profiles.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/generated-profiles"

if [ -z "${AGY_MODEL:-}" ]; then
  printf '%s\n' 'AGY_MODEL is required.' >&2
  printf '%s\n' 'Run: agy models' >&2
  printf '%s\n' "Then: AGY_MODEL='exact Gemini model string' ./scripts/10-render-profiles.sh" >&2
  exit 1
fi
AGY_REVIEW_MODEL="${AGY_REVIEW_MODEL:-$AGY_MODEL}"

mkdir -p "$OUT"
for f in "$ROOT"/profiles/*.md; do
  cp "$f" "$OUT/$(basename "$f")"
  printf 'copied   %s\n' "$(basename "$f")"
done

for t in "$ROOT"/profiles/*.md.template; do
  name="$(basename "$t" .template)"
  model="$AGY_MODEL"
  [ "$name" = "agy_reviewer.md" ] && model="$AGY_REVIEW_MODEL"
  python3 - "$t" "$OUT/$name" "$model" <<'PY'
import json, pathlib, sys
src, dst, model = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3].strip()
if not model:
    raise SystemExit("model cannot be empty")
text = src.read_text(encoding="utf-8")
ph = '"__AGY_MODEL__"'
if ph not in text:
    raise SystemExit(f"placeholder not found in {src}")
dst.write_text(text.replace(ph, json.dumps(model, ensure_ascii=False), 1), encoding="utf-8")
PY
  printf 'rendered %s  (model: %s)\n' "$name" "$model"
done

if grep -l '__AGY_MODEL__' "$OUT"/*.md >/dev/null 2>&1; then
  printf '%s\n' 'Profile rendering failed: unresolved AGY model placeholder.' >&2
  exit 1
fi
printf 'Rendered profiles in %s\n' "$OUT"
