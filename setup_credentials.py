"""setup_credentials.py — ONE command credential setup (v6.2, never fails silently).

What it does:
  1. Verifies DATABASE_URL points to a SQLite file (else prints exact fix).
  2. Reads school / teacher / latest class / latest lesson from that DB.
  3. Issues a fresh 8-hour JWT (same secret as the backend).
  4. Writes config.json (backs up any existing one to config.json.bak).
  5. ALWAYS prints the token — even if the app.auth import fails, it falls
     back to a zero-dependency HMAC-SHA256 JWT (identical output to PyJWT).

Run:  python setup_credentials.py
(after  $env:DATABASE_URL = "sqlite:///D:/WIP/.../classroom_copilot.db")
Tip:  python -u setup_credentials.py   <- if output looks truncated
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import base64
import hashlib
import hmac
import urllib.parse

OK = "[OK]  "
NO = "[X]   "
INFO = "[i]   "


def say(*args):
    print(*args, flush=True)


# --------------------------------------------------------------------------
# 0. Fallback JWT issuer — pure stdlib, byte-compatible with PyJWT HS256
# --------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_token_stdlib(sub: str, school_id: str, role: str,
                       secret: str, hours: int = 8) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": sub,
        "school_id": school_id,
        "role": role,
        "exp": int(time.time()) + hours * 3600,
    }).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


# --------------------------------------------------------------------------
# 1. Resolve the SQLite file path from DATABASE_URL
# --------------------------------------------------------------------------
url = os.getenv("DATABASE_URL", "")
say("Classroom Copilot — credential setup (v6.2)\n")

if not url:
    say(NO + "DATABASE_URL is not set in THIS PowerShell window.")
    say(INFO + "Env vars are per-window — set it and run the script in the SAME window:")
    say('      $env:DATABASE_URL = "sqlite:///D:/WIP/DreaPro/'
        'classroom_copilot_v6.1/classroom_copilot.db"')
    say("      python setup_credentials.py")
    sys.exit(1)

if not url.startswith("sqlite:///"):
    say(NO + f"DATABASE_URL does not point to SQLite:\n      {url}")
    say(INFO + "That is why get_token.py hung — the fallback URL is "
        "PostgreSQL, and nothing listens on localhost:5432.")
    say(INFO + "Fix it for this window:")
    say('      $env:DATABASE_URL = "sqlite:///D:/WIP/DreaPro/'
        'classroom_copilot_v6.1/classroom_copilot.db"')
    sys.exit(1)

db_path = urllib.parse.unquote(url[len("sqlite:///"):])
if not os.path.exists(db_path):
    say(NO + f"SQLite file not found: {db_path}")
    say(INFO + "Create+migrate it once, in the project folder:")
    say("      python -m alembic upgrade head")
    say("      python seed_demo.py")
    sys.exit(1)
say(OK + f"Database: {db_path}")

# --------------------------------------------------------------------------
# 2. Read the classroom rows (10 s busy timeout — no infinite waits)
# --------------------------------------------------------------------------
try:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"schools", "teachers", "classes", "lessons"} <= tables:
        say(NO + "Database exists but tables are missing (alembic not run).")
        say(INFO + "Fix:  python -m alembic upgrade head")
        sys.exit(1)
    school = con.execute(
        "SELECT id FROM schools ORDER BY created_at LIMIT 1").fetchone()
    if not school:
        say(NO + "No school row found. Run:  python seed_demo.py  first.")
        sys.exit(1)
    sid = school["id"]
    teacher = con.execute(
        "SELECT id FROM teachers WHERE school_id = ? LIMIT 1",
        (sid,)).fetchone()
    cls = con.execute(
        "SELECT id FROM classes WHERE school_id = ? LIMIT 1",
        (sid,)).fetchone()
    lesson = con.execute(
        "SELECT id FROM lessons WHERE school_id = ? "
        "ORDER BY started_at DESC LIMIT 1", (sid,)).fetchone()
    con.close()
except sqlite3.Error as exc:
    say(NO + f"SQLite error: {exc}")
    say(INFO + "If this mentions a missing column, run:  python -m alembic upgrade head")
    sys.exit(1)

if not (teacher and cls and lesson):
    say(NO + "Missing teacher/class/lesson rows — run:  python seed_demo.py")
    sys.exit(1)

# --------------------------------------------------------------------------
# 3. Issue the token — prefer app.auth, fall back to stdlib HMAC JWT
# --------------------------------------------------------------------------
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

jwt_secret = os.getenv("JWT_SECRET") or "dev-only-secret-do-not-use-in-prod"
token = None

try:
    from app.auth import issue_token                 # noqa: E402
    token = issue_token(sid, teacher["id"], "teacher")
    say(OK + "Token signed via app.auth (backend parity)")
except ModuleNotFoundError as exc:
    missing = getattr(exc, "name", "?")
    if missing == "app":
        say(INFO + "app/ package not found next to this script — "
            "keep setup_credentials.py inside the project folder.")
    elif missing == "jwt":
        say(INFO + "PyJWT not installed — using built-in fallback signer instead. "
            "Optional fix:  pip install pyjwt")
    else:
        say(INFO + f"Import failed ({exc}) — using built-in fallback signer.")
except Exception as exc:                              # noqa: BLE001
    say(INFO + f"app.auth raised ({exc}) — using built-in fallback signer.")

if token is None:
    token = issue_token_stdlib(teacher["id"], sid, "teacher", jwt_secret)
    say(OK + "Token signed with stdlib HMAC-SHA256 "
        "(same secret + algorithm as the backend)")

# --------------------------------------------------------------------------
# 4. Write config.json (backup first)
# --------------------------------------------------------------------------
cfg_path = os.path.join(here, "config.json")
if os.path.exists(cfg_path):
    shutil.copy2(cfg_path, cfg_path + ".bak")
    say(OK + "Old config.json backed up -> config.json.bak")

cfg = {"token": token, "class_id": cls["id"], "lesson_id": lesson["id"]}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
say(OK + f"Saved -> {cfg_path}")

# --------------------------------------------------------------------------
# 5. Show everything
# --------------------------------------------------------------------------
say("\n================ YOUR CREDENTIALS ================")
say(f"CLASS_ID : {cls['id']}")
say(f"LESSON_ID: {lesson['id']}")
say(f"TOKEN    : {token}")
say("==================================================")
say(OK + "Done. Now start the stack:")
say("      Terminal 1:  python -m uvicorn app.main:app --port 8000")
say("      Terminal 2:  python .\\mic_listener.py")
say(INFO + "Token expires in 8 h — rerun this script to refresh.")
