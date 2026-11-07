# v6.2.1 — Transcriber crash fix ("first sentence works, then nothing")

## The bug you saw

```
Exception in thread transcriber:
  ...
  File "...\mic_listener.py", line 1806, in transcription_worker
    and MAX_UTTERANCE_FRAMES > min_frames):
UnboundLocalError: cannot access local variable 'MAX_UTTERANCE_FRAMES'
where it is not associated with a value
```

After that traceback, the console kept printing `✂️ Long stretch…`,
`👂 listening… … ⏳ 2 queued` — but **no transcript ever appeared again**.

## Root cause (deep look)

The v6.2.0 **CPU watchdog** (the feature that shortens the 12 s chunk cap
to 9 s / 7 s when your CPU decodes slower than real time) **assigned**
`MAX_UTTERANCE_FRAMES` inside `transcription_worker()` without declaring
`global MAX_UTTERANCE_FRAMES`. Python therefore treated the name as a
function-local variable everywhere in that function, and the FIRST read of
it (the watchdog comparison at line 1806) raised `UnboundLocalError`
**before any assignment had run**.

Sequence on your machine:

1. First utterance decoded (slowly — your CPU ran RTF ≈ 3.4, i.e. 28.9 s
   of ASR for 8.5 s of audio).
2. The rolling RTF crossed the watchdog trigger → the watchdog comparison
   read `MAX_UTTERANCE_FRAMES` → `UnboundLocalError`.
3. The exception killed the whole **transcriber thread**. Capture kept
   running (that's why you still saw `✂️` splits and `⏳ queued`), but
   nothing was ever transcribed again — "initially it recognize but not
   after that".

## Fixes in v6.2.1

1. **`global MAX_UTTERANCE_FRAMES`** added to `transcription_worker` —
   the watchdog now updates the real module-level cap, which the
   assembler also reads every frame, so shortening the cap actually
   takes effect in the capture pipeline (in v6.2.0 the watchdog feature
   was silently broken even when it didn't crash).
2. **Watchdog block guarded** — a watchdog failure now costs one
   `⚠️ Watchdog check skipped:` line, never an utterance.
3. **Transcriber supervisor** — the worker now runs under a supervisor
   thread. If the worker EVER dies for any reason, it is restarted
   within a second and everything still queued is transcribed:
   `⚠️ Transcriber thread died and was restarted automatically (#1) — N
   chunk(s) still queued and safe; speech keeps flowing`.
   The session summary reports `worker restarts`.
4. **Shutdown sentinel fix** — the backlog-drain used to consume and drop
   the `None` shutdown sentinel, leaving the worker polling an empty
   queue forever after Ctrl+C. It is now preserved and the worker exits
   cleanly after finishing the current job.
5. **Cold-start Hindi rescue widened** — the blind stock decode fails two
   ways on Hindi audio: low confidence, or *confident junk* (measured on
   a merged Hinglish chunk: language detected as `mn`, one Khmer-script
   repetition loop, cr 12.0, avg_logprob **−0.25** — a good-looking score
   for garbage). The rescue now fires whenever stock produces nothing
   that survives the confidence gate, and the Hindi fine-tune's answer
   wins only if it is shippable Hindi (Devanagari present) — the worker's
   gate still judges everything that ships, so junk can never reach the
   API.

## Verification (all green before release)

| Check | Result |
| --- | --- |
| AST audit for read-before-assign of module globals | clean |
| Shipped offline suite `tests/test_listener.py` | 84/84 |
| Extended unit suite (`test_v616_units_packaged.py`) | 50/50 |
| New regression: worker under sustained RTF 3.4 (your crash) | survives, drains queue, cap 12→9 s |
| New regression: decoder exception mid-session | worker skips, continues |
| New regression: forced thread death | supervisor restarts exactly once, queued speech transcribed |
| Real faster-whisper E2E (router mode, both models) | crash condition + quality path PASS |

## What to expect after updating

- The traceback above cannot recur; if anything else ever kills the
  transcriber you'll see ONE warning line and transcription continues.
- When your CPU falls behind you'll now actually see the watchdog work:
  `🌡 CPU is behind (RTF …) — max chunk shortened to 9s …`
- If speech still arrives late on long lessons, the honest fix on this
  CPU class is a smaller model — add this to `config.json`:
  `"listener": { "model_size": "base", "language": "hi" }`
  (`small-hi` is more accurate but needs a faster CPU for real-time).
