#!/usr/bin/env python3
"""Report Claude Code token usage per session for a throwaway smoke repo.

Claude Code writes one transcript per session under
``~/.claude/projects/<repo path with non-alphanumerics replaced by '-'>/``.
Each assistant message carries a ``usage`` block. This script sums them and
labels each session by the ``.company/`` paths it writes to, since the
transcripts do not name the CAO terminal.

Antigravity (agy) sessions are not covered: they leave no token data here.

    python3 scripts/token_usage.py validation/run-XXXX/smoke-repo [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# Only paths a session writes count; reading another role's file says nothing about
# who the session is. First match wins. The captain owns the task file and the
# shared logs, a worker owns only its artifact or review.
ROLE_BY_PATH = (
    ("/.company/tasks/", "captain"),
    ("/.company/DECISIONS.md", "captain"),
    ("/.company/BACKLOG.md", "captain"),
    ("/.company/TEAM.md", "captain"),
    ("/.company/reviews/", "reviewer"),
    ("/.company/artifacts/", "engineer"),
)
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def transcript_dir(repo: Path) -> Path:
    """Return the Claude Code transcript directory for ``repo``."""
    key = re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    return Path.home() / ".claude" / "projects" / key


def written_paths(message: dict) -> list[str]:
    """Return file paths that write tools in an assistant message target."""
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        str(block.get("input", {}).get("file_path", ""))
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") in WRITE_TOOLS
    ]


def summarize(path: Path) -> dict:
    """Sum usage for one transcript, counting each message id once."""
    totals = dict.fromkeys(FIELDS, 0)
    seen: set[str] = set()
    written: list[str] = []
    stamps: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if rec.get("timestamp"):
            stamps.append(rec["timestamp"])
        written += written_paths(msg)
        usage = msg.get("usage")
        key = msg.get("id") or rec.get("uuid")
        if not usage or key in seen:
            continue
        seen.add(key)
        for f in FIELDS:
            totals[f] += usage.get(f) or 0
    role = next((r for d, r in ROLE_BY_PATH if any(d in p for p in written)), "unknown")
    return {
        "session": path.stem,
        "role": role,
        "messages": len(seen),
        "first": min(stamps, default=""),
        "last": max(stamps, default=""),
        **totals,
    }


def main() -> int:
    """Print a usage table for the repo given on the command line."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--json", type=Path, help="also write the rows as JSON here")
    args = ap.parse_args()
    d = transcript_dir(args.repo)
    files = sorted(d.glob("*.jsonl")) if d.is_dir() else []
    if not files:
        print(f"no Claude transcripts found in {d}", file=sys.stderr)
        return 1
    rows = sorted((summarize(f) for f in files), key=lambda r: r["first"])
    total = {f: sum(r[f] for r in rows) for f in FIELDS}
    print("| role | session | msgs | output | cache read | cache write | input |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['role']} | {r['session'][:8]} | {r['messages']} | {r['output_tokens']} | "
            f"{r['cache_read_input_tokens']} | {r['cache_creation_input_tokens']} | "
            f"{r['input_tokens']} |"
        )
    print(
        f"| **total** | | {sum(r['messages'] for r in rows)} | {total['output_tokens']} | "
        f"{total['cache_read_input_tokens']} | {total['cache_creation_input_tokens']} | "
        f"{total['input_tokens']} |"
    )
    if args.json:
        args.json.write_text(json.dumps({"sessions": rows, "total": total}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
