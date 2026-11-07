# Pilot Runbook — classroom_copilot live listener v6.3.0

One-time setup + a 10-minute English math demo that must succeed, plus what
to do when it doesn't. (2 pages; details in README_v6.3.0.md and
`python mic_listener.py --help`.)

## 0. One-time setup (5 min)

```
pip install -r requirements_audio.txt
python mic_listener.py --list-mics        # note your mic name/index
python mic_listener.py --meter            # speak: bar must move + show SPEECH!
```

- **Mic placement**: 30–60 cm from the teacher, hard-addressed at the
  teacher (not the ceiling); avoid laptop-fan side. A USB/headset mic beats
  WO Mic/Bluetooth (fewer dropped samples → fewer garbled words).
- In `--meter`: bar flat when speaking → wrong device (Windows Settings →
  Sound → Input, or `listener.input_device` in config.json). Bar moves but
  never reaches the gate → raise mic volume / move closer, or set
  `"start_margin_db": 4`.
- Credentials: `python setup_credentials.py` (writes config.json — never
  commit it). Start the backend + dashboard: `python start_all.py`.

## 1. Pick the preset (the only decision you make per lesson)

| Preset | When | Command |
| --- | --- | --- |
| `math_en` | English-medium math (the pilot) | `python mic_listener.py --preset math_en` |
| `hindi_class` | Hindi-medium lesson | `python mic_listener.py --preset hindi_class` |
| `auto` | genuinely mixed hour | `python mic_listener.py` (default) |

- `math_en` HARD-LOCKS English: the stock EN model only — the Hindi model
  is never loaded or called, so accented English can't become Devanagari
  soup. (Equivalent without the preset: `"language": "en"` in config.)
- `hindi_class` pins the Hindi fine-tune, skips EN probes, and never
  applies EN math hotwords.
- Hotwords are OFF by default everywhere (measured 3–9× slower). Leave them
  off unless `--bench` proves they help your room.

## 2. The 10-minute English math demo (must succeed)

1. Start backend + listener with `--preset math_en`. Watch for:
   `🔊 Calibrated…` (stay quiet 2 s), `🔒 Preset 'math_en': language LOCKED…`,
   and `🔒 language=en — the Hindi model is NOT loaded`.
2. **Minute 1 — gate check**: speak one sentence from your seat. Expect
   `✅ Teacher said: …` within a few seconds. Nothing? The 👂 heartbeat line
   shows `mic peak` vs `gate opens at` — if the peak never reaches the
   gate, fix mic/device (step 0), don't touch code.
3. **Minute 2–3 — the acceptance sentence**, clearly, at demo volume:
   *"One half is greater than three quarters."*
   Expect ONE coherent line `✅ Teacher said: One half is greater than three
   quarters` and then a `⏳ Tier 3 PROPOSAL — awaiting your YES` (MathGuard;
   approve on the dashboard). **Success = a single transcript + a proposal.**
4. **Minute 4–5 — split-claim resilience**: say it with a deliberate
   2-second pause in the middle: *"One half is greater than" … "three
   quarters."* The stitcher joins the tail (`🧩 Stitched onto the previous
   tail`) — the second chunk must NOT die as "Ignored short noise". Short
   fragments like *"three quarters"* alone are kept by the math allowlist.
5. **Minute 6–7 — Hindi sanity** (optional): restart with
   `--preset hindi_class` and say *"तीन चौथाई एक आधे से बड़ा है"*. Expect
   readable Devanagari on the `small-hi` route (not perfect; readable).
6. **Minute 8–10 — teacher loop**: Reject one wrong proposal and Accept one
   right one on the dashboard, then run
   `python -m tools.experience_report` — counts must move
   (`teacher_decision: accept ≥ 1`, allowlist grew by your accepted phrase).

## 3. What success looks like (and what we guarantee)

| Signal | Healthy |
| --- | --- |
| RTF in the ⚡ ASR line | `< 1.0×` typical on a modern CPU laptop with `small-hi`; the watchdog auto-shortens chunks (12→9→7 s) if the CPU falls behind — late but nothing lost |
| Drops | Every drop carries a reason: occasional `low_conf` = teacher too far/room noise; `no_speech` clusters = mic muted/disconnected; `short_noise` only for non-math fragments |
| Hindi | readable, not perfect — we make **no 100% accuracy claim**; measure your room: `python mic_listener.py --bench saved_audio/*.wav --ref "exact words"` (WER + RTF per model) |
| Proposals | Every Tier-3 action waits for teacher approval — nothing is auto-applied |

## 4. When RTF is high / text is late

1. It self-heals first: queued chunks merge into ONE decode (nothing is
   dropped) and the watchdog shortens the cap — expect late, complete text.
2. `"model_size": "base"` in config.json = the fastest honest option
   (bench first: `--bench --ref`).
3. `"language": "hi"` during Hindi-medium stretches skips EN probes (also
   implied by `--preset hindi_class`).
4. Recurring `audio status` overflow warnings → USB mic; keep
   `"block_ms": 200`.
5. Garbled text with clean audio? Record what Whisper hears:
   `--save-audio`, replay with `--test-wav`, then bench.

## 5. What is never automatic

Hotwords (OFF by default), runtime fine-tuning, silent weight updates,
auto-punish/discipline actions, cloud ASR. The experience loop only writes
readable files you control: accepts → `data/experience/allowlist.txt`,
rejects → `false_patterns.txt`, edits stay in `experience.db` until you
export (`--experience-export`) and train offline (docs/FINETUNE_HI_OPTIONAL.md).
