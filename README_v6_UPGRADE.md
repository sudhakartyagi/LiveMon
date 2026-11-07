# Classroom Agent v6.1 — Six-Parameter Assessment + Hindi + Learning Loop

Upgrade shipped on top of v5.7 (MathGuard + permission-first actions).
**No database migration, no new tables, no new pip dependencies** — this is a
drop-in code upgrade. Your live database (revision 0005, 13 tables) is used
as-is.

**Verified before shipping:** 64 unit tests pass (30 new assessment tests +
34 regression), and a 33-check end-to-end suite drives the real HTTP API on
SQLite (your pilot mode): Hindi math error → propose → deny → learned
suppression, abuse EN+HI, wellbeing, motivation, discipline pattern, roster,
learning prompt, digest, pause gate — **33/33 passed**.

> v6.1 supersedes the earlier v6.0 package, which had two SQLite defects
> (see CHANGELOG below). If you downloaded v6.0, replace it with v6.1.

---

## WHAT IT NOW ASSESSES (the six parameters)

| # | Parameter | Detector | Signal source | Event / Tier |
|---|-----------|----------|---------------|--------------|
| 1 | Teacher teaching wrong | MathGuard (deterministic, now Hindi-aware) | spoken math claims, EN + HI + Hinglish | `factual_correction` tier 3 (proposed) |
| 2 | Class not in discipline | discipline.py rolling window | sustained noise (>=68 dB in 3 of last 5 readings) + repeated teacher discipline phrases | `discipline_watch` tier 2 (whole-class, cooldown 3 min); `discipline_pattern` tier 1 log |
| 3 | Individual / common mistakes | mistakes.py | same topic repeated 3x in 15 min = CLASS gap; roster alias + wrong-answer context = individual (silent log) | `common_mistake` tier 2 (proposed); `individual_mistake` tier 1 (never spoken, no naming) |
| 4 | Abusive language | abuse.py bilingual lexicon | demeaning words vs threats (two severities, school-extendable) | `language_nudge` tier 2 (proposed); `conduct_alert` tier 4 (principal digest) |
| 5 | Emotional issue | wellbeing.py | distress cues in teacher speech ("is crying", "रो रहा", "डर") | `wellbeing_alert` tier 3 (proposed, private check-in) |
| 5b | Injury / self-harm | wellbeing.py | explicit cues only ("bleeding", "खून", "hurt himself") | `wellbeing_escalation` tier 4 (principal, agent never speaks) |
| 6 | Needs motivation | wellbeing.py | giving-up cues ("can't do it", "mujhse nahin ho raha") + mistake streaks | `encouragement` tier 2 (whole-class, non-naming) |

Safety invariants preserved from v5.7: Propose -> Permission -> Act -> Log.
Tier 3+ is never spoken without teacher approval; tier 4 goes to the principal
digest; discipline/mistake attribution NEVER names a child aloud (DPDP).

## HINDI + MULTILINGUAL

* `app/assessment/multilingual.py` converts Devanagari AND romanised Hindi
  math vocabulary to MathGuard tokens before verification:
  "दो जमा दो बराबर पाँच" -> "two plus two is equal to five" -> ERROR.
  Fractions ("आधा/तिहाई/चौथाई"), comparisons ("से बड़ा/से छोटा"), and Hindi
  word order ("90 का आधा") are handled. English passes through untouched.
* Whisper runs with language=auto and reports the detected language of every
  utterance (`lang: hi/en/...` in the payload + console "🗣 hi").
* Future languages: append word tables in `multilingual.py` (or supply them
  via policy config) — no pipeline changes anywhere else.
* Default hotwords are bilingual (EN + HI), and `/learning/prompt` evolves
  them automatically (below).

## THE LEARNING LOOP ("keeps learning from classroom experience")

1. **Hotword growth** — `GET /learning/prompt` returns an evolved Whisper
   hotword string: base bilingual math vocabulary + your roster aliases +
   tokens recovered from corrections you DENIED/FLAGGED (those were
   mishearings). `mic_listener.py` fetches it at every startup.
2. **Correction suppression** — when you DENY a proposed factual correction,
   that exact claim is remembered (policy config JSONB). The same claim is
   later logged tier-1 ("Learned: you rejected this correction before") and
   never re-proposed. Wrong-interruptions die with use.
3. **Six-parameter digest** — `GET /learning/digest?date=YYYY-MM-DD` returns
   per-parameter counts (all six), top mistake topics, and approval rate.

## SETUP

```powershell
cd D:\WIP\DreaPro\classroom_copilot_v6.1\classroom_copilot_v5
setx DATABASE_URL "sqlite:///D:/WIP/DreaPro/classroom_copilot_v6.1/classroom_copilot_v5/classroom_copilot.db"   # once; open NEW window after
python -m uvicorn app.main:app --port 8000        # terminal 1
python .\mic_listener.py                          # terminal 2
python -m pytest tests/test_assessment.py -q      # 30 new tests, no DB needed
```

**Upgrading your EXISTING live v5.7 folder in place** (keeps your DB, config,
migrations): copy over from this package —

```
app\                      (whole folder — assessment/, learning.py, audio.py,
                           main.py, brain.py, db.py are the v6 core)
mic_listener.py
tests\test_assessment.py
pyproject.toml            (version only — optional)
```

Do NOT copy `alembic\` over your live folder — your live migrations are
already patched and applied at 0005. Then restart uvicorn and the listener.
First start will print `📚 Learning loop: N evolved hotwords loaded`.

Register the class roster once per class (enables parameter 3):

```
POST /roster  {"roster": {"rahul": "<student-uuid>", "aarti": "<student-uuid>"}}
```

Extend lexicons per school without code changes (policy config JSONB):

```json
{
  "abuse_extra": {"severe": [], "moderate": ["absurd"]},
  "wellbeing_extra": {"distress": [], "selfharm": [], "motivation": []}
}
```

## HONEST LIMITS (single-teacher-mic reality)

* Individual students are heard only when the teacher speaks to/about them.
  Per-child voice emotion or noise attribution needs classroom microphones
  (Phase-2 hardware) — the engine is built so those detectors plug in
  without changing the event schema.
* Discipline state is in-process (pilot = one uvicorn worker). Multi-worker
  deployment: move discipline._STATE to Redis (one documented swap).
* Lexicon detectors are word-boundary exact — conservative by design;
  schools extend them, the agent never invents severity.
* SQLite has no vector search — curriculum RAG activates when you move to
  PostgreSQL (deployment path); on SQLite the conservative fallback answers
  without curriculum context (silently, no error spam).

## FILES (v6.1)

NEW:      app/assessment/{__init__,multilingual,lexicons,abuse,wellbeing,
          discipline,mistakes}.py, app/learning.py, tests/test_assessment.py
MODIFIED: app/audio.py (assessment orchestrator + policy config),
          app/main.py (v6 title, /roster, /learning/prompt, /learning/digest,
          deny->suppress), app/db.py (dialect-aware tenant session),
          app/brain.py (RAG skipped on SQLite, no error spam),
          mic_listener.py (bilingual + evolved hotwords, language detection,
          MKL recovery, ~30 s utterance cap),
          alembic/versions/0001..0005 (dialect-aware via patch_migration.py)
ADDED:    patch_migration.py (re-runnable; makes migrations safe on SQLite),
          CHANGELOG_v6.1.md
UNTOUCHED: mathguard.py, engine.py, models.py, auth.py, schemas.py, ui/
