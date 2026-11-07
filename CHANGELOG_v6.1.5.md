# Changelog — v6.1.5 (the real "Hindi phoneme soup" fix: the MODEL)

## Root cause (measured, not guessed)
Stock Whisper **small** scores **67.4% WER on FLEURS Hindi** — it cannot
transcribe Hindi at all (it produced soup even on clean studio audio in our
bench). English was never broken because the same model handles English
fine. No decode tuning can fix a model that cannot decode the language;
v6.1.4's decode-only changes were reverted where they did not pay.

## Fixes
1. **Hindi-grade model, same speed** — new default `model_size: "small-hi"`
   pairs stock `small` (English) with
   `collabora/faster-whisper-small-hindi` — the SAME 244M size, fine-tuned
   on ~3000 h of Hindi; FLEURS Hindi WER **7.2% vs 67.4%** stock. First run
   downloads it once (~0.5 GB), then fully offline; graceful fallback to
   stock `small` if the download fails.
2. **Language router** — a ~1-2 s probe per chunk on the stock model routes
   `hi` chunks to the Hindi model and `en` chunks to stock (the path that
   always worked). Confident probes decide; uncertain ones follow the
   majority of the last 3 probes; `ur` detections route to the Hindi model
   (Hindi/Urdu detector confusion); third-language probes never poison the
   state. When the CPU falls behind (rolling RTF > 0.85) probing is skipped
   and the last known language is reused. A cold-start Hindi chunk decoded
   blind by stock is re-decoded once on the Hindi model (budget permitting).
3. **Word-boundary chunks (proven now)** — the cap fires at 12 s and cuts
   at the quietest 30 ms frame in the tail; the tail is carried into the
   next chunk, so chunks start/end between words. On bench Hindi: sentence
   recovery 0.48 -> 0.72 combined with the Hindi model.
4. **Honest decode retune** — temperature [0.0, 0.2] (the 0.4 level of
   v6.1.4 cost +15-40% wall time with zero quality gain); `beam_retry`
   default 0 (could not rescue stock Hindi, doubled latency; still opt-in);
   repetition_penalty stays off.
5. **Honest console** — chunks rejected by the confidence gate now print a
   visible 🔇 line (before: silence); the printed/sent confidence is the
   duration-weighted value used for decisions; `--test-wav` replays WAVs
   through the exact live engine (no mic/credentials needed) and shows the
   Hindi-model comparison when a clip probes as non-Hindi.
6. Kept from v6.1.4: Devanagari-safe wellbeing lexicons (no false "डर"
   events from garble), floor auto-boost, --save-audio.

## Measured on bench Hindi/English (2-core CPU, Whisper small int8)
| path | conf | sentence recovery | RTF |
| --- | --- | --- | --- |
| v6.1.1 stock (10 s mid-word cuts) | -0.57 | 0.48 | 0.87x |
| v6.1.5 Hindi steady state | **-0.25** | **0.72** | **0.61x** |
English path is bit-identical to v6.1.1 (same model, same kwargs class).

## Rollback / options
`"model_size": "small"` reverts to the old single stock model;
`"model_size": "base"` if the CPU cannot keep up; `"language": "hi"` pins
the Hindi model for fully Hindi-medium lessons (skips probing).
