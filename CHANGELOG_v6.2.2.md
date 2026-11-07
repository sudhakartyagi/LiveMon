# v6.2.2 — math tail rescue (stitch + allowlist) & Hindi continuity

Every fix below maps to a symptom in the production logs. Nothing in the
stable pipeline was restructured: adaptive noise floor, pre-roll, threaded
capture → assembler → ASR queue, backlog merger, RTF watchdog, language
router, janitor, confidence gates, `/audio/ingest` contract and MathGuard
Tier-3 approve flow are untouched. Hotwords and domain prompts stay OFF by
default; beam stays 1; no medium models became defaults.

## Symptom → fix

| # | Log symptom | Root cause | v6.2.2 fix |
| --- | --- | --- | --- |
| 1 | `✅ …one half is greater than` then `⚠️ Ignored short noise: 'three quarters.'` — the claim was split across chunks and the tail dropped, so MathGuard never saw the full statement | the min-words gate judges every chunk in isolation; a 2-word math tail has no chance | **A1 STITCH**: the last 6 words of the previous *accepted* transcript (config `listener.stitch_tail_words`, spec range 3–8) are stitched in front of a chunk that continues an incomplete cue — previous tail ends with one (`greater than`, `equals`, `से बड़ा`, `दो तिहाई` …) or the new text starts with one (`greater than three quarters`). Runs BEFORE the min-words filter and before the API send; the janitor runs once on the combined text; ONE combined transcript ships (`🧩 Stitched onto the previous tail …`). A tail older than `listener.stitch_window_s` (12 s) never stitches |
| 2 | same log line — the tail would be fine on its own if it were not for its length | `three quarters` / `तीन चौथाई` are real math, not noise | **A2 ALLOWLIST**: EN+HI number×fraction fragments (`three quarters`, `one half`, `two thirds`, `तीन चौथाई`, `एक आधा`, `दो तिहाई`, `तीन चौथाई भाग`, …) are never dropped for being below MIN_WORDS (`🧮 Kept a math fragment …`). Symbol-only, punctuation-only and hallucination output are still rejected first — the allowlist only waives the word count |
| 3 | claims split when a cap-cut lands right after a cue | cuts pick the longest real pause; a cue-adjacent pause is chosen only when the teacher truly never pauses | **A3**: unchanged measured cut logic (v6.2.0 longest-real-gap rule already skips cue-adjacent micro-pauses whenever any longer pause exists) + the A1 stitch repairs any forced cut. No new cut heuristics to destabilize the stable build |
| 4 | Hindi continuity: good lines work, but mid-claim chunks and domain phrasing still wobble | chunks decode with no claim-level memory; prompts measured to poison the fine-tune | **A1 stitch works on the HI cue list too** (`से बड़ा`, `से छोटा`, `बराबर`, `आधा`, `तिहाई`, `चौथाई`, `अंश`, `हर`, `जमा`, `घटा`, `गुणा`, `भाग`) and the continuation prompt (v6.2.0) is unchanged. **A4 optional prompts, OFF by default**: `listener.math_initial_prompt` (EN route only) and `listener.hindi_classroom_prompt` (HI route only). Never applied across routes; with both false the route kwargs are byte-identical to v6.2.1 |
| 5 | no honest way to improve Hindi phrases without risking the stable model | — | **B1**: `--bench --ref` now also benches a LOCAL model: `"listener": {"hi_model": "local/small-hi-classroom-v1"}` (or top-level `hi_model`) repoints the HI route AND the `small-hi` bench candidate. Hindi fixture lines ship in `bench_fixtures/hi_classroom_refs.txt`. The default `collabora/faster-whisper-small-hindi` path is never changed in code without the config key |
| 6 | RTF > 1 backlog on the pilot CPU | — | **B2**: watchdog behaviour unchanged (auto-shortens max_utt 12→9→7 s); a one-time advice line now prints with it (`language: "hi"` for Hindi-medium periods / `model_size: "base"`). Script-sanity stays budget-gated, max one re-decode per utterance, no decode chains |
| 7 | "can we fine-tune on our classroom?" | — | **B3**: opt-in OFFLINE recipe only — `docs/FINETUNE_HI_OPTIONAL.md` (data layout, eval-first gate, LoRA/PEFT preferred, CT2 export, consent/retention limits). Nothing runs at listener startup; EN regression gate: "one half is greater than three quarters" must still pass stitch + MathGuard on the stock route (unit-tested) |

## Tests (all green before release)

| Suite | Result |
| --- | --- |
| Shipped offline suite `tests/test_listener.py` | **134/134** (was 84; +50 v6.2.2 checks) |
| Extended unit suite | **50/50** |
| AST audit (read-before-assign of module globals) | clean |
| New worker regressions | prev `"one half is greater than"` + new `"three quarters."` → stitched, NOT short-noise ignore · standalone `"three quarters"` allowlisted → posted · `"तीन चौथाई"` → posted · random short non-math → still dropped · no stitch when the tail has no cue · stale tail never stitches · prompts default OFF and never cross routes · `hi_model` override parsed with clean-default reset |

## Config (all optional; defaults preserve v6.2.1 behaviour)

```json
"listener": {
  "math_initial_prompt": false,
  "hindi_classroom_prompt": false,
  "stitch_tail_words": 6,
  "stitch_window_s": 12,
  "hi_model": null
}
```

## Verify on your machine

English (the exact production case): say **"One half is greater than
three quarters."** once normally, then once **with a pause after
"than"** — both must end in ONE `✅ Teacher said: one half is greater than
three quarters` (the paused case shows `🧩 Stitched …`), and MathGuard
Tier-3 must flag the false claim. Hindi: record
`एक आधा तीन चौथाई से बड़ा नहीं है` with `--save-audio`, then
`python mic_listener.py --bench saved_audio/utt_*.wav --ref "एक आधा तीन चौथाई से बड़ा नहीं है"`
— WER + RTF print, no crash, `small-hi` still routes HI.
