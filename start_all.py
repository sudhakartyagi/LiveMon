"""start_all.py — v6.1 one-command launcher (SQLite mode).

Replaces start_agent.bat (the old v5.6 Docker/Postgres launcher, which never
set DATABASE_URL and left your services pointing at localhost:5432).

What this does:
  1. Sets DATABASE_URL to sqlite:///<this folder>/classroom_copilot.db —
     for THIS console AND both service windows it opens.
  2. First run: creates + migrates + seeds the DB and writes config.json
     with a fresh 8-hour token (runs alembic / seed_demo / setup_credentials).
  3. Auto-refreshes the token if it expires within 30 minutes.
  4. Launches the API (uvicorn), the microphone listener, and the Streamlit
     teacher dashboard (http://localhost:8501, when streamlit is installed)
     in their own console windows — CLOSE THOSE WINDOWS to stop everything.

Run:    python start_all.py
Flags:  --port 8000    API port; if not 8000, api_url is patched into config.json
        --no-launch    do the setup steps only, don't start the services
        --reseed       wipe the SQLite DB and demo-seed it again
        --fg           run the API in THIS console (errors visible) instead of
                       popup windows — for diagnosing startup problems
"""

import argparse
import base64
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OK, NO, INFO = "[OK]  ", "[X]   ", "[i]   "

HERE = Path(__file__).resolve().parent
DB = HERE / "classroom_copilot.db"
DB_URL = f"sqlite:///{DB.as_posix()}"
TOKEN_GRACE_SECONDS = 30 * 60  # refresh when < 30 min of token life remain


def say(*a):
    print(*a, flush=True)


def run_step(label, *cmd):
    say(f"\n--- {label} ---")
    r = subprocess.run(cmd, cwd=str(HERE))
    if r.returncode != 0:
        say(NO + f"{label} failed (exit {r.returncode}). Fix the error above, "
            "then run:  python start_all.py")
        sys.exit(r.returncode)


def token_payload(path: Path):
    try:
        tok = json.loads(path.read_text(encoding="utf-8")).get("token", "")
        part = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return None


def ensure_credentials(force: bool = False):
    cfg = HERE / "config.json"
    payload = None if force else (token_payload(cfg) if cfg.exists() else None)
    if payload is None:
        if force and cfg.exists():
            say(INFO + "Database was (re)created — regenerating credentials.")
        run_step("Credential setup (setup_credentials.py)", sys.executable,
                 "setup_credentials.py")
        payload = token_payload(cfg) or {}
    else:
        remaining = payload.get("exp", 0) - time.time()
        if remaining < TOKEN_GRACE_SECONDS:
            say(INFO + f"Token expires in {max(remaining, 0):.0f} s — refreshing.")
            run_step("Credential refresh (setup_credentials.py)", sys.executable,
                     "setup_credentials.py")
            payload = token_payload(cfg) or {}
    remaining = payload.get("exp", 0) - time.time()
    say(OK + f"Credentials valid (token expires in {remaining / 3600:.1f} h)")


def patch_api_url(port: int):
    cfg_path = HERE / "config.json"
    if port == 8000:
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["api_url"] = f"http://localhost:{port}"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        say(OK + f"config.json api_url -> {cfg['api_url']}")
    except Exception as exc:  # non-fatal: listener still defaults to 8000
        say(INFO + f"Could not patch api_url into config.json ({exc}) — "
            "the listener may target the wrong port.")


def wait_health(port: int, timeout: float = 25.0) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser(description="Classroom Copilot v6.1 launcher")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--reseed", action="store_true")
    ap.add_argument("--fg", action="store_true",
                    help="run the API in THIS console (errors visible) instead "
                         "of popup windows — for diagnosing startup problems")
    args = ap.parse_args()

    say("Classroom Copilot v6.1 — SQLite launcher\n")
    say(OK + f"DATABASE_URL = {DB_URL}")
    os.environ["DATABASE_URL"] = DB_URL

    missing = [d for d in ("app", "alembic") if not (HERE / d).is_dir()]
    if missing or not (HERE / "alembic.ini").is_file():
        say(NO + "Run this from the project folder that contains app/, "
            "alembic/ and alembic.ini.")
        say(INFO + f"Current folder: {HERE}"
            + (f"  (missing: {', '.join(missing)})" if missing else
               "  (alembic.ini missing)"))
        sys.exit(1)

    fresh_db = False
    if args.reseed and DB.exists():
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB) + suffix)
            if p.exists():
                p.unlink()
        say(OK + "Old database deleted (--reseed).")
        fresh_db = True

    if not DB.exists():
        # Preflight: the project's own alembic/ migrations folder SHADOWS the
        # real alembic package when it is not installed, and python then
        # dies with "'alembic' is a package and cannot be directly executed".
        pre = subprocess.run([sys.executable, "-m", "alembic", "--help"],
                             cwd=str(HERE), capture_output=True, text=True)
        if pre.returncode != 0:
            reason = (pre.stderr.strip() or pre.stdout.strip() or
                      "unknown error").splitlines()[-1]
            say(NO + f"alembic is not usable with this Python: {reason}")
            say(INFO + "Fix:  pip install alembic   (then run this again)")
            sys.exit(1)
        run_step("Create schema (alembic upgrade head)", sys.executable,
                 "-m", "alembic", "upgrade", "head")
        run_step("Seed demo data (seed_demo.py)", sys.executable, "seed_demo.py")
        fresh_db = True
    else:
        say(OK + f"Database ready: {DB.name}")

    ensure_credentials(force=fresh_db)
    patch_api_url(args.port)

    if args.no_launch:
        say("\n" + OK + "Setup complete (--no-launch). Start services later with:  "
            "python start_all.py")
        return

    if port_in_use(args.port):
        say(NO + f"Port {args.port} is already in use — an old API window (or "
            "another program) owns it. Close it, or pick another:  "
            "python start_all.py --port 8001")
        sys.exit(1)

    if args.fg:
        say(INFO + "Foreground mode — the API runs in THIS console so you can "
            "see any error. Ctrl+C to stop. The mic listener is NOT started.\n")
        try:
            subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app",
                            "--port", str(args.port)], cwd=str(HERE), env=os.environ)
        except KeyboardInterrupt:
            pass
        return

    # Direct python spawn — no `cmd /c` wrapper (its re-quoting silently
    # garbles the command line; windows would flash and die instantly).
    flags = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if os.name == "nt" else {}
    api_cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.port)]
    mic_cmd = [sys.executable, "mic_listener.py"]

    mic = None
    api = subprocess.Popen(api_cmd, cwd=str(HERE), env=os.environ, **flags)
    if os.name == "nt":
        mic = subprocess.Popen(mic_cmd, cwd=str(HERE), env=os.environ, **flags)
        say(OK + f"API window started        (PID {api.pid}, port {args.port})")
        say(OK + f"Microphone window started (PID {mic.pid})")
        say(INFO + "Each window's title bar shows its python command line — that "
            "is how you tell them apart.")
    else:
        say(OK + f"API started (PID {api.pid}, port {args.port}); mic listener is "
            "start separately on this platform:  python mic_listener.py")
    say(INFO + "First mic run downloads the Whisper model once (~475 MB) — "
        "the Microphone window may stay quiet for a while.")

    if wait_health(args.port):
        say(OK + f"API is up:  http://localhost:{args.port}/health")
    else:
        say(NO + "API did not answer within 25 s. Diagnose with:")
        say("      python start_all.py --fg        <- runs the API here, error visible")
        say(INFO + "(each popup window closes the moment its command fails — "
            "the error text only shows in --fg mode)")
        sys.exit(1)

    # Teacher dashboard (Streamlit) — auto-opens the browser in its window.
    ui = None
    if importlib.util.find_spec("streamlit") is None:
        say(INFO + "Teacher dashboard skipped — streamlit not installed. "
            "Install once with:  pip install streamlit")
    elif port_in_use(8501):
        say(OK + "Teacher dashboard already running:  http://localhost:8501")
    else:
        ui_cmd = [sys.executable, "-m", "streamlit", "run", "ui/app.py",
                  "--server.port=8501", "--server.headless=false",
                  "--browser.gatherUsageStats=false"]
        ui = subprocess.Popen(ui_cmd, cwd=str(HERE), env=os.environ, **flags)
        say(OK + f"Dashboard window started  (PID {ui.pid})")
        say(INFO + "Dashboard:  http://localhost:8501  (token / class / lesson "
            "prefilled from config.json)")

    stop = "taskkill /PID " + str(api.pid) + " /T"
    if mic:
        stop += f"  &&  taskkill /PID {mic.pid} /T"
    if ui:
        stop += f"  &&  taskkill /PID {ui.pid} /T"
    say("\nAll services launched on SQLite! Close the popup windows to stop "
        "them, or:  " + stop)
    say(INFO + "Note: start_agent.bat (v5.6) starts Postgres — do NOT use it "
        "for this SQLite setup.")


if __name__ == "__main__":
    main()
