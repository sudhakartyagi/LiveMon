# v6.2.3 — session language lock, honest empty-rejects, and the learning loop

Every fix below maps to a symptom from the live classroom reports. Nothing in
the stable pipeline was restructured: adaptive noise floor, pre-roll, threaded
capture → assembler → ASR queue, no-drop backlog merger, RTF watchdog
(auto-shortens max_utt), language router, stitch, janitor, confidence gates,
the `/audio/ingest` contract and MathGuard Tier-3 approval are all unchanged.
**Hotwords stay OFF by default (measured 3–9× slower). Beam stays 1. The
default models stay stock `small` (EN) + `collabora/faster-whisper-small-hindi`
(HI). Nothing is auto-trained.**

## Symptom → fix

| # | Symptom | Root cause | v6.2.3 fix |
| --- | --- | --- | --- |
| 1 | **Accented English math came out as Devanagari transliteration soup** — a strong-accented English chunk probed as `hi` (or the probe was skipped during a backlog) and the Hindi fine-tune transliterated it | auto routing has no idea what the LESSON is; per-chunk probes can misfire on accents | **SESSION LANGUAGE LOCK**: `listener.language`: `"en"` \| `"hi"` \| `"auto"` (default `auto`, the measured router). With `"en"` every chunk decodes on the stock model — the hi-model path is never taken, *including* the script-sanity and cold-start re-decodes (unit-tested with a hi-model that raises if touched). With `"hi"` every chunk goes straight to small-hi and EN probes are skipped (no probe thrash). Math pilot → `"en"`; Hindi-medium lesson → `"hi"`. A startup line spells out the guarantee (`🔒 Language lock: …`). Typos fall back to auto with a warning, never wedge the router |
| 2 | **"🔇 …confidence gate rejected every segment"** on chunks that clearly contained speech; no way to tell *why* a chunk produced nothing | one opaque reject path for two very different cases (no speech detected vs. speech decoded below the gates); borderline decodes that landed just under the thresholds were lost with no second chance | **REASON CODES**: every silent chunk now prints `rejected_no_speech` (VAD/decode found nothing) or `rejected_low_conf` (speech decoded but every segment below the gates); short drops print `rejected_too_short` (symbol-only keeps its own line). **BORDERLINE RESCUE**: when real speech (≥ 1.2 s utterance) produced zero shippable segments and the CPU is not behind (rolling RTF ≤ 1), ONE re-decode runs with slightly lower decode thresholds (`log_prob_threshold` −1.0 → −1.15, `no_speech_threshold` 0.6 → 0.7) and a hair-lower segment hard floor (−1.1 → −1.25). Max once per utterance — no decode chains. The no-speech combo, compression-loop and hallucination gates are IDENTICAL on the retry: the confidence gates are never disabled, junk still cannot ship. `listener.empty_retry: false` turns the rescue off |
| 3 | **`⚠️ Ignored short noise: 'three quarters.'`** — the v6.2.2 stitch + allowlist already fixed the split claim; the remaining gap was that the allowlist only knew OUR static fraction list | teacher-specific phrasing ("three quarters of one half", lesson-specific fragments) was invisible to a static list | **KEPT + EXTENDED**: stitch, EN+HI cue lists and the static allowlist are unchanged; the allowlist now also loads *teacher-accepted* phrase patterns from the experience loop (`data/experience/allowlist.txt`), so a phrase the teacher once ACCEPTED stops dying as "noise" for the rest of the session. Rejected patterns are never added |
| 4 | **No learning** — teacher decisions on Tier-3 proposals vanished into the dashboard; nothing remembered what the listener got right, dropped, or misheard | the listener had no local memory of its own decisions | **EXPERIENCE LEARNING LOOP** (`experience.py`, stdlib SQLite, WAL, thread-safe — no new dependencies): table `experience_events(ts, lesson_id, route, transcript, confidence, noise_db, event_type, teacher_decision, edited_text, note)`. Wired: every `/audio/ingest` attempt, every short drop, every Tier-3 proposal seen in a response, and every teacher **accept / reject / edit** — from a `GET {API_URL}/lesson/feedback?since_id=` poller (20 s, best-effort; a missing endpoint prints one info line and goes silent) or any dashboard callback that writes the same endpoint. Derived rules (explicit, never silent weight updates): **accept** → phrase pattern appended to the allowlist file; **reject** → false pattern recorded in `data/experience/false_patterns.txt`, allowlist deliberately unchanged; **edit** → corrected `(asr → teacher)` pair stored for later eval/train. End-of-session counts print at shutdown; `python mic_listener.py --experience-report` gives all-time + last-7-days counts and the latest corrected pairs |
| 5 | "can we train on this later?" | — | **OFFLINE, OPT-IN ONLY**: `python mic_listener.py --experience-export [DIR]` writes accepted/edited `(asr, ref)` text pairs to `data/asr/{en,hi}/txt|asr/` + a manifest (copy matching `--save-audio` WAVs next to them to complete the set). Training stays a separate script (see `docs/FINETUNE_HI_OPTIONAL.md`); results plug in ONLY via config overrides — `listener.hi_model` (v6.2.2) and the new `listener.en_model` (same contract, defaults stay `small`). Nothing exports, trains or swaps models by itself |

## Non-negotiables honored

- Global hotwords: still **OFF by default** (v6.1.6 bench numbers unchanged).
- MathGuard / teacher approval: untouched — the loop only *observes* responses.
- No runtime fine-tune: the store holds text metadata (no audio, no recordings);
  training/export are separate opt-in commands.
- Watchdog, backlog merger, stitch, router, janitor, confidence gates,
  `/audio/ingest` payload: unchanged.
- New decode work is budget-gated: the rescue re-decode runs only when the
  rolling RTF ≤ 1 and never more than once per utterance.

## Config (all optional; defaults preserve v6.2.2 behaviour)

```json
"listener": {
  "language": "auto",              // "en" | "hi" | "auto" — the session lock
  "empty_retry": true,             // one borderline re-decode per utterance
  "experience": true,              // local SQLite decision mirror
  "experience_db": "experience.db",
  "feedback_url": null,            // override the /lesson/feedback URL
  "experience_allowlist": null,    // override the accepted-patterns file
  "en_model": null                 // opt-in stock/EN model override (like hi_model)
}
```

## Tests (all green before release)

| Suite | Result |
| --- | --- |
| Shipped offline suite `tests/test_listener.py` | **172/172** (was 134; +38 v6.2.3 checks) |
| AST audit (module globals read-before-assign — the v6.2.0 crash class) | clean (+ self-test that the detector fires on a seeded bug) |
| New regressions | `language=en` never calls the hi model (raising mock) · `language=hi` never calls stock · Devanagari-soup output stays on stock under the lock · `"auto"`/aliases/typos normalize · rescue fires exactly once with lowered thresholds and ships the chunk · failed rescue still only 2 decodes + reason code · sub-1.2 s audio not rescued · `empty_retry=false` honored · short drop → `rejected_too_short` · mock teacher accept/reject/edit rows + accept-appends-allowlist + reject-never-does + edit pair + offline export · Tier-3 proposal in a response logged as `math_proposal` · feedback payload parsing |

## Verify it yourself (5 minutes, no class needed)

```powershell
# 1) English math with the lock on (put "language": "en" in config.json first)
python mic_listener.py
#    say: "One half is greater than three quarters."  — pause after "than" too;
#    the stitch still ships ONE claim and the backend answers with the Tier-3
#    proposal. The console shows 🧩 / ✅ and the proposal line.

# 2) Hindi line, measured honestly
python mic_listener.py --save-audio
#    say: "एक आधा तीन चौथाई से बड़ा नहीं है"  (with "language": "hi")
python mic_listener.py --bench saved_audio/utt_*.wav --ref "एक आधा तीन चौथाई से बड़ा नहीं है"

# 3) Learning loop
python mic_listener.py --experience-report    # counts + latest corrected pairs
python mic_listener.py --experience-export    # offline, opt-in, writes data/asr/
```
