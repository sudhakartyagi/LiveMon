# Changelog — v6.1.6 (the "first chunk works, then nothing" fix)

## Symptom (your log, v6.1.5)
One ✅ line (conf -0.22), then SEVEN "⚠️ Speech is faster than
transcription", two "🔇 …rejected every segment", silence. ASR took
28.9 s for an 8.5 s utterance while the teacher kept talking; the
12-slot queue overflowed and the OLDEST utterances were dropped;
survivors started mid-sentence and were rejected whole.

## What was measured (2-thread bench, Hindi fine-tune + stock small)
| change | effect (measured) |
| --- | --- |
| drop math hotwords (both routes) | HI conf -0.60 -> -0.10, sentence recovery 0.33 -> 0.83; EN RTF 2.13 -> 0.23, rejected chunks 3/5 -> 0 |
| without_timestamps=true | ~30% faster decode; nothing downstream used timings |
| temperature retry kept at [0.0, 0.2] | costs nothing on clean chunks |
| compression_ratio_threshold 2.4 -> 3.5 | long merged Hindi measured cr 2.5 on CORRECT text — at 2.4 the internal retry fired, doubled cost and emitted the loop it tried to avoid (cr 8.6) |
| merge 3 queued chunks into one decode | 1.52x faster than separate decodes |
| VAD kept ON | without it the first words of a chunk could vanish (recovery-min 0.48 vs 0.63) |
| no_repeat_ngram_size=4 | REJECTED — it deleted legitimate repeated Hindi words ("दो भाग में से एक भाग" -> "दो भा में एक माघ") |

## Fixes
1. **NO-DROP backlog merger** — after finishing a decode, everything
   already waiting in the queue is merged into ONE decode (up to
   listener.merge_max_s, default 25 s, 0.35 s gaps). On a CPU that
   decodes slower than the teacher speaks, speech now arrives late but
   complete — v6.1.5 DROPPED it. A ⏳ line shows the catch-up; the 👂
   heartbeat shows the queue depth.
2. **Faster decode (RTF 0.61 -> 0.31 on the bench)** — hotwords OFF by
   default (they poisoned BOTH models; opt back in with
   listener.hotwords — they force timestamps ON on the English route,
   the hot + no-timestamps combo measured recovery 0.00),
   without_timestamps on, compression_ratio_threshold 3.5.
3. **Seam-overlap trim** — cap-split carries share a few words with the
   next chunk; >= 4 matching seam words are trimmed before posting
   (listener.overlap_trim). Exact repeats are still suppressed.
4. **Routing that survives being behind** — a probe costs ~1.1 s
   constant (CT2 pads to 30 s; slicing audio saves nothing), so while
   behind the router probes every 3rd idle job AND the moment the
   backlog clears — a switch to English is now noticed instead of being
   transliterated through the Hindi model. Cold-start blind decodes are
   also checked with SCRIPT evidence: stock small cannot decode Hindi
   (67% WER), so Devanagari in its output means Hindi audio whatever
   the detector claimed ('la'/'nn'/'ur' misprobes measured), and the
   'ur' alias now triggers the Hindi rescue too.
5. **Generator bug (v6.1.5 latent)** — the cold-start inspection consumed
   Whisper's one-shot segment generator, so the worker could receive an
   exhausted iterator and print "rejected every segment" on a good
   decode. Segments are materialized once now.
6. **Phrase-loop guard** — looks_degenerate now catches 2-3 word phrase
   loops ("उनके बारह उनके बारह उनके बारह" — the exact pattern in your
   logs), not only single-word loops.
7. **Windows console** — stdout/stderr reconfigured to UTF-8: no more
   leading "�" on Hindi lines in cp1252 terminals.
8. **Robust worker** — counters self-seed; unsupported faster-whisper
   kwargs (old builds) are auto-stripped instead of failing the chunk.

## Verified before shipping
- 48/48 offline unit tests (merger, seam trim, router policy, kwarg
  auto-strip, config parsing, the "__unset__ echo" regression).
- 10/10 E2E checks on REAL models replaying your exact failure mode
  (whole lecture queued before the worker starts): zero utterances
  dropped, merged 27.8 s Hindi job decoded in 5.3 s at conf -0.08,
  every sentence recovered, no errors; English-after-Hindi correctly
  flips back to the stock route.
- CLI smoke: python mic_listener.py --test-wav (English clip decoded
  whole at conf -0.27; pinned-'hi' Hindi clip at conf -0.10).

## Rollback / options
"model_size": "small" reverts to the old single stock model;
"model_size": "base" if the CPU still cannot keep up; "language": "hi"
pins the Hindi model for fully Hindi-medium lessons; "hotwords": "…"
opts back into vocabulary biasing (measured: slower, less stable).
