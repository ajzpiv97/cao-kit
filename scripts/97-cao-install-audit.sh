#!/usr/bin/env bash
# Audit (and optionally clean) CAO installations so exactly ONE exists:
# the uv tool install (`uv tool install cli-agent-orchestrator==<ver>`).
#
#   ./scripts/97-cao-install-audit.sh          # read-only report
#   FIX=1 ./scripts/97-cao-install-audit.sh    # uninstall every non-uv copy
#
# Report is also written to validation/cao-install-audit.txt.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/validation/cao-install-audit.txt"
mkdir -p "$ROOT/validation"
PKG=cli-agent-orchestrator
FIX="${FIX:-0}"
extra=0

run() {
  echo "== $*"
  "$@" 2>&1 | sed 's/^/   /'
}

{
echo "CAO install audit  $(date)   FIX=$FIX"

echo; echo "== 1. uv tool (the one we keep)"
if command -v uv >/dev/null; then
  uv tool list 2>/dev/null | sed -n "/^$PKG /,/^[^-]/p" | sed 's/^/   /'
  uv tool list 2>/dev/null | grep -q "^$PKG " || echo "   NOT installed via uv"
  echo "   uv tool dir: $(uv tool dir 2>/dev/null)"
else
  echo "   uv not found"
fi

echo; echo "== 2. pipx"
if command -v pipx >/dev/null && pipx list --short 2>/dev/null | grep -q "^$PKG "; then
  echo "   FOUND pipx install: $(pipx list --short | grep "^$PKG ")"; extra=1
  [ "$FIX" = 1 ] && run pipx uninstall "$PKG"
else
  echo "   none"
fi

echo; echo "== 3. pip in every python on PATH (and common locations)"
seen=""
for py in $(type -ap python3 python3.9 python3.10 python3.11 python3.12 python3.13 python3.14 2>/dev/null) \
          /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  [ -x "$py" ] || continue
  real="$(cd "$(dirname "$py")" && pwd -P)/$(basename "$py")"
  case " $seen " in *" $real "*) continue ;; esac
  seen="$seen $real"
  v="$("$py" -c "import importlib.metadata as m; print(m.version('$PKG'))" 2>/dev/null)"
  if [ -n "$v" ]; then
    loc="$("$py" -m pip show "$PKG" 2>/dev/null | awk '/^Location:/{print $2}')"
    echo "   FOUND $PKG $v in $py  ($loc)"; extra=1
    if [ "$FIX" = 1 ]; then
      "$py" -m pip uninstall -y "$PKG" 2>&1 | sed 's/^/     /' \
        || "$py" -m pip uninstall -y --break-system-packages "$PKG" 2>&1 | sed 's/^/     /'
    fi
  else
    echo "   none in $py"
  fi
done

echo; echo "== 4. Homebrew"
if command -v brew >/dev/null && brew list --formula 2>/dev/null | grep -qiE 'cli-agent-orchestrator|^cao$'; then
  echo "   FOUND brew formula"; extra=1
  [ "$FIX" = 1 ] && run brew uninstall cli-agent-orchestrator
else
  echo "   none"
fi

echo; echo "== 5. Every cao* executable in common bin dirs"
UVBIN="$(uv tool dir 2>/dev/null)/$PKG/bin"
# A function (not inline in $(...)): macOS bash 3.2 cannot parse `case` inside $(...).
scan_bins() {
  local d f tgt
  for d in "$HOME/.local/bin" /usr/local/bin /opt/homebrew/bin "$HOME/bin" \
           $(echo "$PATH" | tr ':' '\n'); do
    [ -d "$d" ] || continue
    for f in "$d"/cao "$d"/cao-server "$d"/cao-mcp-server "$d"/cao-ops-mcp-server; do
      [ -e "$f" ] || continue
      tgt="$(readlink "$f" 2>/dev/null || true)"
      case "$tgt" in
        "$UVBIN"/*|*/uv/tools/$PKG/bin/*) echo "   ok    $f -> $tgt (uv)";;
        *) echo "   OTHER $f ${tgt:+-> $tgt}  shebang: $(head -1 "$f" 2>/dev/null | cut -c1-80)";;
      esac
    done
  done | sort -u
}
bins="$(scan_bins)"
echo "$bins"
case "$bins" in *OTHER*) extra=1 ;; esac

echo; echo "== 6. PATH entries that appear more than once"
echo "$PATH" | tr ':' '\n' | sort | uniq -d | sed 's/^/   duplicate: /'
echo "   (duplicates are harmless; fix by removing the repeated export from ~/.zshrc / ~/.zprofile)"

echo; echo "== 7. Leftover CAO state"
ls -d "$HOME"/cao-reset-backup-* 2>/dev/null | sed 's/^/   reset backup: /' || true
echo "   live state: $HOME/.aws/cli-agent-orchestrator ($(du -sh "$HOME/.aws/cli-agent-orchestrator" 2>/dev/null | cut -f1))"

echo; echo "== 8. Resolved now"
hash -r
echo "   cao:        $(command -v cao)  ($(cao --version 2>/dev/null))"
echo "   cao-server: $(command -v cao-server)"

echo
if [ "$extra" = 1 ] && [ "$FIX" != 1 ]; then
  echo "RESULT: extra CAO copies found. Rerun with FIX=1 to remove them (the uv install is kept)."
elif [ "$extra" = 1 ]; then
  echo "RESULT: extra copies were found and FIX=1 attempted removal. Rerun without FIX to confirm."
else
  echo "RESULT: exactly one CAO install (uv tool)."
fi
} 2>&1 | tee "$OUT"
