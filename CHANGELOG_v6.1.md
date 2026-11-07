# CHANGELOG — v6.1 (2026-11-03)

## v6.1.3 — "still poor transcript" fix: 10-s chunks + floor auto-boost + repetition guard (2026-11-04)

Pilot log after v6.1.2: listener runs and ASR is now FASTER than real time
(15.1 s ASR for a 30 s utterance — the v6.1.1 speed fix worked), but the
text was still garbage: "ब्रम्ःपूद्द्दा ब्रम्ःपूद्द्दा ब्रम्ःपूद्द्दा बेलिएश
आसान एज़ मबाद", ⏱ utterance 30.0s, 🎯 conf -0.59, 🗣 en (while speaking
Hindi), and the 👂 heartbeat showed mic peak pinned at -29..-31 dBFS
against a floor of -66..-68 dBFS for 90+ seconds.

### Root-cause chain
1. A steady sound source (fan / AC / projector hum / laptop mic
   self-noise) started after the 2 s calibration: mic peak -31 dBFS vs.
   stale floor -66 dBFS. Every frame sat ~29 dB above the floor → the
   gate NEVER closed on its 1.2 s silence rule → the ONLY thing closing
   an utterance was the 30 s hard cap (⏱ utterance 30.0s exactly).
2. Whisper then received one 30 s mostly-noise blob → language
   auto-detect said 'en' for Hindi audio → decoded Devanagari garbage →
   repetition loop (no repetition penalty was set, and the compression
   filter only drops ratio > 2.4, so a 3x repeat slipped through).

### Changed (mic_listener.py)
1. **Floor auto-boost**: the effective noise floor rises toward the quiet
   end (10th percentile) of the last ~3 s of audio, kept 3 dB below it
   (clamp 50 dB). A steady hum stops counting as speech within ~3 s and
   the gate closes again; real speech keeps the gate open (inter-word
   energy dips sit far below word peaks, so p10 stays low). Self-heals
   when the noise source stops: the boost decays as the window refills
   with quiet frames.
2. **Utterance cap 30 s -> 10 s** (`listener.max_utt_s`, 3-60): transcript
   latency drops from ~45 s (30 s wait + 15 s ASR) to a few seconds, and
   short chunks transcribe dramatically better. One-time hint after 3
   cap-splits ("Teacher speaks in long stretches…").
3. **temperature [0.0]** only — the hidden 0.2 fallback retry doubled ASR
   time on hard audio without improving the text.
4. **repetition_penalty 1.15** kills "ब्रम्ः ब्रम्ः ब्रम्ः" style loops; on
   faster-whisper < 1.0 (no such kwarg) it is auto-detected via TypeError
   and skipped with a printed note (upgrade hint included).
5. **Repetition-loop detector**: when a transcript has one word 3+ times
   in a row, a one-time hint prints: pin "language": "hi" (or "en") in
   config.json + run --save-audio.
6. **`--save-audio [dir]`** (default saved_audio/): every captured
   utterance is written as 16 kHz mono WAV before ASR — the teacher can
   HEAR exactly what Whisper hears and separate mic/room problems
   (muffled WAV) from model/settings problems (clean WAV, bad text).
7. Banner mentions the 10 s max chunk; session summary counts 10 s-splits.

### Verification
- 40-check listener suite: everything from v6.1.2 plus new checks —
  floor-boost wedge recovery (fan starting after calibration closes the
  gate in < 6 s, no further false opens, real speech still opens it),
  12 s continuous speech cap-split at ~10 s with the capped flag,
  max_utt_s override, repetition_penalty/temperature kwargs,
  TypeError fallback on an old-faster-whisper fake, degenerate-text
  hint, and a WAV save round-trip.

---


## v6.1.2 — "Deaf listener" fix + dashboard auto-launch (2026-11-03)

Pilot report: listener starts, calibrates (floor -57 dBFS), then never
transcribes anything; the teacher dashboard page never opens.

### Root cause (listener)
Calibration proves audio IS flowing — the speech GATE was the problem. The
gate opened only when frames exceeded floor + 8 dB, but a teacher 1-2 m from
a laptop mic often peaks just 7-9 dB over room tone (the pilot's own earlier
session measured ~8-9 dB). A slightly quieter mic/room -> the gate never
opens -> total silence, no errors.

### Fixed / changed (mic_listener.py)
1. **Speech gate relaxed: start_margin_db 8 -> 6, continue_margin_db 4 -> 3**
   (config-overridable: `listener.start_margin_db`, `continue_margin_db`).
2. **👂 30 s heartbeat** (listener.heartbeat_s, 0 = off): prints floor, gate,
   mic peak since last beat and utterance count — the console is never a
   silent void, and it says exactly what to fix when the peak never
   reaches the gate.
3. **No-audio stall warning**: if NO audio block arrives for 5 s (device
   muted/unplugged/default changed), the listener says so explicitly and
   points to the new meter.
4. **`--meter` diagnostic mode**: live 0.5 s bar meter of mic level vs. gate
   (no Whisper needed, same capture settings). Ends with a printed diagnosis
   guide (wrong device / too quiet / listener bug).

### Fixed (launcher + UI)
5. **start_all.py now launches the teacher dashboard** (Streamlit,
   ui/app.py) as a third window and opens the browser at
   http://localhost:8501. Previously NOTHING served the web page — that is
   why it "did not open". Skips with a hint if streamlit is not installed
   (`pip install streamlit`), reuses an already-running instance.
6. **ui/app.py prefills from config.json**: token, class_id, lesson_id and
   api_url are read automatically — the teacher pastes nothing (old file had
   hardcoded demo IDs and demanded a pasted token).

### Verification
- 27-check listener suite (block splitting 16k/48k, gate overrides,
  heartbeat + stall warnings, fake-Whisper end-to-end, compile).
- start_all 6-test suite re-run: fresh launch, health, idempotent rerun,
  token refresh, reseed, --fg, port-busy guard.

---


## v6.1.1 — Audio capture & CPU tuning (2026-11-03)

Fixes the two pilot complaints: "⚠️ audio status: input overflow" during
capture and 25.1 s ASR for a 6.4 s utterance (conf -0.56). Root cause chain:
Whisper decoded with beam 5 on every core -> the mic callback starved ->
PortAudio dropped samples -> garbled words -> temperature fallback retried ->
even more CPU. One loop, two symptoms.

### Changed (mic_listener.py)
1. **beam_size default 5 -> 1** (greedy). Typically 2-4x faster on CPU;
   near-identical text for short classroom utterances. Config:
   `listener.beam_size` (raise to 3-5 only on fast CPUs).
2. **cpu_threads auto-reservation.** WhisperModel now gets
   `cpu_threads = max(1, min(4, cores - 2))`, leaving cores for capture +
   assembler, so the mic no longer overflows exactly while Whisper runs.
   Config: `listener.cpu_threads` (0 = auto).
3. **200 ms capture blocks** (was 30 ms). The sounddevice callback fires 6x
   less often and blocks are split back into 30 ms frames downstream with a
   residue carry, so pre-roll / trailing-silence timing is unchanged.
   Config: `listener.block_ms` (>= 30).
4. **Overflow warnings throttled** to one line per 10 s (was one per event —
   console spam), with updated self-help text.
5. **One-time slow-ASR hint**: when ASR time > 1.5x utterance duration, the
   listener prints the exact config.json snippet to get ~2-3x more speed
   (`model_size base`, pinned `language hi`).
6. New optional `listener` keys: `cpu_threads`, `block_ms`. All previous
   keys keep working; defaults need no config.json edits.

### Added
- `config.tuned.example.json` — ready-made "listener" section for
  Hindi-medium math on a CPU laptop (base model + language hi).

### Verification
- 24-check sandbox suite (scripts/test_mic_listener_v2.py): block splitting
  with residue at 16 kHz and 48 kHz, utterance assembly through threads,
  overflow counting + throttle, config overrides, fake-Whisper end-to-end
  (segment filters, hotwords, conf/lang propagation), full-file compile.

---


## v6.1 "Six-Parameter Assessment" — fixes over the v6.0 package

v6.0 introduced the six-parameter engine but shipped two defects for the
SQLite pilot deployment. Both were caught by the new end-to-end suite
(scripts/e2e_v6.py, 33 checks through the real HTTP API) and are fixed here.

### Fixed
1. **app/db.py — `set_config()` crashed on SQLite.** `tenant_session()` ran
   the PostgreSQL-only `SELECT set_config(...)` unconditionally, so every
   endpoint would 500 on the SQLite pilot DB. It is now dialect-aware
   (`_IS_PG` guard): Postgres keeps enforced RLS tenant context; SQLite skips
   it (single-school laptop pilot by design).
2. **alembic/versions — shipped unpatched.** The v6.0 zip contained the raw
   migrations (RLS/GRANT/pgvector statements + Postgres-only column types),
   which fail on a fresh SQLite install. The package now ships the patched,
   dialect-aware migrations (generated by the re-runnable
   `patch_migration.py`, v4) — verified: fresh SQLite upgrades to 0005 with
   all 13 tables.
3. **app/learning.py — abuse count always 0 in `/learning/digest`.** Detector
   metas name the parameter `abuse` while the digest read `abuse_language`.
   Added a parameter-alias normalisation so both counting paths agree.
4. **app/brain.py — "DB RAG Error" spam + wasted work on SQLite.** The
   curriculum RAG query uses pgvector's `<=>` operator (PostgreSQL-only) and
   built a 1536-float placeholder embedding for every fall-through
   transcript. On SQLite the query is now skipped silently; embeddings/RAG
   activate again on PostgreSQL.

### Verification
* `pytest tests/` — 64 passed (23 errors are Postgres-RLS tests that
  require a live PostgreSQL; environmental, unchanged since v5.7).
* `scripts/e2e_v6.py` — 33/33 checks on fresh SQLite:
  migrations → Hindi/Devanagari math error (tier 3, proposed) → teacher
  deny → same claim suppressed to tier-1 → EN+HI abuse (tier 2 / tier 4) →
  distress (tier 3) → self-harm (tier 4) → motivation (tier 2) → discipline
  pattern (tier 1) → roster → individual mistake (tier 1) → /learning/prompt
  (aliases + Hindi vocab) → /learning/digest (all six parameters counted) →
  pause/resume gate.

## v6.0 (2026-11-03) — feature release

* **Six-parameter assessment engine** (`app/assessment/`): wrong teaching
  (MathGuard, now Hindi-aware), discipline (noise window + cue patterns),
  common/individual mistakes (roster-based, DPDP-safe), abusive language
  (two severities, school-extendable), emotional wellbeing (distress +
  self-harm), motivation (giving-up cues → encouragement).
  One primary event + up to 3 co-events per utterance; transcripts never
  persisted.
* **Hindi/Hinglish multilingual bridge** (`multilingual.py`): Devanagari +
  romanised math vocabulary → MathGuard tokens; script-based language tag;
  language=auto Whisper.
* **Continuous learning loop** (`app/learning.py` + 3 new endpoints):
  hotword growth from denied corrections, correction suppression,
  six-parameter daily digest.
* **Listener robustness**: MKL allocator recovery (retry instead of losing
  the utterance), utterance hard cap raised to ~30 s with silence-based
  segmentation, per-utterance language detection sent with the payload,
  evolved hotwords fetched from /learning/prompt at startup.

## v6.2 hotfix (2026-11-03)
- `setup_credentials.py` hardened: now ALWAYS prints the token or an exact fix.
  - Echoes the DATABASE_URL it actually sees (catches wrong-PowerShell-window mistakes).
  - Checks SQLite tables exist -> hints `python -m alembic upgrade head`.
  - `from app.auth import issue_token` wrapped: missing `app/` folder or missing PyJWT no longer crash the run.
  - Built-in stdlib HMAC-SHA256 fallback signer (identical output to PyJWT, same JWT_SECRET env / dev default).
- Script is now included in this zip at `classroom_copilot_v5/setup_credentials.py`.

- `seed_demo.py` SQLite fix: ids are now `str(uuid.uuid4())` — raw `text()` binds crash on SQLite with `uuid.UUID` objects ("type 'UUID' is not supported"). Postgres tolerated them; SQLite does not. Backend `uuid.UUID()` parses the dashed strings, so all ORM paths stay consistent (verified).

- NEW `start_all.py` — one-command v6.1 SQLite launcher (replaces start_agent.bat for SQLite mode): sets DATABASE_URL for itself and both service windows, auto-creates+migrates+seeds the DB on first run, auto-refreshes the token when <30 min remain, patches api_url when --port differs from 8000, launches uvicorn + mic_listener in titled console windows, waits for /health. Flags: --port, --no-launch, --reseed. Verified: fresh launch (health 200), idempotent rerun, token refresh, reseed regenerates credentials.

- `start_all.py` Windows spawn FIX: the v1 launcher passed the command through `cmd /c title ... && "python" ...` as a list arg — Windows re-quoting garbled it, so both popup consoles errored and closed instantly (looked like "nothing launched"). Now spawns python directly with CREATE_NEW_CONSOLE (same command list as POSIX — sandbox-tested).
- NEW `--fg` flag: runs the API in the current console so startup errors are visible.
- NEW port-busy guard: aborts with a clear message instead of silently failing when the port is taken (e.g. by a leftover old API window).

- `mic_listener.py` audio capture tuning (poor accuracy / input overflow report):
  - InputStream now opens with `latency="high"` (new default, configurable via `listener.latency`) — PortAudio gets a bigger internal buffer, the main fix for `input overflow` on WO Mic / Bluetooth / busy CPU.
  - Overflow events are counted; on the 3rd occurrence the listener prints targeted advice (USB mic, model_size base, keep latency high).
  - `listener.latency` added to apply_overrides (all other Whisper knobs were already configurable).
- NEW `config.tuned.example.json` — recommended `listener` section for Hindi-medium math on CPU: model_size base, beam_size 1 (greedy, ~3-4x faster than beam 5), language hi, latency high, min_words 2.
- Verified: config overrides incl. latency, overflow counter/advice-once, assembler emits utterances with realistic synthetic audio.

## v6.1.4 (2026-11-04) — the "Hindi phoneme soup" fix

Symptom (pilot log): English transcribed PERFECTLY ("one half is greater
than three quarters", conf -0.62) while Hindi on the SAME mic came out as
phoneme soup ("चवक सुता है कोंषे पीडर्द है", "बवाग ज्योंटा भी अच्छा…"),
every Hindi chunk exactly 10.0 s, conf -0.77…-1.10, 🗣 hi detected correctly.
English being perfect proves the mic/gate/audio path are fine — the damage
was at decode time.

### Fixed
1. **Mid-word cap cuts (mic_listener.py).** The v6.1.3 10 s hard cap sliced
   continuous speech at an arbitrary sample: Whisper received chunks that
   started AND ended mid-phoneme, and the next chunk restarted mid-word with
   only 90 ms of context. Whisper is trained on segment-aligned audio; that
   destroys low-resource languages (Hindi) while English priors still
   recover — exactly the observed asymmetry. The cap now cuts at the
   QUIETEST 30 ms frame of the last ~4 s and carries the remainder into the
   next chunk (utterance assembler `_close/_resume`), so every chunk starts
   and ends between words; no word lost, none duplicated.
2. **10 s chunks -> 20 s (mic_listener.py, `MAX_UTTERANCE_FRAMES` 333->667).**
   Whisper always pads audio to a 30 s window internally, so a 20 s chunk
   costs barely more than a 10 s one while doubling decoder context. On the
   pilot CPU this moves throughput from ~1.4x real time to ~1.0x — the same
   model now keeps up with continuous speech instead of drifting behind.
   Sentence flushes still happen on the 1.2 s pause rule.
3. **repetition_penalty 1.15 -> OFF (default 1.0).** It penalizes every
   repeated token; Devanagari legitimately repeats matras/consonants inside
   words, so the penalty pushed Hindi decode into garbage. The loops it
   guarded against came from the old noise-blob bug (fixed in v6.1.3);
   dedupe + loop-detector hints still protect. Config override:
   `listener.repetition_penalty` (1.0-2.0).
4. **temperature [0.0] -> [0.0, 0.2, 0.4].** A decode failing the confidence
   checks is now retried at a higher temperature instead of shipping garbage
   (only bad chunks pay).
5. **Adaptive beam retry.** Empty or conf < -0.95 transcripts are re-decoded
   ONCE at beam 3; the better of the two results wins
   (`listener.beam_retry`, 0 = off).
6. **Language auto-flicker.** language=auto now majority-votes over the last
   3 per-chunk detections (newest wins ties).
7. **app/assessment/lexicons.py — Devanagari word boundaries.** Python `\w`
   does not cover Devanagari matras, so the distress cue `डर` matched inside
   the garbled word "पीडर्द" and fired a false wellbeing event. Devanagari
   cues now require a real Devanagari word start (lookbehind), which also
   un-blocks real suffixed forms ("डरता", "घबराहट"). Latin cues unchanged.

### Config keys added (all optional; old config.json keeps working)
`listener.max_utt_s` (default 20), `listener.beam_retry` (default 3),
`listener.repetition_penalty` (default 1.0).
`config.tuned.example.json` refreshed for v6.1.4.

### Verification
* Offline suite (no audio hardware): 40 checks — quiet-spot cap cut lands on
  the engineered dip with exact carry-over sample equality, pause-close
  regression, 48 kHz path, kwargs contract (no repetition_penalty, temp
  fallback, hotwords, VAD), adaptive beam retry adopt/skip/empty cases,
  weighted confidence, language smoothing, lexicon guard (पीडर्द blocked,
  डरता/घबराहट matched, abuse words safe), old-faster-whisper TypeError
  fallback, --save-audio round-trip, py_compile.
* `pytest tests/` — 64 passed (23 Postgres-only RLS errors, unchanged).
