# CHANGELOG — v5.7.0 (finished-product upgrade)

Date: Nov 2026
Baseline: v5.6.0 (zip `classroom_copilot_v5.zip`) — 18/18 tests green on
PostgreSQL 15 + pgvector, RLS enforced.

## Why

Live pilot (8 utterances) showed the bottleneck had moved from HEARING to
UNDERSTANDING:

| Teacher said | Old behaviour | Why |
|---|---|---|
| "2 plus 2 is 3" (deliberate error) | NO event | keyword mock didn't match |
| "2 minus 2 is not equal to 0" (false math) | NO event | same |
| "So one half is greater than three letters" (garbled) | tier-3 action FIRED | mock keyword `half/greater` |

That is exactly inverted. v5.7 fixes all three directions and adds the
permission-first layer the product context requires
(Propose -> Permission -> Act -> Log).

## 1. MathGuard (`app/mathguard.py` — NEW, ~600 lines)

Deterministic spoken-math verifier. Runs FIRST on every transcript — no LLM,
no network, no cost, microseconds.

- Grammar: `<expr> (is|equals|not equal to|greater than|less than|...) <expr>`
  with full expression evaluation (+ - * / precedence, fractions, decimals).
- Vocabulary: English number words to thousands, Hindi numerals (do, teen,
  chaar, ...), "into" = multiply, "upon/by" = divide, fraction phrases
  (one half, three fourths, two thirds...), "half of N", "double of N",
  "sum/product of A and B", "A subtracted from B", unary minus results,
  2-dp rounding tolerance for division, division-by-zero detection.
- Safety guards: comparisons require a copula ("3 less than 5" is NOT a
  claim); a claim trailed by a noun ("1/2 > 3 letters") is rejected;
  homophones (to/for/won/ate) are only mapped in a second contextual pass.
- Verdicts: `error` (with correction), `correct` (no event), `None`
  (not a claim -> falls through to the AI brain).
- Regression: `tests/test_mathguard.py`, 45-case smoke all green.

## 2. Audio pipeline (`app/audio.py` rewritten)

Order: normalize -> noise gate (75 dB, env-tunable) -> MathGuard -> AI brain
(only for non-math text) -> confidence gate.

- Math errors -> tier-3 `factual_correction` with structured
  `meta {statement, verdict, topic, detector}` + `suggestion` (the
  correction text).
- Correct math -> `math_verified` marker (reported to the listener, no event
  row).
- ASR confidence (avg log-prob) below `ASR_CONFIDENCE_FLOOR` (-0.6 default)
  downgrades tier-3 to tier-1 log-only. Misheard text can never be spoken.

## 3. AI brain (`app/brain.py`)

- Returns structured `{kind: correction|suggestion, text, source}`.
- Prompt: hints not spoon-feeding, no naming students, no behaviour talk.
- The keyword mock that fired on "half/quarter/greater" is REMOVED. The
  conservative fallback answers ONLY explicit teaching requests
  ("give an example...").
- RAG vector literal fixed to pgvector text form `[0.1,0.2,...]`.

## 4. Permission-first action layer (context requirement)

- `app/engine.py`: `PERMISSION_FIRST_ACTIONS` (recap, example,
  check_question, quiet_reminder, timer), new action defaults,
  `PolicyEngine.needs_approval()` with `DEFAULT_AUTO_APPROVE =
  ["scripted_reminder"]` and policy-config override.
- `app/main.py`:
  - `/audio/ingest` -> tier 2/3 events are `proposed` (unless pre-approved
    by policy); response carries `approval_required`, `proposal`,
    `teacher_note`, `math` metadata. Tier 0/1 logged; tier 4 escalated to
    the principal digest.
  - `POST /actions/{id}/approve` -> releases `spoken_text`, writes audit.
  - `POST /actions/{id}/deny` -> logged, never spoken, writes audit.
  - `GET /actions/pending?lesson_id=` -> the teacher's yes/no queue.
  - Double-deciding returns 409.
- `ui/app.py`: new **✅ Approvals** tab (Allow / Skip per proposal).
- Schema: migration `0005_permission_flow` adds `proposed_text`, `meta`
  (JSONB), `approved_by`, `decided_at` to `agent_actions`. RLS unchanged.
- Discipline unchanged: observe/log only, naming still gated by school
  policy + 30-day pattern escalation to the principal (v0.4.1 gates intact).

## 5. Pro listener (`mic_listener.py`)

- Sends `confidence` (avg segment log-prob) with every transcript.
- Default math hotwords bias Whisper to Class 4-5 vocabulary
  (config.json `listener.hotwords` overrides).
- Trailing silence 0.9 s -> 1.2 s: no more mid-word clipping
  ("whole tea[m]").
- Console now shows events, detected claims, proposals awaiting YES, and
  math-verified notes.
- `requirements_audio.txt` added (was referenced but missing).

## 6. Tests & tooling

- `tests/test_mathguard.py` (NEW), `tests/test_audio_processor.py` (NEW),
  `tests/test_permission_flow.py` (NEW).
- `tests/conftest.py` + `tests/test_rls.py`: superuser/app URLs are
  env-overridable (`TEST_SUPER_URL`, `DATABASE_URL`); migrations run as the
  DB owner, app runs as restricted `app_user` (RLS enforced).
- `alembic/env.py`: honours `DATABASE_URL`.
- Live E2E (uvicorn + real Postgres): 11/11 steps PASS —
  error->proposal->approve->spoken_text; deny; math_verified; garbled->no
  event; noise->pre-approved; low-confidence->silent log; dashboard trail.
- Full suite: **57 passed**.

## Upgrade steps (existing deployments)

```bash
pip install -e .          # no new runtime deps
alembic upgrade head      # applies 0005_permission_flow
pytest -v                 # expect 57 passed
```

Laptop listener:

```powershell
pip install -r requirements_audio.txt
python .\mic_listener.py
```

## Deliberately NOT changed

- No autonomous discipline, no naming children, no emotion/attention scoring.
- No raw transcript storage (DPDP: structured events only, short retention).
- Teacher remains in charge: agent speaks only after permission or
  pre-approved policy.
