# Classroom Agent v5.0 — Week 1 (Security Gate)

PostgreSQL + Row-Level Security + two-school isolation test suite.
This is the foundation. Nothing else in v5 ships until pytest -v passes 10/10.

## Prereqs
- Docker Desktop (with docker compose)
- Python 3.11+

## Run
docker compose up -d
pip install -e .
alembic upgrade head
pytest -v

Expected: 10 passed.

## What is proven
- RLS on every tenant table (ENABLE + FORCE ROW LEVEL SECURITY)
- Runtime connects as app_user (NOSUPERUSER NOBYPASSRLS)
- SET LOCAL app.current_tenant_id is pooling-safe (transaction-scoped)
- Cross-tenant SELECT returns 404 (no existence leak)
- Missing tenant context filters ALL rows (fail-safe)
- alg=none JWT rejected
- Policy presence verified in pg_policies

## What is NOT proven (Weeks 2+)
- Concurrent pooling stress test
- Cross-tenant INSERT/UPDATE WITH CHECK negative tests
- Audit log of cross-tenant attempts
- Policy editor, tier engine, agent core

## Reset
docker compose down -v   # wipes the volume so init.sql re-runs

---

# v5.7 — Voice Accuracy + MathGuard + Permission-First Actions

## What changed (finished-product upgrade, Nov 2026)

### 1. MathGuard — deterministic math verification (`app/mathguard.py`)
Every transcript is checked by a fast, offline, deterministic parser BEFORE
any LLM. Spoken claims like "2 plus 2 is 3", "2 minus 2 is not equal to 0",
"1/2 is bigger than 3/4", "do plus do is chaar" (Hinglish), "half of 10 is 5",
"seven into eight is fifty four" are verified exactly (fractions, unary minus,
division rounding tolerance, division-by-zero). Errors produce tier-3
`factual_correction` events with a ready correction; correct claims produce a
`math_verified` note and NO event; garbled text ("one half is greater than
three letters") parses to nothing — the old keyword-mock false positive is
gone. 45-case regression suite in `tests/test_mathguard.py`.

### 2. ASR confidence gating (pro listening -> pro judgment)
`mic_listener.py` now sends `confidence` (avg Whisper log-prob). Transcripts
below `ASR_CONFIDENCE_FLOOR` (default -0.6) can be LOGGED but never auto-fire
a tier-3 correction. Listener upgrades: default Class 4-5 math hotwords,
1.2 s trailing silence (no more clipped words), richer console output
(events, proposals, math verdicts). Deps: `requirements_audio.txt`.

### 3. Permission-first action layer (Propose -> Permission -> Act -> Log)
- Tier 2/3 events become `proposed` — nothing is spoken until the teacher
  allows it (`POST /actions/{id}/approve`, `POST /actions/{id}/deny`).
- `GET /actions/pending?lesson_id=` — the teacher's yes/no queue.
- Whole-class scripted noise reminders are pre-approved by default; schools
  can pre-approve more via policy config `{"auto_approve": [...]}`.
- Every decision writes an `audit_logs` row (actor, action, resource).
- Streamlit UI gains an **✅ Approvals** tab.
- Discipline remains observe/log-only; naming rules unchanged (v0.4.1 gates).

### 4. Schema & ops
- Migration `0005_permission_flow`: `agent_actions.proposed_text/meta/
  approved_by/decided_at` (no new tables; RLS unchanged).
- Raw transcripts are still NEVER stored (DPDP-friendly): only structured
  events with statement/verdict metadata.
- Tests: 57 passed (RLS, cross-tenant, discipline, math, processor, flow).
