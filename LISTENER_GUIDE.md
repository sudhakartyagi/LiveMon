# Listener Guide (v6.2.2) — install, tuning, honest limits

## Install (Windows PowerShell)

```powershell
cd classroom_copilot_v5
pip install -r requirements_audio.txt
python setup_credentials.py            # writes YOUR config.json (never shipped)
python mic_listener.py --list-mics     # optional: pick "input_device"
python mic_listener.py                 # live listener (dashboard on :8501)
```

First run downloads the models once (~1 GB for the default `small-hi`
pair), then everything is fully offline. On a weak laptop the download is
the slow part (the 213.9 s "Hindi model ready" in one pilot log was the
first-run download, not the load).

## First run ritual (30 seconds, do not skip)

1. Start the listener BEFORE the class; stay **quiet for the 2 s
   calibration** ("🔊 Calibrated. Noise floor: …").
2. Watch the 👂 heartbeat: `mic peak` must clearly exceed `gate opens at`.
   If not: mic volume up, move closer, or `"start_margin_db": 4`.
3. Speak normally. ~1.2 s of quiet closes a sentence; 12 s chunks split at
   real word gaps (never mid-word unless you literally never pause).

## The math tail rescue (v6.2.2) — verify it in your class

v6.2.2 fixes the production log case where `…one half is greater than`
printed fine but `three quarters.` died as `⚠️ Ignored short noise`. Two
mechanisms, both automatic:

1. **Stitch** — if a chunk continues an incomplete cue (EN: *greater
   than, less than, equal to, equals, plus, minus, into, upon, divided
   by…* / HI: *से बड़ा, से छोटा, बराबर, आधा, तिहाई, चौथाई, अंश, हर, जमा,
   घटा, गुणा, भाग…*), the tail of the previous accepted transcript is
   joined onto it and ONE combined transcript is sent (`🧩 Stitched onto
   the previous tail …`). MathGuard sees the whole claim again.
2. **Allowlist** — `three quarters`, `one half`, `तीन चौथाई`, `एक आधा`,
   `दो तिहाई`, `तीन चौथाई भाग`… are never dropped for being short
   (`🧮 Kept a math fragment …`). Junk (symbols, loops, hallucinations) is
   still dropped exactly as before.

**English verification (2 minutes, no tools):** say *“One half is greater
than three quarters.”* once normally, then once with a 2-second pause
after **“than”**. Both must print ONE `✅ Teacher said: one half is
greater than three quarters` — the paused case shows the `🧩` stitch line
and MathGuard Tier-3 flags the false statement on the dashboard. If the
paused case instead shows `⚠️ Ignored short noise`, send me that console
block.

## Bench Hindi (and any model choice) honestly

Synthetic/espeak WER numbers are NOT your classroom — measure your room:

```powershell
python mic_listener.py --save-audio                 # record real lines
python mic_listener.py --bench saved_audio/utt_*.wav --ref "एक आधा तीन चौथाई से बड़ा नहीं है"
```

`bench_fixtures/hi_classroom_refs.txt` has 10 ready Class 4–5 Hindi lines
(math + classroom management) to read aloud, one per recording, joined
with `" | "` for multi-WAV runs. The table ranks base / small / small-hi
by WER + RTF **through the production path**. To bench a model you
fine-tuned yourself, see the next section — the config override repoints
the `small-hi` row.

## Optional Hindi fine-tune (separate, opt-in, offline)

The listener never trains. If you want a model adapted to YOUR room, the
recipe (data layout, eval-first gate, LoRA/PEFT steps, CTranslate2 export,
consent/retention rules) lives in `docs/FINETUNE_HI_OPTIONAL.md`. Enable
the result with ONE key — the default is never touched without it:

```json
"listener": { "hi_model": "local/small-hi-classroom-v1" }
```

## Optional route prompts (OFF by default — bench before enabling)

In your `config.json` listener section (keys shown with their defaults —
add only what you change):

```json
"math_initial_prompt": false,
"hindi_classroom_prompt": false
```

Prompts measurably hurt the Hindi fine-tune (conf −0.60 vs −0.10), so the
HI route ships with none; both flags are opt-in per class and never apply
across routes.

## Which model for which class

| config.json `model_size` | Use when | Measured behaviour |
| --- | --- | --- |
| `small-hi` (default) | Hindi/Hinglish-medium Class 4–5 | Best Hindi by far (bench: WER 57% on *robotic* espeak Hindi vs 93–100% for base/small; real classroom audio does much better — measure yours). English equal to stock. RTF ~0.6× on a 2-thread bench box; the backlog merger keeps every word even when the CPU falls behind. |
| `base` | Weak CPU (RTF > 1 with small-hi), English-heavy lessons | ~2–3× faster; Hindi markedly weaker (bench 92.6% WER). |
| `small` | Hindi download impossible | Stock Hindi is unusable (67% FLEURS WER); English fine. |
| `medium` / `medium-hi` | Overnight/accuracy mode on strong CPUs | Set `model_size": "medium"`; Hindi fine-tunes at medium size are community models — bench them with `--bench --ref` before trusting them in class. |

## English class vs Hindi class tips

* **English math pilot** — defaults are already tuned. Optionally add a
  domain prompt (EN route only):
  `"initial_prompt": "Class 4-5 math lesson: fractions, one half, three
  quarters, numerator, denominator, greater than, less than, equals"`.
  Bench-measured: confidence −0.17 → −0.12, recovery unchanged. The Hindi
  route NEVER receives prompts (they measurably poison the fine-tune:
  conf −0.60 vs −0.10).
* **Hindi-medium class** — keep defaults (`small-hi`, language auto). If
  the lesson is fully Hindi, `"language": "hi"` skips probing (slightly
  faster). Hinglish (घर का time) is handled: the fine-tune emits Latin
  words inside Devanagari naturally.
* Never set `"hotwords"` unless you bench it first — hotwords measured
  3–9× slower and destabilized BOTH models; that is why they are off.

## Mic placement (biggest single accuracy lever)

* USB/headset mic 0.5–2 m from the teacher, off the laptop chassis (fan
  noise). WO Mic/Bluetooth adds dropouts that garble words.
* Teacher-side check: `python mic_listener.py --save-audio`, teach for a
  minute, listen to `saved_audio/*.wav`. Muffled audio = mic/room problem
  (no model fixes that); clean audio + wrong text = model/settings.

## Bench your own room (the honest number)

```powershell
python mic_listener.py --save-audio              # record a real lesson snippet
python mic_listener.py --bench saved_audio/utt_*.wav --ref "the exact words spoken"
```

Ranks `base` / `small` / `small-hi` by word-level WER + real-time factor
on YOUR recording, through the exact production path (same chunking,
gates, janitor). Bench one recording (or same-language recordings) per
run; `--ref` accepts `"ref1 | ref2"` mapped 1:1 onto multiple WAVs.

## Honest limits

* CPU RTF: `small-hi` measured 0.63× (Hindi) / 0.44× (EN) on a fast 2-thread
  bench box. A weak Celeron-class laptop measured ~2–3.4× SLOWER than real
  time on v6.1.x — v6.2.0 keeps every word there (merger + adaptive
  chunking) but text arrives late during nonstop speech; switch to `base`
  for real-time if that matters more than accuracy.
* All published WER numbers are on **synthetic espeak audio** (worst case,
  robotic prosody) because no consented real-classroom recording was
  available in development. Measure your room with `--bench --ref`.
* The language probe is reliable on real mic audio; on synthetic/robotic
  audio it can misprobe (cold-start rescues + script sanity cover most
  cases, and `--bench` seeds the route from your reference).
* Approval gating, Tier-3 MathGuard, and the `/audio/ingest` contract are
  unchanged by v6.2.0.
