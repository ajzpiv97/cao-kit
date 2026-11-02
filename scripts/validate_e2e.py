#!/usr/bin/env python3
"""End-to-end validation harness for the CAO Claude + Antigravity agent company.

Runs the documented TASK-0001 smoke test against a throwaway Git repository, driven
entirely through the `caokit` CLI (init, install, launch, send), and writes
machine-checked evidence that the routing actually happened:

    General (general role, claude_code)
    ├── engineer  (claude_code)      -- assign, async callback
    ├── scout     (antigravity_cli)  -- assign, async callback
    └── inspector (antigravity_cli)  -- handoff, sync

Evidence comes from CAO's own API (terminal records incl. provider and
caller_id, inbox messages = callbacks, full terminal transcripts), from Git
(proof that no application source changed), and from the artifact files.

Needs Python 3.11+ (caokit). Otherwise stdlib only.

Environment knobs:
    TIMEOUT_MIN      overall wait for the synthesis (default 60)
    POLL_SEC         poll interval (default 15)
    AUTO_NUDGE       1 = send ONE documented status nudge to the captain if the
                     run stalls (flagged in the report); 0 = never (default 1)
    STALL_MIN        minutes with no progress before the nudge (default 10)
    KEEP_SESSION     1 = leave the CAO session running afterwards (default 0)
    FORCE_REPLACE    1 = shut down an existing cao-agent-company session first
    SKIP_AGY_MODELS  1 = skip `agy models` (if it hangs on your machine)
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "src"))
from caokit.render import profile_name  # noqa: E402

PROJECT = "e2e"  # namespaces the harness's profiles so they never touch a real project's
SESSION = "cao-" + PROJECT  # CAO prefixes the --session-name it is given
# Pinned so the run does not depend on the operator's own caokit.toml.
ROSTER = {
    "general": ("claude", "sonnet"),
    "engineer": ("claude", "sonnet"),
    "scout": ("antigravity", "gemini-3.8-flash-medium"),
    "inspector": ("antigravity", "gemini-4-argon-high"),
}
PROVIDER = {"claude": "claude_code", "antigravity": "antigravity_cli"}
PROFILE = {role: profile_name(role, tool, PROJECT) for role, (tool, _m) in ROSTER.items()}
EXPECTED = {PROFILE[role]: PROVIDER[tool] for role, (tool, _m) in ROSTER.items()}
CAOKIT = [sys.executable, "-m", "caokit.cli"]
CAOKIT_ENV = dict(os.environ, PYTHONPATH=str(KIT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
API = "http://{}:{}".format(
    os.environ.get("CAO_API_HOST", "127.0.0.1"), os.environ.get("CAO_API_PORT", "9889")
)
TIMEOUT_MIN = float(os.environ.get("TIMEOUT_MIN", "60"))
POLL_SEC = float(os.environ.get("POLL_SEC", "15"))
AUTO_NUDGE = os.environ.get("AUTO_NUDGE", "1") == "1"
STALL_MIN = float(os.environ.get("STALL_MIN", "10"))
KEEP_SESSION = os.environ.get("KEEP_SESSION", "0") == "1"
FORCE_REPLACE = os.environ.get("FORCE_REPLACE", "0") == "1"
SKIP_AGY_MODELS = os.environ.get("SKIP_AGY_MODELS", "0") == "1"

REQUIRED_CMDS = [
    "git", "tmux", "uv", "cao", "cao-server", "cao-mcp-server",
    "claude", "agy", "python3",
]
ART = {
    "engineer": ".company/artifacts/TASK-0001-engineering-assessment.md",
    "agy": ".company/research/TASK-0001-agy-product-assessment.md",
    "review": ".company/reviews/TASK-0001-cross-provider-review.md",
    "synthesis": ".company/decisions/TASK-0001-general-synthesis.md",
}
ALLOWED_WRITES = {
    ".company/TEAM.md",
    ".company/BACKLOG.md",
    *ART.values(),
}
DONE_STATES = {"idle", "completed"}

TS = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
RUN_DIR = Path(os.environ.get("RUN_DIR", str(KIT / "validation" / ("run-" + TS)))).resolve()
REPO = RUN_DIR / "smoke-repo"
EVID = RUN_DIR / "evidence"
TERM_DIR = EVID / "terminals"

_log_fh = None
_server_proc = None


# --------------------------------------------------------------------------- utils
def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    if _log_fh:
        _log_fh.write(line + "\n")
        _log_fh.flush()


def run(cmd, timeout=120, cwd=None, env=None, check=False):
    """Run a command, never raising on timeout; returns (rc, combined_output)."""
    try:
        p = subprocess.run(
            cmd, cwd=cwd, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        out = p.stdout or ""
        if check and p.returncode != 0:
            raise RuntimeError(f"{cmd} failed ({p.returncode}):\n{out}")
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        return 124, (out or "") + f"\n[harness] TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def api(method: str, path: str, params=None, timeout=30):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body else None


def api_try(method, path, params=None, timeout=30, default=None):
    try:
        return api(method, path, params, timeout)
    except Exception:
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fatal(Exception):
    pass


# --------------------------------------------------------------------------- phases
def preflight(results: dict) -> None:
    log("PHASE 1/6 preflight")
    lines = []
    missing = []
    for c in REQUIRED_CMDS:
        p = shutil.which(c)
        lines.append("{:<16} {}".format(c, p or "MISSING"))
        if not p:
            missing.append(c)
    lines.append("")
    for c, args in [
        ("cao", ["--version"]), ("claude", ["--version"]),
        ("agy", ["--version"]), ("tmux", ["-V"]), ("git", ["--version"]),
    ]:
        if shutil.which(c):
            rc, out = run([c] + args, timeout=60)
            lines.append("$ {} {}\n{}".format(c, " ".join(args), out.strip()))
            results.setdefault("versions", {})[c] = out.strip().splitlines()[-1] if out.strip() else ""
    write(EVID / "preflight.txt", "\n".join(lines) + "\n")
    results["missing_commands"] = missing
    if missing:
        raise Fatal("Missing commands on PATH: {}".format(", ".join(missing)))

    model = ROSTER["scout"][1]
    results["agy_model_configured"] = model

    # agy models: is the configured model a name agy actually lists?
    if SKIP_AGY_MODELS:
        results["agy_model_listed"] = "SKIPPED"
    else:
        rc, out = run(["agy", "models"], timeout=90)
        write(EVID / "agy-models.txt", out)
        listed = model in out
        results["agy_model_listed"] = "YES" if listed else "NO"
        if not listed:
            log(f"WARN: configured agy model {model!r} not found verbatim in `agy models` output "
                f"(see evidence/agy-models.txt). CAO passes it as `agy --model {model!r}`; "
                "the live run will show whether agy accepts it.")

    rmodel = ROSTER["inspector"][1]
    results["agy_review_model_configured"] = rmodel
    log("preflight ok: versions={} agy_model={!r} (listed={}) agy_review_model={!r}".format(
        results.get("versions"), model, results["agy_model_listed"], rmodel))


def ensure_server(results: dict) -> None:
    global _server_proc
    log("PHASE 2/6 cao-server")
    h = api_try("GET", "/health", timeout=5)
    if h:
        results["server_started_by_harness"] = False
        log(f"reusing running cao-server: {h}")
    else:
        log("starting cao-server --terminal tmux (log: evidence/cao-server.log)")
        fh = open(EVID / "cao-server.log", "w")
        _server_proc = subprocess.Popen(
            ["cao-server", "--terminal", "tmux"], stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        results["server_started_by_harness"] = True
        for _ in range(60):
            time.sleep(1)
            h = api_try("GET", "/health", timeout=3)
            if h:
                break
        if not h:
            raise Fatal("cao-server did not become healthy within 60s (see evidence/cao-server.log)")
    write(EVID / "health.json", json.dumps(h, indent=2))
    results["terminal_backend"] = h.get("terminal_backend")
    if h.get("terminal_backend") != "tmux":
        raise Fatal("cao-server is using backend {!r}; Antigravity requires tmux. "
                    "Stop it and rerun (the harness starts it with --terminal tmux).".format(
                        h.get("terminal_backend")))


def install_profiles(results: dict) -> None:
    """Install the project's namespaced profiles with caokit, then confirm CAO lists them."""
    log("PHASE 3/6 install the project's CAO profiles (caokit install --project)")
    rc, out = run(CAOKIT + ["install", "--project", str(REPO)], timeout=300, env=CAOKIT_ENV)
    write(EVID / "install-profiles.txt", out)
    if rc != 0:
        raise Fatal("caokit install failed (see evidence/install-profiles.txt)")
    report, bad = {}, []
    for name, prov in EXPECTED.items():
        info = api_try("GET", f"/agents/profiles/{name}", default=None)
        info = info if isinstance(info, dict) else None
        report[name] = {
            "installed": info is not None,
            "provider": info.get("provider") if info else None,
            "model": info.get("model") if info else None,
            "allowedTools": info.get("allowedTools") if info else None,
        }
        if info is None or info.get("provider") != prov:
            bad.append(name)
    write(EVID / "installed-profiles.json", json.dumps(report, indent=2))
    results["installed_profiles"] = report
    if bad:
        raise Fatal(f"Installed profiles wrong/missing after install: {bad}")
    log("profiles ok: {}".format({n: r["provider"] for n, r in report.items()}))


SEED = {
    "README.md": """# taskly

A tiny command-line to-do tracker for one person. Tasks live in a local JSON
file (`~/.taskly.json` by default, override with `TASKLY_FILE`).

    python -m taskly add "write report"
    python -m taskly list
    python -m taskly done 1

Run tests with `python -m unittest discover -s tests`.
""",
    "pyproject.toml": """[project]
name = "taskly"
version = "0.1.0"
requires-python = ">=3.9"
""",
    "taskly/__init__.py": "",
    "taskly/__main__.py": "from taskly.cli import main\n\nraise SystemExit(main())\n",
    "taskly/store.py": '''import json
import os
from pathlib import Path


def _path() -> Path:
    return Path(os.environ.get("TASKLY_FILE", str(Path.home() / ".taskly.json")))


def load() -> list:
    p = _path()
    if not p.exists():
        return []
    return json.loads(p.read_text())


def save(tasks: list) -> None:
    _path().write_text(json.dumps(tasks, indent=2))


def add(title: str) -> dict:
    tasks = load()
    task = {"id": len(tasks) + 1, "title": title, "done": False}
    tasks.append(task)
    save(tasks)
    return task


def complete(task_id: int) -> bool:
    tasks = load()
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
            save(tasks)
            return True
    return False
''',
    "taskly/cli.py": '''import sys

from taskly import store


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: taskly add TITLE | list | done ID")
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "add":
        t = store.add(" ".join(rest))
        print("added #%d" % t["id"])
    elif cmd == "list":
        for t in store.load():
            print("[%s] %d %s" % ("x" if t["done"] else " ", t["id"], t["title"]))
    elif cmd == "done":
        return 0 if store.complete(int(rest[0])) else 1
    else:
        print("unknown command: " + cmd)
        return 2
    return 0
''',
    "tests/test_store.py": '''import os
import tempfile
import unittest

from taskly import store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        os.environ["TASKLY_FILE"] = self.tmp.name

    def test_add_and_complete(self):
        t = store.add("x")
        self.assertEqual(t["id"], 1)
        self.assertTrue(store.complete(1))
        self.assertTrue(store.load()[0]["done"])


if __name__ == "__main__":
    unittest.main()
''',
}


def git(*args, timeout=60):
    return run(["git", "-C", str(REPO)] + list(args), timeout=timeout)


def company_snapshot() -> dict:
    """Hash every file under .company/. The scaffold's .gitignore hides these from git."""
    root = REPO / ".company"
    return {str(p.relative_to(REPO)): sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}


def make_repo(results: dict) -> None:
    log("PHASE 4/6 throwaway repository + .company scaffold")
    if REPO.exists():
        raise Fatal(f"{REPO} already exists")
    for rel, body in SEED.items():
        write(REPO / rel, body)
    git("init", "-q")
    git("config", "user.name", "cao-validation")
    git("config", "user.email", "cao-validation@localhost")
    git("add", "-A")
    git("commit", "-q", "-m", "seed: taskly sample app")
    init = CAOKIT + ["init", str(REPO), "--name", PROJECT]
    for role, (tool, model) in ROSTER.items():
        init += ["--override", f"{role}={tool}:{model}"]
    rc, out = run(init, timeout=60, env=CAOKIT_ENV)
    write(EVID / "init-project.txt", out)
    if rc != 0:
        raise Fatal("caokit init failed: " + out)
    company = REPO / ".company" / "COMPANY.md"
    txt = company.read_text(encoding="utf-8")
    txt = txt.replace(
        "Replace this paragraph with the product or project mission for the repository.",
        "taskly helps one person track personal to-dos from the terminal with zero setup.",
    ).replace(
        "Replace this paragraph with a concise description of the repository, its users, and its major components.",
        "Python 3.9+ CLI (`taskly/cli.py`) over a JSON file store (`taskly/store.py`), "
        "with a unittest suite in `tests/`. Throwaway repository created by the CAO "
        "validation harness; no production users.",
    )
    company.write_text(txt, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "baseline: .company scaffold for TASK-0001")
    results["company_baseline"] = company_snapshot()
    rc, head = git("rev-parse", "HEAD")
    results["baseline_commit"] = head.strip()
    log(f"repo ready at {REPO} (baseline {head.strip()[:10]})")


def existing_session_guard() -> None:
    sessions = api_try("GET", "/sessions", default=[]) or []
    names = set()
    for s in sessions:
        if isinstance(s, dict):
            names.update({s.get("id"), s.get("name"), s.get("session_name")})
    if SESSION in names:
        if FORCE_REPLACE:
            log(f"FORCE_REPLACE=1: shutting down existing {SESSION}")
            run(["cao", "shutdown", "--session", SESSION], timeout=120)
            time.sleep(3)
        else:
            raise Fatal(f"A '{SESSION}' session is already running. Stop it (caokit stop) "
                        "or rerun with FORCE_REPLACE=1.")


def terminal_full(tid: str) -> dict:
    """GET /terminals/{id}: the full record (status AND caller_id; the
    /sessions/{s}/terminals list omits caller_id in CAO 2.5.x).
    """
    t = api_try("GET", "/terminals/" + tid, default={}) or {}
    return t if isinstance(t, dict) else {}


def terminal_status(tid: str) -> str:
    return str(terminal_full(tid).get("status") or "unknown").lower()


def snapshot_terminal(tid: str, profile: str) -> None:
    out = api_try("GET", f"/terminals/{tid}/output", params={"mode": "full"},
                  timeout=60, default=None)
    if isinstance(out, dict) and out.get("output"):
        write(TERM_DIR / "{}-{}.log".format(profile or "unknown", tid), out["output"])


def launch_and_watch(results: dict) -> None:
    log("PHASE 5/6 launch TASK-0001 via caokit launch")
    existing_session_guard()
    t0 = time.time()
    launch = CAOKIT + ["launch", str(REPO), "--headless", "--auto-approve",
                       "--prompt-file", str(REPO / ".company" / "prompts" / "first-run.md")]
    rc, out = run(launch, timeout=900, cwd=str(KIT), env=CAOKIT_ENV)
    write(EVID / "launch.txt", out)
    results["launch_script_rc"] = rc
    results["launch_script_seconds"] = round(time.time() - t0)
    log("launch script exit={} after {}s (a non-zero exit after ~5 min is CAO's 300s "
        "launch poll timing out; the session keeps running)".format(rc, results["launch_script_seconds"]))

    seen = {}          # tid -> record (+ first_seen/last_seen/statuses)
    timeline = open(EVID / "timeline.jsonl", "a")
    deadline = time.time() + TIMEOUT_MIN * 60
    last_change = time.time()
    last_sig = None
    nudged = False
    conductor = None
    stable_done = 0
    synth = REPO / ART["synthesis"]

    while time.time() < deadline:
        terms = api_try("GET", f"/sessions/{SESSION}/terminals", default=None)
        if terms is None:
            log(f"session {SESSION} not visible via API")
            if seen:
                break  # session went away
            time.sleep(POLL_SEC)
            continue
        if terms and conductor is None:
            conductor = terms[0]["id"]
            results["conductor_id"] = conductor
        sig_parts = []
        for t in terms:
            tid = t["id"]
            full = terminal_full(tid)
            for k, v in full.items():
                if v is not None and k != "status":
                    t.setdefault(k, v)
                    if t.get(k) is None:
                        t[k] = v
            st = str(full.get("status") or "unknown").lower()
            rec = seen.get(tid)
            if rec is None:
                rec = dict(t)
                rec["first_seen"] = now()
                rec["statuses"] = []
                seen[tid] = rec
                log("NEW terminal {} profile={} provider={} caller_id={}".format(
                    tid, t.get("agent_profile"), t.get("provider"), t.get("caller_id")))
            rec.update({k: v for k, v in t.items()})
            rec["last_seen"] = now()
            if not rec["statuses"] or rec["statuses"][-1] != st:
                rec["statuses"].append(st)
                log("  {} ({}) -> {}".format(tid, t.get("agent_profile"), st))
            timeline.write(json.dumps({"t": now(), "id": tid, "profile": t.get("agent_profile"),
                                       "provider": t.get("provider"), "status": st}) + "\n")
            snapshot_terminal(tid, t.get("agent_profile"))
            sig_parts.append(f"{tid}:{st}")
        timeline.flush()
        arts = tuple((k, (REPO / p).exists() and (REPO / p).stat().st_size) for k, p in ART.items())
        sig = (tuple(sig_parts), arts)
        if sig != last_sig:
            last_sig, last_change = sig, time.time()

        if conductor:
            inbox = api_try("GET", f"/terminals/{conductor}/inbox/messages",
                            params={"limit": 100}, default=[])
            write(EVID / "captain-inbox.json", json.dumps(inbox, indent=2))

        cstat = terminal_status(conductor) if conductor else "unknown"
        if synth.exists() and synth.stat().st_size > 0 and cstat in DONE_STATES:
            stable_done += 1
            if stable_done >= 2:
                log(f"synthesis present and captain {cstat} -> run finished")
                break
        else:
            stable_done = 0

        stalled_for = time.time() - last_change
        if AUTO_NUDGE and not nudged and stalled_for > STALL_MIN * 60:
            msg = ("Report TASK-0001 status, current workers, missing callbacks, and artifact paths. "
                   "Do not redo completed work. If both worker artifacts exist, continue with the "
                   "inspector handoff and the synthesis.")
            log(f"STALL {round(stalled_for / 60)}min with no progress -> sending ONE documented nudge (caokit send)")
            rc, out = run(CAOKIT + ["send", msg, "--repo", str(REPO)], timeout=660,
                          cwd=str(KIT), env=CAOKIT_ENV)
            write(EVID / "nudge.txt", f"rc={rc}\n{out}")
            nudged = True
            results["nudged_at"] = now()
            last_change = time.time()
        time.sleep(POLL_SEC)
    else:
        log(f"TIMEOUT after {TIMEOUT_MIN} min")
        results["timed_out"] = True

    timeline.close()
    results["nudged"] = nudged
    results["elapsed_minutes"] = round((time.time() - t0) / 60, 1)
    results["terminals"] = seen
    # Inbox of every terminal (captures captain->worker steering too).
    allbox = {}
    for tid in seen:
        allbox[tid] = api_try("GET", f"/terminals/{tid}/inbox/messages",
                              params={"limit": 100}, default=[])
    write(EVID / "all-inboxes.json", json.dumps(allbox, indent=2))
    write(EVID / "terminals.json", json.dumps(seen, indent=2, default=str))
    rc, out = run(["tmux", "list-windows", "-t", SESSION, "-F",
                   "#{window_index} #{window_name} #{pane_current_command}"], timeout=15)
    write(EVID / "tmux-windows.txt", out)
    rc, out = run(["cao", "session", "status", SESSION, "--workers"], timeout=60)
    write(EVID / "cao-session-status.txt", out)


# --------------------------------------------------------------------------- verdict
def evaluate(results: dict) -> list:
    log("PHASE 6/6 evidence + acceptance checks")
    seen = results.get("terminals", {}) or {}
    cid = results.get("conductor_id")
    by_profile = {}
    for _tid, r in seen.items():
        by_profile.setdefault(r.get("agent_profile"), []).append(r)

    inbox = []
    p = EVID / "captain-inbox.json"
    if p.exists():
        try:
            inbox = json.loads(p.read_text()) or []
        except Exception:
            inbox = []
    senders = {m.get("sender_id") for m in inbox if isinstance(m, dict)}

    # Git: what changed since baseline?
    _, porcelain = git("status", "--porcelain", "--untracked-files=all", "--ignored")
    write(EVID / "git-status.txt", porcelain)
    changed = []
    for line in porcelain.splitlines():
        if len(line) > 3:
            path = line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            changed.append(path)
    _, diffstat = git("diff", "--stat", results.get("baseline_commit", "HEAD"))
    write(EVID / "git-diff-stat.txt", diffstat)
    _, log_out = git("log", "--oneline", "--all")
    write(EVID / "git-log.txt", log_out)
    outside = [c for c in changed if not c.startswith(".company/")
               and "__pycache__/" not in c and not c.endswith(".pyc")]
    base = results.get("company_baseline") or {}
    now_files = company_snapshot()
    extra_company = [p for p, h in now_files.items()
                     if p not in ALLOWED_WRITES and base.get(p) != h]
    results["git_changed"] = changed
    results["git_commits_after_run"] = log_out.strip().splitlines()

    # Artifacts.
    art_info = {}
    adir = EVID / "artifacts"
    for k, rel in ART.items():
        f = REPO / rel
        if f.exists():
            body = f.read_text(encoding="utf-8", errors="replace")
            art_info[k] = {"path": str(f), "bytes": f.stat().st_size, "sha256": sha256(f),
                           "headings": [ln for ln in body.splitlines() if ln.startswith("#")][:25]}
            write(adir / Path(rel).name, body)
        else:
            art_info[k] = None
    results["artifacts"] = art_info

    def one(profile):
        lst = by_profile.get(profile) or []
        return lst[0] if lst else None

    def ok(b):
        return "PASS" if b else "FAIL"

    checks = []
    cap = seen.get(cid) if cid else None
    checks.append(("Active CAO session shows a Claude General",
                   ok(cap is not None and cap.get("agent_profile") == PROFILE["general"]
                      and cap.get("provider") == "claude_code"),
                   "conductor {} profile={} provider={}".format(
                       cid, cap and cap.get("agent_profile"), cap and cap.get("provider"))))
    for profile, prov in ((PROFILE["engineer"], "claude_code"), (PROFILE["scout"], "antigravity_cli")):
        r = one(profile)
        checks.append((f"General launches {profile} with provider {prov}",
                       ok(r is not None and r.get("provider") == prov and r.get("caller_id") == cid),
                       "terminal {} provider={} caller_id={} (captain={})".format(
                           r and r.get("id"), r and r.get("provider"), r and r.get("caller_id"), cid)))
    cx, ag = one(PROFILE["engineer"]), one(PROFILE["scout"])
    cb_eng = bool(cx and cx.get("id") in senders)
    cb_agy = bool(ag and ag.get("id") in senders)
    checks.append(("Both workers return callbacks to the General (CAO inbox)",
                   ok(cb_eng and cb_agy),
                   f"engineer callback={cb_eng} agy callback={cb_agy} ({len(inbox)} inbox msgs)"))
    wa = art_info.get("engineer"), art_info.get("agy")
    checks.append(("Both worker artifacts exist and are non-empty",
                   ok(all(a and a["bytes"] > 0 for a in wa)),
                   "engineer={}B agy={}B".format(wa[0] and wa[0]["bytes"], wa[1] and wa[1]["bytes"])))
    checks.append(("No application-source file is modified",
                   ok(not outside and len(results["git_commits_after_run"]) == 2),
                   "outside .company: {} ; commits now: {}".format(
                       outside or "none", len(results["git_commits_after_run"]))))
    rv = one(PROFILE["inspector"])
    checks.append(("inspector (antigravity_cli) produces the review artifact",
                   ok(bool(art_info.get("review")) and rv is not None
                      and rv.get("provider") == "antigravity_cli"),
                   "reviewer terminal {} provider={} caller_id={} review={}B".format(
                       rv and rv.get("id"), rv and rv.get("provider"), rv and rv.get("caller_id"),
                       art_info.get("review") and art_info["review"]["bytes"])))
    checks.append(("General produces the synthesis artifact",
                   ok(bool(art_info.get("synthesis") and art_info["synthesis"]["bytes"] > 0)),
                   str(art_info.get("synthesis") and art_info["synthesis"]["bytes"]) + "B"))
    unc = ""
    if art_info.get("synthesis"):
        body = (REPO / ART["synthesis"]).read_text(errors="replace")
        hits = re.findall(r"(?i)(NOT VERIFIED|unknown|uncertain\w*|unverified|assumption)", body)
        unc = f"{len(hits)} uncertainty markers"
    checks.append(("Synthesis records unresolved uncertainty (heuristic - read it)",
                   "MANUAL" if unc else "FAIL", unc or "no synthesis"))
    # Extra guardrail checks (not in TASK-0001 but matter before real work).
    checks.append(("[extra] .company writes stay inside TASK-0001 allowed list",
                   "PASS" if not extra_company else "WARN",
                   ", ".join(extra_company) or "only allowed paths"))
    dup = {p: len(v) for p, v in by_profile.items() if p != PROFILE["general"] and len(v) > 1}
    checks.append(("[extra] No duplicate workers spawned", "PASS" if not dup else "WARN", str(dup or "none")))
    unexpected = [p for p in by_profile if p not in EXPECTED]
    checks.append(("[extra] No unexpected agent profiles spawned",
                   "PASS" if not unexpected else "WARN", str(unexpected or "none")))
    denied = []
    for f in sorted(TERM_DIR.glob("*.log")):
        body = f.read_text(errors="replace")
        if re.search(r"requires approval, but approval policy is never", body):
            denied.append(f.name)
    checks.append(("[extra] No MCP/tool call denied by an approval policy",
                   "PASS" if not denied else "FAIL",
                   ", ".join(denied) or "none found in transcripts"))
    checks.append(("[extra] Completed without a human/harness nudge",
                   "PASS" if not results.get("nudged") else "WARN",
                   "nudged at {}".format(results.get("nudged_at")) if results.get("nudged") else "no nudge"))
    return checks


def report(results: dict, checks: list, fatal: str = "") -> None:
    hard = [c for c in checks if not c[0].startswith("[extra]") and c[1] == "FAIL"]
    verdict = "FAIL" if (fatal or hard or not checks) else "PASS"
    results["verdict"] = verdict
    results["checks"] = [{"check": c[0], "result": c[1], "evidence": c[2]} for c in checks]
    if fatal:
        results["fatal"] = fatal
    write(EVID / "summary.json", json.dumps(results, indent=2, default=str))

    L = [f"# CAO two-provider validation — {verdict}", "",
         f"- Run: `{RUN_DIR}`", "- Started: {}  Elapsed: {} min".format(TS, results.get("elapsed_minutes")),
         "- CAO API: {}  backend: {}".format(API, results.get("terminal_backend")),
         "- Versions: {}".format(json.dumps(results.get("versions", {}))),
         "- scout model: `{}` (listed by `agy models`: {})".format(
             results.get("agy_model_configured"), results.get("agy_model_listed")),
         "- inspector model: `{}`".format(results.get("agy_review_model_configured")), ""]
    if fatal:
        L += ["## Aborted", "", "```", fatal, "```", ""]
    if checks:
        L += ["## Acceptance checks", "", "| Check | Result | Evidence |", "|---|---|---|"]
        L += ["| {} | **{}** | {} |".format(c[0], c[1], str(c[2]).replace("|", "\\|")) for c in checks]
        L.append("")
    seen = results.get("terminals") or {}
    if seen:
        L += ["## Terminals observed", "", "| ID | Profile | Provider | caller_id | First seen | Last seen | Status path |",
              "|---|---|---|---|---|---|---|"]
        for tid, r in seen.items():
            L.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                tid, r.get("agent_profile"), r.get("provider"), r.get("caller_id") or "-",
                r.get("first_seen"), r.get("last_seen"), " → ".join(r.get("statuses", []))))
        L.append("")
    arts = results.get("artifacts") or {}
    if arts:
        L += ["## Artifacts", ""]
        for k, a in arts.items():
            L.append("- **{}**: {}".format(k, "MISSING" if not a else "{} ({} B, sha256 {})".format(
                a["path"], a["bytes"], a["sha256"][:16])))
        L.append("")
    L += ["## Evidence files", "", "All under `evidence/`: summary.json, harness.log, timeline.jsonl, "
          "terminals.json, captain-inbox.json, all-inboxes.json, terminals/*.log (full transcripts), "
          "artifacts/*, git-status.txt, git-diff-stat.txt, git-log.txt, preflight.txt, agy-models.txt, "
          "installed-profiles.json, health.json, launch.txt, cao-session-status.txt, tmux-windows.txt."]
    write(EVID / "ACCEPTANCE.md", "\n".join(L) + "\n")
    log("VERDICT: {}  ->  {}".format(verdict, EVID / "ACCEPTANCE.md"))
    for c in checks:
        log(f"  [{c[1]:<6}] {c[0]} :: {c[2]}")


def cleanup(results: dict) -> None:
    if not KEEP_SESSION and results.get("conductor_id"):
        log(f"shutting down session {SESSION} (KEEP_SESSION=1 to keep it)")
        run(["cao", "shutdown", "--session", SESSION], timeout=120)
    if _server_proc is not None:
        if KEEP_SESSION:
            log(f"leaving harness-started cao-server running (pid {_server_proc.pid})")
        else:
            log("stopping harness-started cao-server")
            try:
                os.killpg(_server_proc.pid, signal.SIGTERM)
                _server_proc.wait(timeout=20)
            except Exception:
                pass


def main() -> int:
    global _log_fh
    EVID.mkdir(parents=True, exist_ok=True)
    TERM_DIR.mkdir(parents=True, exist_ok=True)
    _log_fh = open(EVID / "harness.log", "a")
    log(f"CAO validation harness  kit={KIT}  run={RUN_DIR}")
    results = {"started": TS, "kit": str(KIT), "repo": str(REPO), "api": API}
    checks, fatal = [], ""
    try:
        preflight(results)
        ensure_server(results)
        make_repo(results)
        install_profiles(results)
        launch_and_watch(results)
        checks = evaluate(results)
    except Fatal as e:
        fatal = str(e)
        log("FATAL: " + fatal)
        if REPO.exists() and results.get("conductor_id"):
            try:
                checks = evaluate(results)
            except Exception as ee:  # pragma: no cover
                log(f"evaluate after fatal failed: {ee}")
    except KeyboardInterrupt:
        fatal = "interrupted by user"
        log("interrupted; collecting what exists")
        if REPO.exists():
            with contextlib.suppress(Exception):
                checks = evaluate(results)
    finally:
        rc, out = run([sys.executable, str(KIT / "scripts" / "token_usage.py"), str(REPO),
                       "--json", str(EVID / "token-usage.json")], timeout=60)
        write(EVID / "token-usage.md", out)
        log("token usage -> evidence/token-usage.md" if rc == 0 else "token usage unavailable")
        try:
            report(results, checks, fatal)
        finally:
            cleanup(results)
    return 0 if results.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
