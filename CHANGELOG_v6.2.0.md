# Changelog — v6.2.0 (pro-grade Hindi pipeline: janitor, continuation, script sanity, bench)

Every fix below maps to a symptom in the pilot logs.

## Symptom → fix

| # | Log symptom | Root cause | v6.2.0 fix |
| --- | --- | --- | --- |
| 1 | Garbled Devanagari, mid-word cuts | cap-cut at the quietest single frame could slice INSIDE a word | **Word-gap cuts**: a cap-cut now requires a REAL pause (≥ ~90 ms of consecutive quiet frames, `listener.cap_gap_frames`), cut lands mid-gap; quietest-frame only as last resort (carry still loses no audio) |
| 2 | Hallucination loops shipped ("उनके बारह" ×3, "I'm a good boy…" ×2) | loops were only *hinted at*, still posted | **Janitor collapses 1–3-word phrase loops to one instance** before posting (loops can no longer ship); loop guard extended to phrase loops |
| 3 | Residual non-speech / symbol noise | meta tokens & punctuation-only output passed the gates | **Meta tokens stripped** (`[Music]`, `(applause)`, `【silence】`…), **symbol-only output dropped**, min-words/confidence/compression gates unchanged |
| 4 | Mid-sentence chunk starts lose context | chunks decoded with no left context | **Continuation prompt**: last 8 words of the previous GOOD transcript (conf ≥ −0.5) passed as `initial_prompt`; echo stripped after decode; never continues from garble or loops (`listener.carry_prompt_words`, bench-measured neutral-to-positive) |
| 5 | Language routing instability / transliteration soup | misroutes survived when probes were skipped | **Script sanity on every decode** (EN route → dominant Devanagari, or HI route → dominant Latin ⇒ one budget-gated re-decode on the other model, better conf wins); `ur` misprobes rescue to Hindi; backlog-clear + every-3rd-idle probes (v6.1.6) kept |
| 6 | ASR slower than real time; "Speech is faster than transcription" | decode cost + queue overflow | (v6.1.6) **no-drop merger** kept; NEW **adaptive watchdog**: sustained RTF > 1 auto-shortens the cap 12→9→7 s so decodes stay small (`listener.adaptive_max_utt`) |
| 7 | No honest way to pick a model for YOUR room | no WER tooling | **`--bench WAV --ref "text"`**: ranks base/small/small-hi by word-level WER + RTF **through the production path** (real assembler chunking + gates + janitor); Devanagari-safe tokens; spoken digits normalized ("three"≡"3"); `--ref "a \| b"` maps 1:1 to multiple WAVs |
| 8 | Config drift between runs | overrides used keep-current semantics | **Defaults registry**: `apply_overrides({})` (or no listener section) always lands on clean module defaults |
| 9 | `�` on Windows consoles | cp1252 stdout | (v6.1.6) UTF-8 reconfigure kept |

## Route-specific prompt policy (measured, not guessed)
* Hindi fine-tune: prompts/hotwords POISON it (conf −0.60 vs −0.10, sentence recovery 0.33 vs 0.83) → the HI route receives NO hotwords and NO domain prompt. Continuation prompts (Devanagari tail of the previous chunk) are the only prompt the HI route accepts.
* English stock route: `listener.initial_prompt` is available and measured harmless-to-helpful (conf −0.166 → −0.124, recovery unchanged); `listener.hotwords` stays opt-in (measured RTF 2.13 vs 0.23 without, 3/5 chunks rejected).

## Measured (2-thread bench box; espeak synthetic audio = worst case)
| bench (production path) | base | small | small-hi |
| --- | --- | --- | --- |
| English lecture WER | 55.0% | **37.5%** | **37.5%** (RTF 0.46×) |
| Hindi lecture WER | 92.6% | 100% (Latin soup) | **57.4%** (RTF 0.63×, conf −0.13) |
| Hindi sentence recovery (assembler chunks) | — | — | 0.73–0.83 |
| merged 27.8 s Hindi job (E2E replay of pilot failure) | — | — | 5.3 s decode, conf −0.08, zero drops |

⚠️ These WERs are on robotic espeak audio — real classroom speech scores much better. Measure YOUR room: `--bench saved_audio/utt_*.wav --ref "…"`.

## Verified before shipping
* **126/126 offline tests green**: 76 in `tests/test_listener.py` (shipped: noise floor & digital zeros, assembly, word-gap cuts, janitor, seam trim, WER, script checks, route kwargs, overrides, no-drop merger, loop-collapse-before-post, symbol-only drop) + 50 in the extended suite (router probe policy, script sanity both directions, kwarg auto-strip, regressions).
* 10/10 E2E checks on real models replaying the pilot failure mode (whole lecture queued before the worker starts): zero drops, merger batches, router escapes sticky-hi, English never transliterated.
* `--bench` CLI verified end-to-end on both languages with per-file references.
* Packaged zip: py_compile + the full offline suite re-run against the PACKAGED file + `--test-wav` smoke.

## Rollback / options
`"model_size": "base"` (fastest), `"adaptive_max_utt": false`, `"carry_prompt_words": 0`, `"script_sanity": false`, `"language": "hi"` (pin Hindi, skip probing) — all in the `listener` section of config.json.
