# classroom_copilot listener — v6.2.3 operations README

Everything you need to run the listener in class, pick the language lock,
use the meter, and understand the new **experience learning loop** — plus an
honest list of what it does **NOT** do automatically.

---

## 1. Mic placement (fixes most "it can't hear me" problems before any code)

- **Best → worst**: USB/headset mic > laptop built-in > WO Mic / Bluetooth.
  WO Mic and Bluetooth drop samples under CPU load — dropped samples garble
  words no model can fix.
- Place the mic **0.5–2 m** from the teacher, off the desk (desk thumps read
  as speech). Point it away from fans / the projector.
- Close the door if the corridor is loud. The noise floor adapts, but a
  cleaner room still transcribes better.
- If words garble with GOOD confidence: record what the mic actually hears —
  `python mic_listener.py --save-audio` — and listen to the WAVs. Clean audio
  + bad text = model/settings problem. Muffled audio = mic/room problem.

## 2. `--meter`: see the gate before class (no Whisper needed)

```powershell
python mic_listener.py --meter
```

Speak normally; each line is 0.5 s of level vs. the speech gate.

| What you see | Meaning | Fix |
| --- | --- | --- |
| Bar does not move when you speak | Windows captures the wrong/quiet device | Settings → Sound → Input, or `listener.input_device` (find names with `--list-mics`) |
| Bar moves but never shows `SPEECH!` | level below the gate | raise mic volume / move closer / `"start_margin_db": 4` in the listener config |
| Shows `SPEECH!` here but the listener stays deaf | that would be a listener bug | report it with the console output |

The listener also prints a `👂 listening…` heartbeat every 30 s with the mic
peak vs. the gate — same diagnosis, during class.

## 3. The session language lock (`listener.language`)

One line in `config.json`:

```json
"listener": { "language": "en" }
```

| Value | Behaviour | Use for |
| --- | --- | --- |
| `"en"` | **Every** chunk decodes on the stock English model. The Hindi model is *never* invoked — not even by the script-sanity/cold-start rescues (unit-tested). Accented English math can no longer come out as Devanagari soup. | The **math pilot** and any English-medium lesson |
| `"hi"` | Every chunk decodes on the Hindi fine-tune (`small-hi`); English probes are skipped entirely — less CPU thrash. No EN hotwords/prompts are ever applied on this route. | **Hindi-medium** lessons |
| `"auto"` (default) | The measured per-chunk router (probe when there is slack, sticky language when behind). Right for mixed/Hinglish periods. | Mixed lessons |

Notes:
- `"english"`/`"hindi"` are accepted as aliases; `"EN"`/`"HI"` work; a typo
  warns once and falls back to auto (it can never wedge the router).
- The lock applies to the session — switch per lesson by editing config and
  restarting, or keep `auto` for genuinely mixed classes.
- On startup the console prints exactly what is guaranteed
  (`🔒 Language lock: EN …` / `🗣 Language: auto …`).

## 4. The experience learning loop

**What it is**: a small local SQLite store (`experience.db`, stdlib only —
no new dependencies) where the listener mirrors every transcript decision, so
the system learns from experience through **rules you can inspect**, never
through silent model changes.

**What gets stored** (text metadata only — never audio, never recordings):

| event_type | When |
| --- | --- |
| `ingest` | every `/audio/ingest` attempt (transcript, route, confidence, noise_db) |
| `short_drop` | every chunk the min-words gate dropped (`rejected_too_short`) |
| `math_proposal` | every Tier-3 proposal the backend produced |
| `teacher_decision` | your **accept / reject / edit** of a proposal (with the corrected text when editing) |

**How teacher decisions reach the store**: the listener polls
`GET {API_URL}/lesson/feedback?since_id=` every 20 s (override:
`listener.feedback_url`). The backend can expose whatever the dashboard
already writes; flexible JSON shapes are accepted. A missing endpoint prints
one info line and the poller goes quiet — nothing else is affected.

**What the rules do** (explicit, inspectable — files you can open):

- **accept** → the phrase pattern is appended to
  `data/experience/allowlist.txt`; the listener loads it, so that phrase
  stops being dropped as "short noise" (`📚 Teacher accept recorded …`).
- **reject** → the pattern is recorded in `data/experience/false_patterns.txt`
  and is deliberately **never** added to the allowlist.
- **edit** → the corrected `(asr → teacher)` pair is stored for later
  offline eval / opt-in training.

**Commands**:

```powershell
python mic_listener.py --experience-report   # counts (all time + 7 days),
                                             # accept/reject/edit, latest pairs
python mic_listener.py --experience-export   # OFFLINE + OPT-IN: writes
                                             # accepted/edited (asr, ref) text
                                             # pairs to data/asr/{en,hi}/
python mic_listener.py --experience-report --experience-db D:\path\to\other.db
```

The end-of-session summary line shows this session's counts too
(`📚 Experience this session: …`).

**Turning it off**: `"listener": { "experience": false }` — everything else
keeps working.

## 5. What is NOT auto-trained (read this once)

- **No runtime fine-tune. Ever.** The listener never updates model weights.
- **No silent updates.** The only "learning" is the two pattern files above
  plus the SQLite rows — open them in any editor; delete them to forget.
- **Hotwords stay OFF by default** (bench-measured 3–9× slower and
  destabilizing on both models). Don't enable them for accuracy work.
- **Export is manual**: `--experience-export` only runs when you run it, and
  writes plain-text pairs (no audio) under `data/asr/{en,hi}/`.
- **Training is a separate, opt-in offline script** (GPU recommended) — see
  `docs/FINETUNE_HI_OPTIONAL.md`. Its output is YOUR model file; it takes
  effect only when you point `listener.hi_model` (Hindi) or
  `listener.en_model` (English) at it in config. Defaults remain the measured
  stock `small` + `collabora/faster-whisper-small-hindi`.
- **Consent & children**: don't export or train on student-identifiable
  audio without consent and a retention policy; prefer phrase-level teacher
  speech; don't keep raw audio longer than you need.

## 6. Quick verification script (5 minutes)

```powershell
# A) English math with the lock on  (config.json: "language": "en")
python mic_listener.py
#    Say: "One half is greater than three quarters."
#    Also try pausing 2 s after "...greater than" — the stitch still ships
#    ONE claim, and the backend answers with the Tier-3 proposal line.

# B) Hindi line with the lock on  ("language": "hi")
python mic_listener.py --save-audio
#    Say: "एक आधा तीन चौथाई से बड़ा नहीं है"
python mic_listener.py --bench saved_audio\utt_*.wav --ref "एक आधा तीन चौथाई से बड़ा नहीं है"
#    → reports WER + RTF per model on YOUR mic. Synthetic/espeak audio is
#      NOT representative — bench real classroom recordings.

# C) Learning loop
python mic_listener.py --experience-report
#    Accept one proposal on the dashboard, wait ≤ 20 s, re-run the report:
#    the accept must appear, and data/experience/allowlist.txt grows by one
#    line. Reject a proposal: the count moves, the allowlist does not.
```

## 7. Troubleshooting quick map

| Symptom | First move |
| --- | --- |
| Nothing transcribes | `--meter` → mic placement (§1) |
| `🔇 rejected_no_speech / rejected_low_conf` lines | speak closer / louder; check `--save-audio` WAVs |
| `♻️ Borderline chunk rescued` | normal — the one-re-decode recovered a near-miss |
| Wrong language routing | set the lock (§3): `"en"` for the math pilot, `"hi"` for Hindi-medium |
| Behind by a lot (⏳ lines) | `"model_size": "base"` for live class; the watchdog already shortens chunks |
| Wrong-but-confident text | `--bench --ref` with real recordings before touching any config |
