# classroom_copilot listener — v6.3.0 operations README

The pilot workbench release: **session presets**, **structured drop
reasons**, a **modular codebase**, and the experience learning loop — with
an honest list of what it does **NOT** do automatically.

> New here? Start with **PILOT_RUNBOOK.md** (2 pages: mic placement, the
> 10-minute English math demo, what success looks like, what to do when
> RTF is high). This README is the operations reference.

---

## 1. Mic placement (fixes most "it can't hear me" problems before any code)

- **Best → worst**: USB/headset mic > laptop built-in > WO Mic / Bluetooth.
  WO Mic and Bluetooth drop samples under CPU load — dropped samples garble
  words no model can fix.
- Place the mic **0.5–2 m** from the teacher, off the desk (desk thumps read
  as speech). Point it away from fans / the projector.
- If words garble with GOOD confidence: record what the mic actually hears —
  `python mic_listener.py --save-audio` — and listen to the WAVs. Clean audio
  + bad text = model/settings problem. Muffled audio = mic/room problem.

## 2. `--meter`: see the gate before class (no Whisper needed)

```powershell
python mic_listener.py --meter
```

| What you see | Meaning | Fix |
| --- | --- | --- |
| Bar does not move when you speak | Windows captures the wrong/quiet device | Settings → Sound → Input, or `listener.input_device` (find names with `--list-mics`) |
| Bar moves but never shows `SPEECH!` | level below the gate | raise mic volume / move closer / `"start_margin_db": 4` in the listener config |
| Shows `SPEECH!` here but the listener stays deaf | that would be a listener bug | report it with the console output |

During class the `👂 listening…` heartbeat prints the mic peak vs. the gate;
if the peak never opens the gate while you were speaking, the log tells you
exactly that with the same fixes.

## 3. Presets: pick ONE per lesson (v6.3.0)

```powershell
python mic_listener.py --preset math_en      # English math pilot
python mic_listener.py --preset hindi_class  # Hindi-medium lesson
python mic_listener.py                       # auto (default)
```

| Preset | Guarantees |
| --- | --- |
| `math_en` | Language HARD-LOCKED to English: stock model only, **the Hindi model is never loaded and never called** — accented English math cannot become Devanagari soup. Hotwords forced OFF. |
| `hindi_class` | Every chunk on the Hindi fine-tune, EN probes skipped (no CPU thrash), **no EN math hotwords / EN prompts on this route**. |
| `auto` | The measured per-chunk language router (unchanged default behaviour). |

Config equivalent: `"listener": { "preset": "math_en" }` — the CLI
`--preset` wins over config. Presets only pin language/model/hotwords; the
optional route prompts (`math_initial_prompt`, `hindi_classroom_prompt`)
stay OFF by default because prompts measured to hurt decode. Without a
preset you can still lock manually: `"language": "en"` or `"hi"` (aliases
`english`/`hindi`; anything unknown falls back to auto with a warning).

## 4. Reading the log: structured drop reasons (v6.3.0)

Every captured-but-not-shipped chunk prints ONE machine-readable code —
grep `reason=` in a pilot log, and the session summary counts them:

| Code | Meaning | Typical fix |
| --- | --- | --- |
| `no_speech` | VAD/decode found no speech (silence, dropout) | mic muted/disconnected; `--meter` |
| `low_conf` | speech decoded but under the confidence gates | teacher closer to the mic; check `--save-audio` |
| `short_noise` | below min-words and not an allowlisted math fragment | expected for stray words |
| `duplicate` | same normalized text within 10 s, or a repeated seam tail | none (Whisper loop guard) |
| `prompt_echo` | the continuation prompt was re-emitted with nothing new | none (self-protection) |
| `symbol_only` | punctuation/symbol-only output | none |

Borderline real speech (≥1.2 s, everything dropped, CPU keeping up) gets
**one** budget-gated re-decode — the `soft_retry` flag (default on; the
confidence gates themselves are never disabled). Set
`"soft_retry": false` to disable.

## 5. Math reliability: stitch + allowlist (v6.2.2, hardened in v6.3.0)

- **Stitch**: the last ~6 words of an accepted transcript are re-joined
  when a chunk continues an incomplete cue — *"one half is greater than" +
  "three quarters."* ships as ONE claim; head-cues ("greater than three
  quarters" after "one half is") stitch too. v6.3.0 adds earlier cut-point
  cues (EN "is greater"/"is less"/"is equal"; HI "इससे बड़ा", "इससे छोटा",
  "बराबर है"). Knobs: `stitch_tail_words` (3–8), `stitch_window_s`.
- **Allowlist**: fraction fragments ("three quarters", "तीन चौथाई", and
  v6.3.0 spoken forms "three by four", "one upon two", "एक बटा दो") are
  never dropped for length. Symbol-only/hallucination junk still dies.
- **Safer cuts**: cap splits land only in real word gaps; the carry keeps
  the remainder — no audio is ever lost.

## 6. The experience learning loop (teacher in control)

Every ingest attempt, short drop (with its reason code), and Tier-3
proposal is mirrored to the local SQLite store (`listener.experience_db`,
default `experience.db`). Teacher decisions arrive from the dashboard
(via `GET /lesson/feedback` on the backend when present — polled quietly;
missing endpoint = one info line, TODO(API-WEBHOOK) noted in
`listener/experience_store.py`).

| Decision | Derived effect (rules, never weights) |
| --- | --- |
| Accept | phrase pattern appended to `data/experience/allowlist.txt` → that short fragment stops dying as "noise" |
| Reject | recorded in `false_patterns.txt`; **never** allowlisted |
| Edit | (asr → teacher) pair stored for offline eval/train |

```powershell
python mic_listener.py --experience-report   # or: python -m tools.experience_report
python mic_listener.py --experience-export   # offline, opt-in (asr, ref) pairs
```

## 7. The Hindi route (honest numbers only)

`model_size: "small-hi"` pairs stock `small` (English) with
`collabora/faster-whisper-small-hindi` (FLEURS-Hindi WER 7.2% vs 67.4%
stock). **No 100%-accuracy claims** — measure YOUR room:

```powershell
python mic_listener.py --save-audio                 # during a lesson
python mic_listener.py --bench saved_audio/*.wav --ref "तीन चौथाई एक आधे से बड़ा है"
python mic_listener.py --test-wav saved_audio/utt_*.wav   # quick replay
```

The bench prints per-model WER/RTF through the exact production path.
A locally fine-tuned model plugs in via `listener.hi_model`
(docs/FINETUNE_HI_OPTIONAL.md — separate, opt-in, offline).

## 8. What is NEVER automatic

- Global hotwords: **OFF by default** (measured 3–9× slower + destabilizing;
  presets force them off).
- Runtime fine-tuning / silent weight updates: never. The loop only writes
  readable text files you control.
- Emotion/discipline autonomous actions: not touched.
- Cloud ASR: not used, not required.
- Tier-3 math actions: always teacher-approved.

## 9. Files in this package

```
mic_listener.py            main listener loop + CLI (composition root)
listener/                  audio_gate · assembler · asr_router · math_stitch
                           · janitor · reasons · presets · experience_store
tools/experience_report.py python -m tools.experience_report
experience.py              backward-compat shim
tests/                     test_listener.py (172 checks) +
                           test_v63_acceptance.py (31 pytest tests) — offline
config.example.json        every knob incl. preset + soft_retry
PILOT_RUNBOOK.md           the 2-page demo script
bench_fixtures/            reference scripts for --bench
docs/FINETUNE_HI_OPTIONAL.md  opt-in offline fine-tune recipe
```
