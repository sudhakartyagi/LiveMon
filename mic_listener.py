#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mic_listener.py — Pro-tier continuous classroom listener (classroom_copilot v5.0)

WHAT CHANGED VS THE OLD LISTENER (and why words stop being missed)
  1. Google free API -> faster-whisper running LOCALLY.
     Free, offline, accent-proof, handles Hindi/Hinglish + math vocabulary.
     This is the single biggest accuracy upgrade.
  2. Fixed energy_threshold (the "can't hear you / hears the fan" problem)
     -> adaptive noise floor that tracks the room continuously (percentile of
     the last ~3 s of background frames). No more threshold=400 wall.
  3. Crude phrase chopping -> proper utterance assembly with a 390 ms
     PRE-ROLL buffer. Word onsets are no longer clipped — the #1 cause of
     "wrong first words" ("...sing to me or just was").
  4. Blind transcription -> Silero VAD (inside faster-whisper) + confidence
     filters kill Whisper hallucinations on silence
     ("Thanks for watching!", "Okay.", repeated loops).
  5. Old listener STOPPED listening while transcribing -> now capture,
     gating and transcription run on separate threads with queues, so words
     spoken during inference are still captured and queued.
  6. Duplicate suppression (Whisper loop guard), retrying API posts,
     --list-mics, and optional config.json overrides.
  7. v5.7: sends ASR confidence (avg log-prob) so the backend can gate
     tier-3 corrections; default hotwords bias Whisper toward Class 4-5
     math vocabulary; 1.2 s trailing silence so words are never clipped;
     rich response printing (events, proposals, math verdicts).
  8. v6.1.6: NO-DROP backlog merger (queued utterances decode as ONE job,
     so slow CPUs run late but never lose speech), hotwords off by
     default (bench: they poisoned BOTH models), without_timestamps,
     seam-overlap trim, probe-every-3rd-job-when-behind, UTF-8 console.
  9. v6.2.1: CRASH FIX — the v6.2.0 CPU watchdog updated the chunk cap
     WITHOUT a `global` declaration, so the first slow-CPU decode raised
     UnboundLocalError and killed the transcriber thread: the first
     sentence transcribed, then everything stayed '⏳ queued' forever.
     Fixed, the watchdog block is guarded, and a supervisor restarts the
     worker automatically if it EVER dies (queued speech is kept).
     Also: the shutdown sentinel is no longer swallowed by the backlog
     drain, and the cold-start Hindi rescue now also fires when the blind
     stock decode simply FAILED badly (not only when the junk looked
     Hindi) — the rescue must produce Devanagari and beat stock to win.
 10. v6.2.2: MATH TAIL RESCUE — in the pilot log "…one half is greater
     than" printed fine but the next chunk died as "⚠️ Ignored short
     noise: 'three quarters.'": the claim was split across chunks and the
     tail dropped, so MathGuard never saw the full statement. The last
     words of the previous ACCEPTED transcript are now stitched in front
     of a chunk that continues an incomplete cue (EN+HI lists), known
     math fragments are never dropped for length, and optional math /
     Hindi-classroom prompts exist for both routes (OFF by default).
     Hindi bench fixtures and an opt-in fine-tune recipe are included.
 11. v6.2.3: LANGUAGE LOCK + EXPERIENCE LEARNING LOOP.
     - listener.language "en" | "hi" | "auto" (default auto): "en" NEVER
       routes a chunk to the Hindi model (accented English math no longer
       comes out as Devanagari transliteration soup), "hi" pins the
       fine-tune and skips EN-probe thrash. Math pilot -> "en";
       Hindi-medium lesson -> "hi".
     - Fewer false empty rejects, honestly labelled: every silent chunk
       now logs a reason code. When the audio was REAL speech (>= 1.2 s)
       and every segment fell to the confidence gate, ONE budget-gated
       re-decode runs with slightly lower decode thresholds — max once
       per utterance; the confidence gates themselves are never disabled.
     - Experience learning loop (listener/experience_store.py, local
       stdlib SQLite): every ingest attempt, short drop and Tier-3
       proposal is recorded; teacher Accept/Reject/Edit (dashboard
       callback or a GET /lesson/feedback endpoint when present) lands in
       the experience_events table. Accept appends the phrase pattern to
       the allowlist file (short fragments stop dying as noise), Reject
       records a false pattern (NEVER added to the allowlist), Edit
       stores the (asr -> teacher) pair for later offline eval/train.
     - NOT auto-trained: hotwords stay OFF by default, no runtime
       fine-tune, no silent weight updates — the loop only ever writes
       readable pattern/text files that you control.
 12. v6.3.0: PILOT WORKBENCH — presets, structured drop reasons, and a
     modular codebase (the god-file is split; behaviour preserved).
     - PRESETS (config listener.preset or --preset): "math_en" = English
       math pilot with a HARD LOCK (stock EN model only — the Hindi model
       is never loaded and never called), "hindi_class" = Hindi-medium
       lesson (hi model pinned, EN probes skipped, no EN math hotwords),
       "auto" = the measured router (default, unchanged behaviour).
     - STRUCTURED DROP REASONS (spec P2 #9): every dropped chunk now
       prints reason=short_noise | low_conf | no_speech | duplicate |
       prompt_echo, and short drops carry the code into the experience
       store (report shows drops by reason).
     - MODULES (spec P3 #12): listener/{reasons,presets,audio_gate,
       assembler,janitor,math_stitch,asr_router,experience_store}.py +
       tools/experience_report.py; mic_listener.py remains the main
       listener loop / composition root. Capture never blocks on ASR;
       queue + merge + adaptive max_utt + watchdog + supervisor are all
       preserved and regression-tested.
     - math-stitch hardened: more incomplete-cue cues ("is greater",
       "इससे बड़ा", "बराबर है") and a wider spoken-fraction allowlist
       ("three by four", "one upon two", "एक बटा दो"…).
     - soft_retry (the v6.2.3 empty-retry rescue, renamed; the old
       listener.empty_retry key still works) is an explicit, documented
       flag: ONE budget-gated re-decode per utterance, never when RTF>1.

PIPELINE
  mic (16 kHz mono) -> frame queue -> adaptive gate + utterance assembler
      (390 ms pre-roll, ~1.2 s trailing silence closes an utterance)
    -> transcription queue -> faster-whisper (VAD on, greedy beam, hotwords)
    -> confidence / hallucination / duplicate filters
    -> POST {API_URL}/audio/ingest   (JSON contract + confidence field)

SETUP (Windows PowerShell)
  pip install -r requirements_audio.txt
  python mic_listener.py --list-mics     # optional: see / pick a microphone
  python mic_listener.py --meter         # optional: live mic level vs. gate
  python mic_listener.py

  First run downloads the Whisper model(s) once ("small-hi" = stock small
  + the Hindi fine-tune, ~1 GB total), then it is fully offline. On a
  weak laptop use "base"; on a GPU use "medium"/"large-v3".

  Offline check without a mic (transcribe WAVs through the real engine):
  python mic_listener.py --test-wav saved_audio/utt_*.wav

CONFIG (optional — config.json keeps working exactly as before)
  NOTE: config.json is NOT shipped in the zip — it holds YOUR personal
  credentials (JWT token, class_id, lesson_id) and is generated on this
  machine by setup_credentials.py, or automatically on the first
  start_all.py run. Never commit it to git.

  {
    "token": "...", "class_id": "...", "lesson_id": "...",
    "api_url": "http://localhost:8000",
    "listener": {
      "input_device": "WO Mic",
      "preset": "auto",          math_en | hindi_class | auto (v6.3.0;
                                 --preset on the CLI wins)
      "model_size": "small-hi",
      "beam_size": 1,
      "cpu_threads": 0,
      "block_ms": 200,
      "start_margin_db": 6,
      "heartbeat_s": 30,
      "language": "auto",        "en" | "hi" | "auto" (v6.2.3 session lock)
      "hotwords": null,
      "min_words": 3,
      "max_utt_s": 12,
      "beam_retry": 0,
      "repetition_penalty": 1.0,
      "without_timestamps": true,
      "vad_filter": true,
      "probe_every": 3,
      "merge_max_s": 25,
      "overlap_trim": 4,
      "cap_gap_frames": 3,
      "carry_prompt_words": 8,
      "initial_prompt": null,
      "math_initial_prompt": false,
      "hindi_classroom_prompt": false,
      "stitch_tail_words": 6,
      "stitch_window_s": 12,
      "hi_model": null,
      "en_model": null,
      "script_sanity": true,
      "adaptive_max_utt": true,
      "soft_retry": true,        one budget-gated re-decode per dropped
                                 utterance (v6.3.0 name; empty_retry alias)
      "experience": true,
      "experience_db": "experience.db",
      "feedback_url": null
    }
  }

PERFORMANCE (v6.1.6 — every number below is measured on the bench)
  - NO-DROP BACKLOG MERGER: on a CPU that transcribes slower than the
    teacher speaks, the worker now MERGES everything waiting in the queue
    into ONE decode (up to listener.merge_max_s, default 25 s) instead of
    dropping the oldest utterances when the queue filled. Speech spoken
    during a slow decode arrives late — never lost (v6.1.5 DROPPED it:
    that was the user-visible "first sentence works, then nothing" bug).
    A ⏳ line shows the catch-up. Merged decodes also measured 1.52x
    faster than decoding the same chunks separately.
  - Decode retune (bench, Hindi fine-tune, 36 s audio): the math-hotword
    prompt poisoned BOTH models — Hindi conf -0.60 vs -0.10 and sentence
    recovery 0.33 vs 0.83 WITH hotwords; English RTF 2.13 vs 0.23 and 3/5
    chunks rejected vs 0. Hotwords are therefore OFF by default (opt in
    with listener.hotwords; they force timestamps back ON — the hot +
    no-timestamps combo measured recovery 0.00). Timestamp tokens are
    used by nothing downstream and cost ~30% decode time —
    without_timestamps is on by default. Together: RTF 0.61 -> 0.31.
  - Language probe policy: a probe costs ~1.1 s CONSTANT (CT2 pads the
    mel to 30 s — probing a short slice saves nothing). Keeping up
    (RTF <= 0.85): probe every chunk. Behind: probe every 3rd job while
    the queue is empty, sticky language in between, so a switch to
    English is still noticed without deepening the backlog (v6.1.5
    stopped probing entirely once behind, which froze the router on the
    first language it saw).
  - beam_size 1 (greedy): ~2-4x faster than beam 5, near-identical text
    on short classroom utterances. cpu_threads 0 = auto: reserves cores
    for audio capture. block_ms 200: fewer, bigger callbacks.
  - Still slower than real time? v6.1.6 keeps everything (late but
    complete). For real-time text, "model_size": "base" (~2-3x faster).
    See config.tuned.example.json.
  - Deaf even when you speak? v6.1.2 relaxed the gate (start_margin_db 8->6)
    and prints a 👂 heartbeat every 30 s showing mic peak vs. gate and
    the queue depth. Run "python mic_listener.py --meter" for live levels.

ACCURACY (v6.2.2 — the math tail rescue: "Ignored short noise: 'three
quarters.'")
  - Symptom (production log): "…one half is greater than" printed fine and
    the next chunk "three quarters." died at the min-words gate — the claim
    was split, the tail dropped, and MathGuard never saw the statement.
  - STITCH (A1): the last N words (listener.stitch_tail_words, default 6,
    spec range 3-8) of the previous ACCEPTED transcript sit in a stitch
    buffer. When a new chunk continues an incomplete cue — the tail ends
    with one ('greater than', 'equals', 'से बड़ा', 'दो तिहाई' …) or the new
    text starts with one ('greater than three quarters' after a cut) — the
    tail is stitched in front of it BEFORE the min-words filter and before
    the API send; the janitor runs once on the combined text and ONE
    combined transcript is sent (MathGuard sees the whole claim). A tail
    older than listener.stitch_window_s (12 s) never stitches.
  - ALLOWLIST (A2): known math fragments ('three quarters', 'one half',
    'तीन चौथाई', 'एक आधा', 'तीन चौथाई भाग', number×fraction combinations…)
    are never dropped for being below MIN_WORDS. Symbol-only,
    punctuation-only and hallucination output are still rejected — the
    allowlist only waives the word count.
  - SAFER CUTS (A3): cap-cuts already prefer the LONGEST real pause in the
    tail window (v6.2.0 word-gap rule), which skips the short pause after
    a cue whenever any sentence-length pause exists; when the teacher
    truly never pauses, the cut lands wherever it must and the stitch
    above repairs the seam. The measured cut logic is unchanged.
  - OPTIONAL PROMPTS (A4, OFF by default): "listener.math_initial_prompt":
    true adds a fractions prompt to the ENGLISH route;
    "listener.hindi_classroom_prompt": true adds a Hindi classroom prompt
    to the HI route only. Never applied across routes; both default false
    (prompts measured to hurt the Hindi fine-tune).
  - HINDI MODEL OVERRIDE (B2/B3): "listener.hi_model":
    "local/small-hi-classroom-v1" points the HI route (and the 'small-hi'
    bench candidate) at a locally fine-tuned model. Offline opt-in recipe:
    docs/FINETUNE_HI_OPTIONAL.md; Hindi bench lines: bench_fixtures/.

ACCURACY (v6.2.0 — pro-grade janitor + continuation + script sanity)
  - Word-gap chunking: a cap-cut now requires a REAL pause (>= ~90 ms of
    consecutive quiet frames in the tail window) and lands mid-gap, so no
    chunk ever starts or ends inside a word unless the teacher literally
    never pauses (then the quietest frame is the least-bad cut and the
    carry still loses no audio).
  - Left-context continuation: the last 8 words of the previous GOOD
    transcript (conf >= -0.5) are passed as Whisper initial_prompt, so a
    chunk that starts mid-sentence continues in context. The prompt echo
    is stripped after decode and the seam trim is a second net. Never
    continues from garble or a collapsed loop.
  - Script sanity (both routes): a decode whose output script contradicts
    its route (EN route -> dominant Devanagari, HI route -> dominant
    Latin) is re-decoded once on the other model when the RTF budget
    allows; better confidence wins.
  - Janitor before posting: meta tokens ([Music]/(applause)/…) stripped,
    1-3-word phrase loops COLLAPSED to one instance (a hallucination loop
    can no longer ship to the API), symbol-only/punctuation-only output
    dropped, min-words, confidence and compression gates unchanged.
  - Route-specific domain prompt: listener.initial_prompt biases the
    ENGLISH route toward Class 4-5 math vocabulary — the Hindi route
    never receives prompts (they measurably hurt the fine-tune).
  - Adaptive stability: sustained RTF > 1 automatically shortens the cap
    (12 -> 9 -> 7 s) so decodes stay small; one-time console notice;
    listener.adaptive_max_utt = false to disable.
  - --bench: python mic_listener.py --bench saved_audio/utt_*.wav \
        --ref "the exact words spoken"
    ranks base / small / small-hi by word-level WER + real-time factor on
    YOUR recording — the honest way to pick a model for your room.

ACCURACY (v6.1.6 — the "first chunk works, then nothing" fix)
  - Symptom (user log, v6.1.5): one ✅ line (conf -0.22) then SEVEN
    "⚠️ Speech is faster than transcription" (= oldest utterances dropped),
    two "🔇 …rejected every segment", silence. ASR took 28.9 s for an
    8.5 s utterance while the teacher kept talking; the 12-slot queue
    overflowed; survivors started mid-sentence and got rejected whole.
  - FIX 1 — never drop speech: queued utterances merge into one decode
    (see PERFORMANCE). The "Speech is faster" drop warnings should
    disappear; text appears late while catching up, then clears.
  - FIX 2 — less backlog in the first place: hotwords off by default,
    without_timestamps on, Hindi route never receives the hotword prompt.
  - FIX 3 — seam-overlap trim: cap-split carries share a few words with
    the next chunk, so the same words could print twice; a >= 4-word
    match at the seam of consecutive transcripts is trimmed before
    posting. Exact repeats are still suppressed as before.
  - FIX 4 — routing that survives being behind: probe every 3rd job
    (queue empty) instead of never, so a long English stretch no longer
    sticks to the Hindi model (which transliterates English into
    Devanagari — the original soup bug).
  - FIX 5 — Windows console: stdout/stderr are reconfigured to UTF-8, so
    cp1252 terminals show Devanagari instead of leading "�".
  - VERIFY IT YOURSELF, no mic needed:  python mic_listener.py --test-wav
    transcribes any WAV(s) through the exact same engine and prints
    text + confidence — record a lesson with --save-audio, then replay.

ACCURACY (v6.1.5 — the real "Hindi phoneme soup" fix: the MODEL)
  - Symptom: English came out PERFECT ("one half is greater than three
    quarters", conf -0.24…-0.62) while Hindi on the SAME mic came out as
    phoneme soup ("चवक सुता है कोंषे पीडर्द है", conf -0.77…-1.10).
  - ROOT CAUSE (measured, not guessed): the stock Whisper 'small' model
    scores 67% WER on the FLEURS Hindi benchmark — it is simply not able
    to transcribe Hindi (its Hindi came out as soup even on CLEAN studio
    audio in our bench). No decode tuning can fix a model that cannot
    decode the language. English was never broken because the same model
    handles English fine.
  - FIX 1 — Hindi-grade model, same speed: "small-hi" is now the default.
    It pairs the stock small model (for English) with
    collabora/faster-whisper-small-hindi — the SAME 244 M-parameter size,
    fine-tuned on ~3000 h of Hindi (Shrutilipi, IndicVoices-R, Common
    Voice, FLEURS…). FLEURS Hindi WER: 7.2% vs 67.4% stock. First run
    downloads it once (~0.5 GB), then fully offline. If the download or
    the model file ever fails, the listener falls back to stock 'small'
    automatically and says so.
  - FIX 2 — language router (both models are loaded in "small-hi" mode):
    every chunk gets a cheap language probe on the stock model (~1-2 s;
    it detects English reliably, p>=0.94). 'hi' chunks are decoded by the
    Hindi model with language pinned, 'en' chunks by the stock model —
    exactly the behavior that already worked. Uncertain probes (p<0.5)
    follow the majority of the last 3 detections. When the CPU falls
    behind (rolling RTF > 0.85) the probe is skipped and the last known
    language is used, so the router never deepens a backlog.
  - FIX 3 — chunks cut at word boundaries (kept from v6.1.4, now proven):
    the 10 s hard cap used to slice continuous speech mid-phoneme; the
    next chunk restarted mid-word. Now the cap fires at 12 s and cuts at
    the QUIETEST 30 ms frame in the last ~4 s; the tail is carried into
    the next chunk, so every chunk starts and ends between words.
    Measured on Hindi bench audio: sentence recovery 0.48 -> 0.78 when
    combined with the Hindi model (the same chunking on the stock model
    changed nothing — the model has to understand Hindi first).
  - FIX 4 — decode retune (honest, measured):
      * repetition_penalty stays OFF (Devanagari repeats matras inside
        words; the penalty distorted Hindi decode). Override:
        listener.repetition_penalty (1.0-2.0).
      * temperature [0.0, 0.2] — the extra 0.4 level of v6.1.4 measured
        +15-40% ASR time with ZERO quality gain on bench audio; removed.
      * beam_retry now defaults to 0 (off). Bench: re-decoding stock
        'small' at beam 3 could not recover Hindi it cannot parse, and
        on a CPU that is already behind real time it doubled latency.
        Keep it as an opt-in for fast CPUs: listener.beam_retry = 3.
  - FIX 5 — honest console: a chunk whose every segment was rejected by
    the confidence gate now prints a visible 🔇 line (before: silence,
    which looked like "not working"), and the printed/sent confidence is
    the duration-weighted value used for all decisions.
  - FIX 6 — false wellbeing events from garble (kept from v6.1.4): the
    distress lexicon matched डर as a substring inside garbled words
    (पीडर्द -> "डर" cue). Devanagari matras are not \\w, so the old \\w
    boundary guard never worked for Hindi. Devanagari cues now require a
    real Devanagari word start (lexicons.py).
  - VERIFY IT YOURSELF, no mic needed:  python mic_listener.py --test-wav
    transcribes any WAV(s) through the exact same engine and prints
    text + confidence — record a lesson with --save-audio, then replay.
  - Expected on the pilot machine: Hindi conf should rise from
    -0.8…-1.1 to roughly -0.2…-0.5 with real sentences; English should
    stay exactly as good as before (same model, same path as v6.1.1).
    If words are still wrong with GOOD confidence on --test-wav replays
    of --save-audio recordings, the remaining error is mic/room or the
    fine-tune's limit — try model_size "medium" overnight or a USB
    headset mic closer to the teacher.

ACCURACY (v6.1.3 — the "30-second monster utterance" fix)
  - Symptom: "✅ Teacher said: ब्रम्ःपूद्द्दा ब्रम्ःपूद्द्दा ..." with
    "⏱ utterance 30.0s, 🎯 conf -0.59, 🗣 en". A steady sound (fan/AC/
    projector hum) that started AFTER calibration sat ~29 dB above the
    stale noise floor, so EVERY frame counted as speech, the 1.2 s
    silence rule never fired, and only the 30 s hard cap could close an
    utterance. Whisper then got one 30 s mostly-noise blob, misdetected
    the language ('en' for Hindi audio) and looped on repeated garbage
    tokens.
  - Floor auto-boost: the effective floor rises toward the quiet end
    (10th percentile) of the last ~3 s of audio, so a steady hum stops
    counting as speech and the gate can close again. Real speech has deep
    inter-word dips, so talking still holds the gate open.
  - Utterance cap 30 s -> 10 s (listener.max_utt_s, 3-60): text appears in
    seconds, not half a minute later; short chunks transcribe far better.
  - temperature [0.0] only (no hidden 0.2 retries) + repetition_penalty
    1.15 (auto-skipped on older faster-whisper) kills repetition loops.
  - One-time hint when a transcript looks like a repetition loop.
  - NEW --save-audio [dir]: writes every captured utterance as a WAV so
    you can HEAR exactly what Whisper hears — clean audio + bad text =
    model/settings problem; muffled audio = mic/room problem.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from typing import Optional

import httpx
import numpy as np

# v6.2.3: the experience learning loop lives in experience.py next to this
# file. If it is missing, the listener still works exactly as before —
# only the local decision mirror is disabled.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from experience import ExperienceStore, parse_feedback_items
    _EXPERIENCE_OK = True
except Exception:                                   # pragma: no cover
    ExperienceStore = None
    parse_feedback_items = None
    _EXPERIENCE_OK = False

# ---------------------------------------------------------------------------
# v6.3.0: the god-file is split into clean modules (listener/ package).
# mic_listener.py stays the MAIN LISTENER LOOP / composition root: it owns
# the tunables + config + threads, and wires them into:
#   audio_gate / assembler / asr_router / math_stitch / experience_store
# All modules import without faster-whisper or sounddevice, so the unit
# tests run offline on CI (numpy + stdlib only).
# ---------------------------------------------------------------------------
from listener import presets as _presets_mod
from listener.reasons import (SHORT_NOISE, LOW_CONF, NO_SPEECH, DUPLICATE,
                              PROMPT_ECHO, SYMBOL_ONLY, ALL_CODES)
from listener.audio_gate import (frame_dbfs, api_noise_db, downsample_to_16k,
                                 AdaptiveGate)
from listener.assembler import (find_gap_cut as _find_gap_cut,
                                UtteranceAssembler as _AssemblerCore)
from listener.janitor import (clean_transcript, strip_meta_tokens,
                              collapse_repetition, has_letters,
                              script_counts, looks_degenerate,
                              HALLUCINATION_RE)
from listener.math_stitch import (PUNCT_EDGE, word_key as _word_key_mod,
                                  transcript_words as _transcript_words_mod,
                                  ends_with_incomplete_cue,
                                  starts_with_continuation_cue,
                                  math_fragment_allowed as _frag_allowed)
from listener.asr_router import (NO_SPEECH_DROP, LOGPROB_COMBO_DROP,
                                 LOGPROB_HARD_DROP, COMPRESSION_LOOP_DROP,
                                 segment_ok, seg_confidence, raw_confidence,
                                 RouteConfig, WhisperRouter as _RouterCore,
                                 SingleEngine as _SingleCore,
                                 build_transcribe_kwargs as _build_kwargs,
                                 hi_route_kwargs as _hi_kwargs_core,
                                 en_route_kwargs as _en_kwargs_core,
                                 _transcribe_once, detect_language,
                                 LanguageSmoother, wer)

# ---------------------------------------------------------------------------
# Tunables (config.json -> "listener" section can override most of these)
# ---------------------------------------------------------------------------
API_URL = "http://localhost:8000"
CONFIG_FILE = "config.json"

SAMPLE_RATE = 16000          # Whisper's native rate
FRAME_MS = 30                # analysis frame = 30 ms (independent of mic rate)

SPEECH_START_MARGIN_DB = 6.0     # speech starts when frame > floor + 6 dB.
                                 # Was 8 — a teacher 1-2 m from a laptop mic
                                 # often peaks only 7-9 dB above room tone, so
                                 # an 8 dB gate can stay deaf forever.
                                 # Override: listener.start_margin_db
SPEECH_CONTINUE_MARGIN_DB = 3.0  # utterance stays open while > floor + 3 dB.
                                 # Override: listener.continue_margin_db
FLOOR_WINDOW_FRAMES = 100        # ~3 s rolling window for the noise floor
FLOOR_PERCENTILE = 20            # floor = 20th percentile of recent frames
ABSOLUTE_SILENCE_DB = -85.0      # below this = digital dropout, NOT room tone
WARMUP_FRAMES = 66               # 2 s of listening-only calibration at start
PRE_ROLL_FRAMES = 13             # ~390 ms kept BEFORE speech starts
SILENCE_FRAMES_TO_END = 40       # ~1.2 s of quiet closes an utterance
                                 # (teacher mid-thought pauses are 0.8-1.1 s;
                                 # 0.9 s clipped words like "whole tea[m]")
MAX_UTTERANCE_FRAMES = 400       # ~12 s hard cap (v6.1.5; 10 s in v6.1.1,
                                 # 20 s in v6.1.4). The cap cuts at the
                                 # QUIETEST frame in the tail, never
                                 # mid-word, and the tail is carried into
                                 # the next chunk. 12 s keeps decoder
                                 # context without the latency and temp-
                                 # fallback cost of 20 s chunks. Override:
                                 # listener.max_utt_s (3-60 s)
CAP_SEARCH_FRAMES = 133          # when the cap fires, search the last ~4 s
                                 # for the quietest 30 ms frame and cut there
CAP_MIN_EMIT_FRAMES = 200        # never emit less than ~6 s when cap-cutting
                                 # (bounds how small the carried tail can be)
MIN_UTTERANCE_MS = 400           # shorter than this = noise blip

# Floor auto-boost (v6.1.3): a steady noise source that starts AFTER
# calibration used to wedge the gate open forever. The effective floor
# rises to p10(last ~3 s of ALL frames) - 3 dB, clamped, so steady noise
# stops counting as speech within a few seconds.
FLOOR_BOOST_PCT = 10             # percentile of recent audio used as target
FLOOR_BOOST_GAP_DB = 3.0         # keep the floor 3 dB below that target
FLOOR_BOOST_MAX_DB = 50.0        # safety clamp
FLOOR_BOOST_MIN_FRAMES = 20      # need ~0.6 s of history before boosting
MIN_SPEECH_FRAMES = 4            # needs >=120 ms of real speech energy

MODEL_SIZE = "small-hi"          # "small-hi" = stock small (EN) + Hindi
                                 # fine-tune (collabora/whisper-small-hindi,
                                 # FLEURS-Hindi WER 7.2% vs 67.4% stock).
                                 # Also accepts tiny|base|small|medium|
                                 # large-v3 (single-model mode).
                                 # Override: listener.model_size
_HINDI_FT_DEFAULT = "collabora/faster-whisper-small-hindi"
HINDI_FT_MODEL = _HINDI_FT_DEFAULT
                                 # v6.2.2: point the HI route at a locally
                                 # fine-tuned model with listener.hi_model
                                 # (or a top-level "hi_model"), e.g.
                                 # "local/small-hi-classroom-v1". The code
                                 # never changes this without the config key.
EN_STOCK_MODEL: Optional[str] = None
                                 # v6.2.3: opt-in override for the STOCK
                                 # (EN-route) model — same contract as
                                 # hi_model: "listener": {"en_model":
                                 # "local/small-en-classroom-v1"}. None keeps
                                 # the measured default "small". Never
                                 # changed in code without the config key.
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
WHISPER_LANGUAGE: Optional[str] = None   # v6.2.3 session lock: None = auto
                                 # (the measured router, best for Hinglish),
                                 # "en" = every chunk on the stock model (a
                                 # Hindi-model path is NEVER taken — see the
                                 # router), "hi" = every chunk on the Hindi
                                 # model with EN probes skipped.
                                 # "auto" in config normalizes to None.
                                 # Override: listener.language
LANG_ROUTE_PROB = 0.5            # probe p >= this routes hi/en decisively;
                                 # below it, majority of last 3 probes wins.
ROUTE_LANGS = ("hi", "en")       # languages the router can decide between;
                                 # third-language probes (nn, hu, ...) never
                                 # poison the sticky state.
ROUTE_ALIASES = {"ur": "hi"}     # spoken Hindi is often detected as Urdu
                                 # (same register, different script) — route
                                 # it to the Hindi model as well.
HINDI_RESCUE_CONF = -0.7         # cold-start: a blind stock-auto decode that
                                 # turns out to be Hindi below this confidence
                                 # is re-decoded once on the Hindi model.
RTF_SKIP_PROBE = 0.85            # rolling ASR real-time factor above which
                                 # per-chunk probing stops (sticky lang is
                                 # used) so the router never deepens a
                                 # backlog on slow CPUs.
PROBE_EVERY_BEHIND = 3           # even when behind, probe every Nth job
                                 # WHILE THE QUEUE IS EMPTY — a language
                                 # switch is noticed within a few chunks
                                 # without deepening the backlog (a probe
                                 # costs ~1.1 s constant; CT2 pads the mel
                                 # to 30 s, so slicing audio saves nothing).
                                 # Override: listener.probe_every
MERGE_MAX_S = 25.0               # backlog merger: everything waiting in the
                                 # queue is decoded as ONE job up to this
                                 # many seconds (bench: 1.52x faster than
                                 # separate decodes, and nothing dropped).
                                 # Override: listener.merge_max_s (8-60)
MERGE_GAP_S = 0.35               # silence inserted between merged parts
WITHOUT_TIMESTAMPS = True        # nothing downstream uses token timings;
                                 # skipping timestamp tokens measured ~30%
                                 # faster decode and removes a loop source.
                                 # Forced off on a route while hotwords are
                                 # active. Override: listener.without_timestamps
VAD_FILTER_ENABLED = True        # chunks are energy-gated already, but the
                                 # bench showed VAD still protects the chunk
                                 # START (without it the first words of a
                                 # chunk could vanish: recovery-min 0.48 vs
                                 # 0.63). Override: listener.vad_filter
OVERLAP_TRIM_MIN_WORDS = 4       # cap-split carries share a few words with
                                 # the next chunk; when >= this many words
                                 # match at the seam of consecutive
                                 # transcripts, the repeat is trimmed before
                                 # posting. 0 = off.
                                 # Override: listener.overlap_trim
OVERLAP_TRIM_WINDOW_S = 30.0     # seam matches older than this are ignored

# --- v6.2.2: math phrase-tail rescue --------------------------------------
STITCH_TAIL_WORDS = 6            # words of the last ACCEPTED transcript kept
                                 # as the stitch tail (spec range 3-8). When
                                 # a new chunk continues an incomplete cue,
                                 # the tail is stitched in front of it BEFORE
                                 # the min-words filter and before the API
                                 # send, so "one half is greater than" +
                                 # "three quarters." ships as ONE claim.
                                 # 0 = off. Override:
                                 # listener.stitch_tail_words
STITCH_WINDOW_S = 12.0           # a tail older than this never stitches —
                                 # the teacher moved on and joining would
                                 # corrupt two real sentences. Override:
                                 # listener.stitch_window_s
MATH_INITIAL_PROMPT = False      # opt-in ENGLISH-route math prompt (see
                                 # MATH_PROMPT_EN). OFF by default —
                                 # prompts/hotwords measured risky; enable
                                 # per class after a --bench check.
                                 # Override: listener.math_initial_prompt
HINDI_CLASSROOM_PROMPT = False   # opt-in HINDI-route classroom prompt (see
                                 # MATH_PROMPT_HI). The HI route receives NO
                                 # prompt by default (prompts measured to
                                 # hurt the fine-tune). Override:
                                 # listener.hindi_classroom_prompt
MATH_PROMPT_EN = ("Classroom math fractions: one half, three quarters, "
                  "greater than, less than, equals.")
MATH_PROMPT_HI = ("कक्षा गणित: एक आधा, तीन चौथाई, से बड़ा, से छोटा, बराबर। "
                  "शिक्षक हिंदी में पढ़ा रहे हैं।")

# v6.3.0: the incomplete-claim cue tables (EN+HI) and the math fragment
# allowlist moved to listener/math_stitch.py (imported above).


# --- v6.2.3: session language lock -----------------------------------------
# Accepted listener.language values (case-insensitive). "auto" (and null)
# means the measured router; "en"/"hi" pin the session. Anything else
# warns once and falls back to auto — a typo must never wedge the router.
LANGUAGE_ALIASES = {"en": "en", "english": "en",
                    "hi": "hi", "hindi": "hi",
                    "auto": None, "": None, "none": None, "null": None}

# --- v6.2.3/v6.3.0: borderline empty-reject rescue (SOFT RETRY) -------------
# Canonical config key: listener.soft_retry (v6.3.0 name); the v6.2.3 key
# listener.empty_retry is still honored as an alias. When real speech
# (>= EMPTY_RETRY_MIN_MS) produced ZERO shippable segments, decode ONCE
# more with slightly lower decode thresholds before giving up — max once
# per utterance, skipped when the CPU is behind (rolling RTF > 1). The
# confidence gates themselves are never disabled — the retry only widens
# the window a hair and every original gate still judges the result.
EMPTY_RETRY = True               # Override: listener.soft_retry (or
                                 #            listener.empty_retry, legacy)
EMPTY_RETRY_MIN_MS = 1200        # shorter audio = a blip, not a sentence
EMPTY_RETRY_LOGPROB = -1.15      # retry decode log_prob_threshold
                                 # (live default: -1.0)
EMPTY_RETRY_NO_SPEECH = 0.7      # retry decode no_speech_threshold
                                 # (live default: 0.6)
LOGPROB_RETRY_DROP = -1.25       # retry segment-gate hard floor (live
                                 # default: -1.1). The no-speech combo,
                                 # compression-loop and hallucination gates
                                 # are NEVER relaxed.

# --- v6.2.3: experience learning loop ---------------------------------------
EXPERIENCE_ENABLED = True        # local SQLite mirror of transcript
                                 # decisions (experience.py; text metadata
                                 # only, never audio). Override:
                                 # listener.experience
EXPERIENCE_DB = "experience.db"  # Override: listener.experience_db
FEEDBACK_POLL_S = 20.0           # how often the listener asks the backend
                                 # for teacher Accept/Reject/Edit decisions
                                 # (dashboard callback or a
                                 # GET /lesson/feedback endpoint when
                                 # present). A missing endpoint stays
                                 # silent — the poller is best-effort.
FEEDBACK_URL: Optional[str] = None   # Override: listener.feedback_url

# --- v6.2.0 ---------------------------------------------------------------
CAP_GAP_MIN_FRAMES = 3           # a cap-cut needs a REAL word gap: >= this
                                 # many consecutive quiet frames (~90 ms at
                                 # 30 ms frames) around the cut point. The
                                 # old quietest-single-frame cut could slice
                                 # INSIDE a word when speech never pauses.
                                 # Override: listener.cap_gap_frames
CARRY_PROMPT_WORDS = 8           # left-context continuation: the last N
                                 # words of the previous GOOD transcript
                                 # (conf >= CARRY_PROMPT_MIN_CONF) are passed
                                 # to Whisper as initial_prompt, so a chunk
                                 # that starts mid-sentence continues in
                                 # context; the echo is stripped. 0 = off.
                                 # Override: listener.carry_prompt_words
CARRY_PROMPT_MIN_CONF = -0.5     # never continue from garbled context
INITIAL_PROMPT: Optional[str] = None   # domain prompt for Class 4-5 math,
                                 # ENGLISH ROUTE ONLY (route-specific:
                                 # prompts measured to hurt the Hindi
                                 # fine-tune the same way hotwords did).
                                 # Override: listener.initial_prompt
SCRIPT_SANITY = True             # post-decode guard: an EN-route decode
                                 # coming out Devanagari-dominant (or an
                                 # HI-route decode Latin-dominant) is
                                 # re-decoded once on the other model
                                 # (budget permitting), better conf wins.
                                 # Override: listener.script_sanity
ADAPTIVE_MAX_UTT = True          # sustained RTF > ADAPTIVE_RTF_TRIGGER:
                                 # shorten the cap 12 -> 9 -> 7 s (never
                                 # below) so decodes get smaller and the
                                 # queue catches up more often. One-time
                                 # console notice per step.
                                 # Override: listener.adaptive_max_utt
ADAPTIVE_RTF_TRIGGER = 1.0       # rolling real-time factor that arms it
ADAPTIVE_STEPS_S = (9.0, 7.0)    # cap sizes after each step
ADAPTIVE_COOLDOWN_S = 45.0       # min seconds between steps
WHISPER_BEAM_SIZE = 1            # greedy: ~2-4x faster on CPU than beam 5;
                                 # accuracy on short utterances is near-equal.
                                 # Override: listener.beam_size (3-5 = a bit
                                 # sharper but much slower — fast CPUs only)
WHISPER_BEAM_RETRY = 0           # opt-in re-decode at a wider beam when a
                                 # chunk comes back empty or with conf <
                                 # CONF_RETRY_DB; better of the two wins.
                                 # Bench: cannot rescue stock-small Hindi
                                 # (the model cannot parse it) and doubles
                                 # latency on slow CPUs — off by default.
                                 # Override: listener.beam_retry (e.g. 3)
CONF_RETRY_DB = -0.95            # retry threshold above (log-prob units)
WHISPER_REP_PENALTY = 1.0        # 1.0 = OFF (since v6.1.4). Devanagari
                                 # legitimately repeats matras/consonants
                                 # inside words; the penalty distorted Hindi
                                 # decode into phoneme soup. Override:
                                 # listener.repetition_penalty (1.0-2.0)
WHISPER_CPU_THREADS = max(1, min(4, (os.cpu_count() or 4) - 2))
                                 # reserve cores for capture + assembler, or
                                 # the mic overflows exactly while Whisper
                                 # decodes. 0 in config.json = this auto value.
AUDIO_LATENCY = "high"           # PortAudio latency: "high" resists input
                                 # overflow on flaky captures (WO Mic, USB,
                                 # Bluetooth). Override: listener.latency
BLOCK_MS = 200                   # capture block (was 30 ms). Fewer, bigger
                                 # callbacks = far more overflow-resistant;
                                 # split back into 30 ms frames downstream.
                                 # Override: listener.block_ms (>= 30)

# v6.1.6: hotwords are OFF by default — measured on the bench to poison
# BOTH models (English route: RTF 2.13 vs 0.23 without, 3/5 chunks
# rejected vs 0; Hindi fine-tune: conf -0.60 vs -0.10, sentence recovery
# 0.33 vs 0.83). The /learning/prompt set is also ignored unless you opt
# in here. When enabled they apply to the ENGLISH route only and force
# timestamps back ON (hot + no-timestamps measured recovery 0.00).
# Override: listener.hotwords ("word word …", or true = learning-loop set)
WHISPER_HOTWORDS: Optional[str] = None
_HOTWORDS_FROM_LEARNING = False   # listener.hotwords == true

MIN_WORDS = 3
DEDUPE_WINDOW_S = 10.0

TRANSCRIBE_QUEUE_MAX = 12
HEARTBEAT_S = 30.0               # periodic "still listening" status line
                                 # (floor / gate / mic peak / count); 0 = off.
                                 # Override: listener.heartbeat_s
STALL_WARN_S = 5.0               # no audio arriving at all -> warn
HTTP_TIMEOUT_S = 30.0
HTTP_RETRIES = 2

# HALLUCINATION_RE (v6.2.0) moved to listener/janitor.py — imported above.

ACTIVE_SR = SAMPLE_RATE          # actual capture rate (fallback resamples)
STOP = threading.Event()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LISTENER_CFG: dict = {}

# Module defaults for every listener knob — apply_overrides({}) (or a
# config without a listener section) always lands back on THESE, so
# re-applied overrides and --test-wav never inherit stale tuning.
_DEFAULTS = {
    "probe_every": PROBE_EVERY_BEHIND,
    "merge_max_s": MERGE_MAX_S,
    "overlap_trim": OVERLAP_TRIM_MIN_WORDS,
    "cap_gap_frames": CAP_GAP_MIN_FRAMES,
    "carry_prompt_words": CARRY_PROMPT_WORDS,
    "repetition_penalty": WHISPER_REP_PENALTY,
    "beam_retry": WHISPER_BEAM_RETRY,
    "without_timestamps": WITHOUT_TIMESTAMPS,
    "vad_filter": VAD_FILTER_ENABLED,
    "script_sanity": SCRIPT_SANITY,
    "adaptive_max_utt": ADAPTIVE_MAX_UTT,
    "max_utt_s": MAX_UTTERANCE_FRAMES * FRAME_MS / 1000.0,
    "math_initial_prompt": MATH_INITIAL_PROMPT,
    "hindi_classroom_prompt": HINDI_CLASSROOM_PROMPT,
    "stitch_tail_words": STITCH_TAIL_WORDS,
    "stitch_window_s": STITCH_WINDOW_S,
    "empty_retry": EMPTY_RETRY,
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        print("✅ Loaded saved credentials from config.json")
    else:
        cfg = {
            "token": input("Token: ").strip(),
            "class_id": input("Class ID: ").strip(),
            "lesson_id": input("Lesson ID: ").strip(),
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print("✅ Credentials saved!")
    return cfg


def apply_overrides(cfg: dict) -> None:
    """Optional config.json overrides — everything stays backward compatible."""
    global API_URL, MODEL_SIZE, WHISPER_LANGUAGE, WHISPER_HOTWORDS, MIN_WORDS
    global WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_BEAM_SIZE, AUDIO_LATENCY
    global WHISPER_CPU_THREADS, BLOCK_MS, MAX_UTTERANCE_FRAMES
    global SPEECH_START_MARGIN_DB, SPEECH_CONTINUE_MARGIN_DB, HEARTBEAT_S
    global WHISPER_BEAM_RETRY, WHISPER_REP_PENALTY
    global WITHOUT_TIMESTAMPS, VAD_FILTER_ENABLED
    global PROBE_EVERY_BEHIND, MERGE_MAX_S, OVERLAP_TRIM_MIN_WORDS
    global _HOTWORDS_FROM_LEARNING
    global CAP_GAP_MIN_FRAMES, CARRY_PROMPT_WORDS, INITIAL_PROMPT
    global SCRIPT_SANITY, ADAPTIVE_MAX_UTT
    global MATH_INITIAL_PROMPT, HINDI_CLASSROOM_PROMPT
    global STITCH_TAIL_WORDS, STITCH_WINDOW_S, HINDI_FT_MODEL
    global EN_STOCK_MODEL, EMPTY_RETRY
    global EXPERIENCE_ENABLED, EXPERIENCE_DB, FEEDBACK_URL
    global CUSTOM_ALLOWLIST_PATH
    lis = cfg.get("listener") or {}
    # v6.3.0 session presets (P2 #7): listener.preset in config.json, or
    # --preset on the CLI (main() writes the CLI value into this dict
    # first, so the CLI always wins). Preset keys OVERRIDE the user's
    # config — that is the point of a preset (math_en forces hi_model
    # back to None even when the config points at a fine-tune). "auto"
    # (or no key) = no overrides = the measured language router.
    preset_raw = lis.get("preset", "__unset__")
    if preset_raw != "__unset__" and preset_raw not in (None, "", "auto"):
        pname = _presets_mod.normalize_preset(preset_raw)
        if pname is None:
            print(f"⚠️ Unknown preset {preset_raw!r} — ignoring (valid: "
                  f"auto | math_en | hindi_class)")
        else:
            lis = _presets_mod.apply_preset(lis, pname)
            print(f"🔒 Preset '{pname}': {_presets_mod.DESCRIPTIONS[pname]}")
    LISTENER_CFG.update(lis)
    API_URL = lis.get("api_url", cfg.get("api_url", API_URL))
    MODEL_SIZE = lis.get("model_size", MODEL_SIZE)
    # v6.2.3 session language lock: "en"|"hi"|"auto" (case-insensitive;
    # english/hindi accepted as aliases; null/absent/"auto" = the measured
    # router). An unknown value warns once and falls back to AUTO — a typo
    # must never wedge the router into a fixed language.
    lang_cfg = lis.get("language", "__unset__")
    if lang_cfg == "__unset__" or lang_cfg is None:
        WHISPER_LANGUAGE = None
    else:
        norm = LANGUAGE_ALIASES.get(str(lang_cfg).strip().lower(), "__bad__")
        if norm == "__bad__":
            print(f"⚠️ listener.language: {lang_cfg!r} is not en/hi/auto — "
                  f"using auto (the language router)")
            WHISPER_LANGUAGE = None
        else:
            WHISPER_LANGUAGE = norm
    hw_cfg = lis.get("hotwords", "__unset__")
    if hw_cfg == "__unset__":
        # no listener.hotwords key (or no config at all) -> v6.1.6 default:
        # hotwords OFF. Explicit reset, not keep-current, so --test-wav and
        # re-applied overrides always land on clean defaults.
        WHISPER_HOTWORDS = None
        _HOTWORDS_FROM_LEARNING = False
    elif hw_cfg is True:                    # opt in to the learning-loop set
        WHISPER_HOTWORDS = None
        _HOTWORDS_FROM_LEARNING = True
    elif isinstance(hw_cfg, str) and hw_cfg.strip():
        WHISPER_HOTWORDS = hw_cfg.strip()
        _HOTWORDS_FROM_LEARNING = False
    else:
        WHISPER_HOTWORDS = None
        _HOTWORDS_FROM_LEARNING = False
    MIN_WORDS = int(lis.get("min_words", MIN_WORDS))
    WHISPER_DEVICE = lis.get("device", WHISPER_DEVICE)
    WHISPER_COMPUTE = lis.get("compute_type", WHISPER_COMPUTE)
    WHISPER_BEAM_SIZE = int(lis.get("beam_size", WHISPER_BEAM_SIZE))
    AUDIO_LATENCY = lis.get("latency", AUDIO_LATENCY)
    WHISPER_CPU_THREADS = int(lis.get("cpu_threads", WHISPER_CPU_THREADS))
    if WHISPER_CPU_THREADS <= 0:          # 0 = auto
        WHISPER_CPU_THREADS = max(1, min(4, (os.cpu_count() or 4) - 2))
    BLOCK_MS = max(30, int(lis.get("block_ms", BLOCK_MS)))
    _max_utt_s = float(lis.get("max_utt_s", _DEFAULTS["max_utt_s"]))
    MAX_UTTERANCE_FRAMES = max(100, min(2000,
                                        round(_max_utt_s * 1000 / FRAME_MS)))
    SPEECH_START_MARGIN_DB = float(lis.get("start_margin_db",
                                           SPEECH_START_MARGIN_DB))
    SPEECH_CONTINUE_MARGIN_DB = float(lis.get("continue_margin_db",
                                              SPEECH_CONTINUE_MARGIN_DB))
    HEARTBEAT_S = float(lis.get("heartbeat_s", HEARTBEAT_S))
    WITHOUT_TIMESTAMPS = bool(lis.get("without_timestamps",
                                      _DEFAULTS["without_timestamps"]))
    VAD_FILTER_ENABLED = bool(lis.get("vad_filter",
                                      _DEFAULTS["vad_filter"]))
    try:
        PROBE_EVERY_BEHIND = max(1, int(lis.get("probe_every",
                                                _DEFAULTS["probe_every"])))
    except (TypeError, ValueError):
        pass
    try:
        MERGE_MAX_S = max(8.0, min(60.0,
                                   float(lis.get("merge_max_s",
                                                 _DEFAULTS["merge_max_s"]))))
    except (TypeError, ValueError):
        pass
    try:
        OVERLAP_TRIM_MIN_WORDS = max(
            0, int(lis.get("overlap_trim",
                           _DEFAULTS["overlap_trim"])))
    except (TypeError, ValueError):
        pass
    try:
        CAP_GAP_MIN_FRAMES = max(
            1, min(20, int(lis.get("cap_gap_frames",
                                   _DEFAULTS["cap_gap_frames"]))))
    except (TypeError, ValueError):
        pass
    try:
        CARRY_PROMPT_WORDS = max(
            0, min(30, int(lis.get("carry_prompt_words",
                                   _DEFAULTS["carry_prompt_words"]))))
    except (TypeError, ValueError):
        pass
    ip_cfg = lis.get("initial_prompt", "__unset__")
    if ip_cfg == "__unset__" or ip_cfg is None:
        # key absent (or explicit null) -> clean default, so re-applied
        # overrides and --test-wav always land on no-prompt behaviour
        INITIAL_PROMPT = None
    elif isinstance(ip_cfg, str) and ip_cfg.strip():
        INITIAL_PROMPT = ip_cfg.strip()
    else:
        INITIAL_PROMPT = None
    SCRIPT_SANITY = bool(lis.get("script_sanity",
                                 _DEFAULTS["script_sanity"]))
    ADAPTIVE_MAX_UTT = bool(lis.get("adaptive_max_utt",
                                    _DEFAULTS["adaptive_max_utt"]))
    MATH_INITIAL_PROMPT = bool(lis.get("math_initial_prompt",
                                       _DEFAULTS["math_initial_prompt"]))
    HINDI_CLASSROOM_PROMPT = bool(lis.get(
        "hindi_classroom_prompt", _DEFAULTS["hindi_classroom_prompt"]))
    try:
        STITCH_TAIL_WORDS = max(0, min(8, int(lis.get(
            "stitch_tail_words", _DEFAULTS["stitch_tail_words"]))))
    except (TypeError, ValueError):
        pass
    try:
        STITCH_WINDOW_S = max(0.0, min(120.0, float(lis.get(
            "stitch_window_s", _DEFAULTS["stitch_window_s"]))))
    except (TypeError, ValueError):
        pass
    # v6.2.2: Hindi model override — opt-in for a locally fine-tuned model
    # (listener.hi_model, or a top-level "hi_model"); absent/null keeps the
    # measured default. Never overwritten in code without this config key.
    hm_cfg = lis.get("hi_model")
    if not isinstance(hm_cfg, str) or not hm_cfg.strip():
        hm_cfg = cfg.get("hi_model")          # top-level fallback
    if isinstance(hm_cfg, str) and hm_cfg.strip():
        HINDI_FT_MODEL = hm_cfg.strip()
    else:
        HINDI_FT_MODEL = _HINDI_FT_DEFAULT
    # v6.2.3: stock/EN-route model override — same contract as hi_model
    # (listener.en_model, or a top-level "en_model"); absent/null keeps
    # the measured default "small". Nothing loads or fine-tunes it here;
    # it is a path/id for WhisperModel().
    em_cfg = lis.get("en_model")
    if not isinstance(em_cfg, str) or not em_cfg.strip():
        em_cfg = cfg.get("en_model")          # top-level fallback
    if isinstance(em_cfg, str) and em_cfg.strip():
        EN_STOCK_MODEL = em_cfg.strip()
    else:
        EN_STOCK_MODEL = None
    try:
        _rp = float(lis.get("repetition_penalty",
                            _DEFAULTS["repetition_penalty"]))
        WHISPER_REP_PENALTY = max(1.0, min(2.0, _rp))
    except (TypeError, ValueError):
        pass
    try:
        WHISPER_BEAM_RETRY = max(0, int(lis.get("beam_retry",
                                                _DEFAULTS["beam_retry"])))
    except (TypeError, ValueError):
        pass
    # v6.2.3/v6.3.0: soft retry on borderline empty rejects + experience
    # loop switches. "soft_retry" is canonical; "empty_retry" is the
    # v6.2.3 alias. If BOTH are present the explicit soft_retry wins.
    _sr = lis.get("soft_retry", "__unset__")
    _er = lis.get("empty_retry", "__unset__")
    if _sr != "__unset__":
        EMPTY_RETRY = bool(_sr)
    elif _er != "__unset__":
        EMPTY_RETRY = bool(_er)
    else:
        EMPTY_RETRY = _DEFAULTS["empty_retry"]
    EXPERIENCE_ENABLED = bool(lis.get("experience", EXPERIENCE_ENABLED))
    edb = lis.get("experience_db")
    EXPERIENCE_DB = edb.strip() if isinstance(edb, str) and edb.strip() \
        else "experience.db"
    fu = lis.get("feedback_url")
    FEEDBACK_URL = fu.strip() if isinstance(fu, str) and fu.strip() else None
    ca = lis.get("experience_allowlist")
    CUSTOM_ALLOWLIST_PATH = ca.strip() \
        if isinstance(ca, str) and ca.strip() else None


# ---------------------------------------------------------------------------
# v6.3.0: frame_dbfs / api_noise_db / downsample_to_16k moved to
# listener/audio_gate.py (imported above) — unit-testable, no hardware.
# ---------------------------------------------------------------------------


class UtteranceAssembler(_AssemblerCore):
    """v6.3.0 composition root: wires the module-level tunables into the
    pure assembler core (listener/assembler.py) + AdaptiveGate
    (listener/audio_gate.py). Behaviour identical to v6.2.3: adaptive
    floor, pre-roll, 1.2 s trailing silence, word-gap cap cuts, carry."""

    def __init__(self) -> None:
        gate = AdaptiveGate(
            start_margin_db=SPEECH_START_MARGIN_DB,
            continue_margin_db=SPEECH_CONTINUE_MARGIN_DB,
            floor_window_frames=FLOOR_WINDOW_FRAMES,
            floor_percentile=FLOOR_PERCENTILE,
            absolute_silence_db=ABSOLUTE_SILENCE_DB,
            warmup_frames=WARMUP_FRAMES,
            boost_pct=FLOOR_BOOST_PCT,
            boost_gap_db=FLOOR_BOOST_GAP_DB,
            boost_max_db=FLOOR_BOOST_MAX_DB,
            boost_min_frames=FLOOR_BOOST_MIN_FRAMES)
        super().__init__(
            gate,
            frame_ms=FRAME_MS,
            pre_roll_frames=PRE_ROLL_FRAMES,
            silence_frames_to_end=SILENCE_FRAMES_TO_END,
            min_utterance_ms=MIN_UTTERANCE_MS,
            cap_search_frames=CAP_SEARCH_FRAMES,
            cap_min_emit_frames=CAP_MIN_EMIT_FRAMES,
            cap_gap_frames=CAP_GAP_MIN_FRAMES,
            min_speech_frames=MIN_SPEECH_FRAMES,
            max_frames_fn=lambda: MAX_UTTERANCE_FRAMES)




_last = {"norm": "", "t": 0.0}


def find_gap_cut(dbs, floor: float, search: int,
                 min_gap_frames: int) -> Optional[int]:
    """v6.2.0 delegate — logic moved to listener/assembler.py; this wrapper
    supplies the configured SPEECH_CONTINUE_MARGIN_DB (legacy signature)."""
    return _find_gap_cut(dbs, floor, search, min_gap_frames,
                         SPEECH_CONTINUE_MARGIN_DB)





def is_duplicate(transcript: str) -> bool:
    """Suppress Whisper repetition loops: same normalized text within 10 s."""
    now = time.time()
    norm = re.sub(r"[^a-z0-9\u0900-\u097F]+", "", transcript.lower())
    dup = bool(norm) and norm == _last["norm"] and (now - _last["t"]) < DEDUPE_WINDOW_S
    if not dup:
        _last["norm"], _last["t"] = norm, now
    return dup











def build_transcribe_kwargs() -> dict:
    """v6.1.6 delegate — kwargs defined in listener/asr_router.py; this
    wrapper supplies the configured beam/VAD/timestamps policy."""
    return _build_kwargs(beam_size=WHISPER_BEAM_SIZE,
                         vad_filter=VAD_FILTER_ENABLED,
                         without_timestamps=WITHOUT_TIMESTAMPS)


def hi_route_kwargs(base: dict) -> dict:
    """v6.2.2 delegate — logic in listener/asr_router.hi_route_kwargs."""
    return _hi_kwargs_core(base, _route_cfg())


def en_route_kwargs(base: dict, lang: Optional[str] = None) -> dict:
    """v6.2.2 delegate — logic in listener/asr_router.en_route_kwargs."""
    return _en_kwargs_core(base, lang, _route_cfg())


def _route_cfg() -> RouteConfig:
    """Snapshot the mutable tunables into the router's RouteConfig.
    Called when the engine is built (and by the route-kwargs delegates),
    so tests/CLI can mutate the globals up to that point."""
    return RouteConfig(
        language=WHISPER_LANGUAGE,
        hotwords=WHISPER_HOTWORDS,
        initial_prompt=INITIAL_PROMPT,
        math_prompt_en=MATH_PROMPT_EN,
        hindi_prompt_hi=MATH_PROMPT_HI,
        math_initial_prompt=MATH_INITIAL_PROMPT,
        hindi_classroom_prompt=HINDI_CLASSROOM_PROMPT,
        rep_penalty=WHISPER_REP_PENALTY,
        script_sanity=SCRIPT_SANITY,
        rtf_skip_probe=RTF_SKIP_PROBE,
        probe_every_behind=PROBE_EVERY_BEHIND,
        lang_route_prob=LANG_ROUTE_PROB,
        route_langs=ROUTE_LANGS,
        route_aliases=tuple(ROUTE_ALIASES.items()),
        hindi_rescue_conf=HINDI_RESCUE_CONF)








_lang_hist: deque = deque(maxlen=3)


# --- v6.1.6 seam-overlap trim -------------------------------------------
_PUNCT_EDGE = PUNCT_EDGE   # v6.3.0: moved to listener/math_stitch
_last_posted = {"text": "", "t": 0.0}


_word_key = _word_key_mod          # v6.3.0: listener/math_stitch
_transcript_words = _transcript_words_mod



def trim_overlap(transcript: str) -> tuple:
    """v6.1.6: a cap-split carries its tail into the next chunk, so the
    seam words can legitimately be transcribed twice (once as the tail of
    chunk N, once as the head of chunk N+1 — Whisper garbles partial
    words differently each time). If the last N (>= listener.overlap_trim,
    default 4) words of the previously POSTED transcript match the first
    N words of this one within OVERLAP_TRIM_WINDOW_S, the repeated head
    is trimmed. Returns (text_after_trim, words_trimmed)."""
    if OVERLAP_TRIM_MIN_WORDS <= 0 or not transcript:
        return transcript, 0
    prev = _last_posted
    if not prev["text"] or \
            time.time() - prev["t"] > OVERLAP_TRIM_WINDOW_S:
        return transcript, 0
    pw = _transcript_words(prev["text"])
    spans = list(re.finditer(r"\S+", transcript))
    nw = [_word_key(m.group(0)) for m in spans]
    maxk = min(len(pw), len(nw), 14)
    for k in range(maxk, OVERLAP_TRIM_MIN_WORDS - 1, -1):
        if pw[-k:] == nw[:k]:
            rest = transcript[spans[k].start():].strip() if k < len(spans) \
                else ""
            return rest, k
    return transcript, 0


# ---------------------------------------------------------------------------
# v6.2.2 math phrase-tail rescue: stitch buffer + fragment allowlist
# ---------------------------------------------------------------------------
_stitch_tail = {"words": [], "t": 0.0}   # tail of the last ACCEPTED transcript





def math_fragment_allowed(text: str) -> bool:
    """v6.2.2 A2 delegate — logic in listener/math_stitch.py; the custom
    (teacher-accepted) patterns come from the experience loop."""
    return _frag_allowed(text, _CUSTOM_ALLOWLIST)





# v6.2.3: teacher-accepted phrase patterns (experience learning loop).
# Populated from data/experience/allowlist.txt at startup and refreshed
# whenever the experience loop records a new ACCEPT. Rejected patterns
# go to a DIFFERENT file and never land here.
_CUSTOM_ALLOWLIST: tuple = ()
_CUSTOM_ALLOWLIST_MTIME: float = 0.0


def reload_custom_allowlist() -> int:
    """(Re)load teacher-accepted phrase patterns into the runtime
    allowlist. Returns the number of patterns loaded. Missing file -> 0
    (silent — the loop may never have accepted anything)."""
    global _CUSTOM_ALLOWLIST, _CUSTOM_ALLOWLIST_MTIME
    path = CUSTOM_ALLOWLIST_PATH or os.path.join(
        os.path.dirname(os.path.abspath(EXPERIENCE_DB)), "data",
        "experience", "allowlist.txt")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _CUSTOM_ALLOWLIST = ()
        _CUSTOM_ALLOWLIST_MTIME = 0.0
        return 0
    if mtime == _CUSTOM_ALLOWLIST_MTIME and _CUSTOM_ALLOWLIST:
        return len(_CUSTOM_ALLOWLIST)
    pats = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    pats.append(ln)
    except Exception:
        return len(_CUSTOM_ALLOWLIST)
    _CUSTOM_ALLOWLIST = tuple(pats)
    _CUSTOM_ALLOWLIST_MTIME = mtime
    return len(_CUSTOM_ALLOWLIST)


def maybe_stitch(new_text: str) -> tuple:
    """v6.2.2 A1: prepend the tail of the previous ACCEPTED transcript when
    the cut fell mid-claim. Two triggers:
      - the previous tail ends with an incomplete cue ('one half is greater
        than' + 'three quarters.'), OR
      - the new chunk starts with a continuation cue ('greater than three
        quarters' after 'one half is').
    Runs BEFORE the min-words filter and before the API send; the caller
    runs the janitor once on the combined text. Returns
    (combined_text, prev_tail_words_or_None)."""
    if STITCH_TAIL_WORDS <= 0 or STITCH_WINDOW_S <= 0 or not new_text:
        return new_text, None
    st = _stitch_tail
    if not st["words"] or time.time() - st["t"] > STITCH_WINDOW_S:
        return new_text, None
    if ends_with_incomplete_cue(" ".join(st["words"])) or \
            starts_with_continuation_cue(new_text):
        return " ".join(st["words"]) + " " + new_text.strip(), st["words"]
    return new_text, None


def _update_stitch_tail(transcript: str) -> None:
    """Remember the tail of an ACCEPTED transcript for the next stitch."""
    if STITCH_TAIL_WORDS <= 0 or not transcript:
        _stitch_tail["words"] = []
        return
    _stitch_tail["words"] = transcript.split()[-STITCH_TAIL_WORDS:]
    _stitch_tail["t"] = time.time()


# ---------------------------------------------------------------------------
# v6.2.0 janitor: nothing noisy, loopy or symbol-only ships to the API
# ---------------------------------------------------------------------------









def smooth_language(det: Optional[str]) -> Optional[str]:
    """Majority vote over the last 3 auto detections (newest wins ties),
    so one shaky chunk can't flip hi<->en mid-lesson. Pinned languages
    (listener.language) bypass smoothing entirely."""
    if not det or WHISPER_LANGUAGE:
        return det
    _lang_hist.append(det)
    counts: dict = {}
    for d in _lang_hist:
        counts[d] = counts.get(d, 0) + 1
    top = max(counts.values())
    tied = [k for k, v in counts.items() if v == top]
    return tied[-1]


_detect_language = detect_language   # v6.3.0: listener/asr_router



class WhisperRouter(_RouterCore):
    """v6.3.0 composition root: the dual-model router now lives in
    listener/asr_router.py and takes a RouteConfig snapshot; this adapter
    keeps the legacy (stock, hi, stats) construction signature and
    snapshots the current tunables at build time (the session lock,
    hotwords and prompts cannot change afterwards without a restart)."""

    def __init__(self, stock_model, hi_model, stats: dict) -> None:
        super().__init__(stock_model, hi_model, stats, _route_cfg())




def hi_route_enabled() -> bool:
    """v6.3.0 (P0 #1): is the Hindi model route part of this session?
    False whenever the session language is locked to "en" (preset
    math_en): the hi model is then NEVER loaded and NEVER called."""
    return MODEL_SIZE == "small-hi" and WHISPER_LANGUAGE != "en"


def load_models():
    """Load per MODEL_SIZE. "small-hi" = stock small + Hindi fine-tune with
    graceful fallback to single-model mode if the fine-tune is unavailable
    (e.g. first run with no internet — stock stays fully offline).
    v6.2.3: the stock (EN-route) model can be repointed with
    listener.en_model — same opt-in contract as hi_model; the default
    is and stays the measured stock 'small'.
    v6.3.0 (P0 #1): under the language="en" lock (preset math_en) the
    Hindi model is NOT loaded at all — faster startup and a structural
    guarantee that no hi-model call can happen."""
    from faster_whisper import WhisperModel
    if HINDI_FT_MODEL != _HINDI_FT_DEFAULT and hi_route_enabled():
        print(f"[i] Hindi model override active (listener.hi_model): "
              f"{HINDI_FT_MODEL}")
    if EN_STOCK_MODEL:
        print(f"[i] English/stock model override active (listener.en_model): "
              f"{EN_STOCK_MODEL}")
    hi_model = None
    stock_name = EN_STOCK_MODEL or \
        ("small" if MODEL_SIZE == "small-hi" else MODEL_SIZE)
    model = WhisperModel(stock_name,
                         device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE,
                         cpu_threads=WHISPER_CPU_THREADS)
    if MODEL_SIZE == "small-hi" and not hi_route_enabled():
        print("🔒 language=en — the Hindi model is NOT loaded; every chunk "
              "decodes on the stock English model (math_en preset)")
    elif MODEL_SIZE == "small-hi":
        try:
            print(f"🇮🇳 Loading Hindi model '{HINDI_FT_MODEL}' "
                  f"(first run downloads ~0.5 GB once, then offline)...")
            t0 = time.time()
            hi_model = WhisperModel(HINDI_FT_MODEL, device=WHISPER_DEVICE,
                                    compute_type=WHISPER_COMPUTE,
                                    cpu_threads=WHISPER_CPU_THREADS)
            print(f"✅ Hindi model ready in {time.time() - t0:.1f}s — Hindi "
                  f"chunks route here, English to stock 'small'")
        except Exception as e:
            print(f"⚠️ Hindi model unavailable ({e}) — falling back to "
                  f"stock 'small' for ALL languages. Retry online later; "
                  f"the download resumes/verifies automatically.")
    return model, hi_model


class SingleEngine(_SingleCore):
    """v6.3.0 composition root for single-model mode (see WhisperRouter)."""

    def __init__(self, model) -> None:
        super().__init__(model, _route_cfg())





def _force_utf8_console() -> None:
    """Windows cp1252 consoles print '�' for Devanagari (and older ones
    raise UnicodeEncodeError mid-line); force UTF-8 with safe replacement
    so Hindi transcripts always render. No-op where unsupported."""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        try:
            if s is not None and hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run_test_wav(paths) -> int:
    """--test-wav: transcribe WAV files through the EXACT live engine
    (router, kwargs, segment gates) and print text + confidence. No mic,
    no API, no credentials needed — the teacher can verify Hindi quality
    from --save-audio recordings before class."""
    _force_utf8_console()
    import wave as _wave
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = load_config()
            apply_overrides(cfg)
        except Exception:
            print("[i]   invalid config.json — using default listener "
                  "settings for this check")
            apply_overrides({})
    else:
        # never prompt for credentials in a diagnostic mode
        print("[i]   no config.json — using default listener settings "
              "for this check")
        apply_overrides({})
    try:
        model, hi_model = load_models()
    except Exception as e:
        print(f"❌ Could not load faster-whisper: {e}")
        return 1
    stats: dict = {}
    engine = (WhisperRouter(model, hi_model, stats) if hi_model is not None
              else SingleEngine(model))
    kwargs = build_transcribe_kwargs()
    print()
    for p in paths:
        try:
            with _wave.open(p, "rb") as w:
                sr = w.getframerate()
                raw = np.frombuffer(w.readframes(w.getnframes()),
                                    dtype=np.int16)
            if sr != SAMPLE_RATE:
                raw = downsample_to_16k(raw, sr)
            audio_f32 = raw.astype(np.float32) / 32768.0
        except Exception as e:
            print(f"▶ {p}\n   ❌ cannot read WAV: {e}\n")
            continue
        segs, info, tag = engine.decode(audio_f32, kwargs)
        kept = [s for s in segs if segment_ok(s)]
        text = clean_transcript([s.text.strip() for s in kept])
        conf = seg_confidence(kept)
        dur = audio_f32.size / SAMPLE_RATE
        print(f"▶ {p}  ({dur:.1f}s)")
        print(f"   🗣 {getattr(info, 'language', '?')}"
              f" (p={getattr(info, 'language_probability', 0):.2f})"
              f" | 🧠 {tag or MODEL_SIZE}"
              f" | 🎯 conf {'%.2f' % conf if conf is not None else 'n/a'}")
        if text:
            print(f"   ✅ {text}")
        else:
            print("   🔇 (every segment rejected by the confidence gate "
                  "— audio unclear)")
        # diagnostic bonus: if the live route decoded on the stock model
        # and the text looks Hindi (or empty), ALSO show the Hindi model
        # so a mis-probed clip doesn't read as "the fix doesn't work"
        if tag == "stock" and hi_model is not None and \
                (not text or any("\u0900" <= ch <= "\u097F" for ch in text)):
            hk = hi_route_kwargs(kwargs)
            segs2, _ = _transcribe_once(hi_model, audio_f32, hk)
            kept2 = [s for s in segs2 if segment_ok(s)]
            text2 = clean_transcript([s.text.strip() for s in kept2])
            conf2 = seg_confidence(kept2)
            print(f"   🧪 Hindi model, language pinned 'hi' | "
                  f"🎯 conf {'%.2f' % conf2 if conf2 is not None else 'n/a'}")
            print(f"      {text2 if text2 else '🔇 (rejected)'}")
        print()
    return 0


def _save_wav(save_dir: str, audio16: np.ndarray, dur_ms: float) -> str:
    """Write one captured utterance as 16 kHz mono WAV (--save-audio)."""
    import wave
    os.makedirs(save_dir, exist_ok=True)
    name = time.strftime("utt_%Y%m%d_%H%M%S") + f"_{dur_ms / 1000:.1f}s.wav"
    path = os.path.join(save_dir, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.ascontiguousarray(audio16, dtype=np.int16).tobytes())
    print(f"💾 Saved {path} — this is EXACTLY what Whisper hears.\n"
          "      Clean audio + bad text -> model/settings problem.\n"
          "      Muffled / noisy audio -> mic or room problem.")
    return path


def looks_degenerate(transcript: str) -> bool:
    """True when a phrase repeats 3+ times back-to-back (Whisper loop).

    Checks block sizes 1-3 words: single-word loops ("है है है") AND
    phrase loops ("उनके बारह उनके बारह उनके बारह" — seen in real logs).
    Split on whitespace (NOT \\w+ — combining marks like ् / ः are not
    \\w, so regex tokenizing would split inside Devanagari conjuncts and
    hide the repetition). Only strip edge punctuation.
    """
    words = [w.strip(".,!?;:\"'`()[]{}<>…॥।")
             for w in transcript.lower().split()]
    words = [w for w in words if w]
    L = len(words)
    for n in (1, 2, 3):
        if L < n * 3:
            continue
        run = 1
        i = n
        while i + n <= L:
            if words[i:i + n] == words[i - n:i]:
                run += 1
                if run >= 3:
                    return True
                i += n
            else:
                run = 1
                i += 1
    return False


def send_transcript(transcript: str, noise_db: int, headers: dict, ids: dict,
                    confidence: Optional[float] = None,
                    language: Optional[str] = None):
    payload = {
        "class_id": ids["class_id"],
        "lesson_id": ids["lesson_id"],
        "transcript": transcript,
        "speaker": "teacher",
        "noise_db": noise_db,
    }
    if confidence is not None:
        # lets the backend gate tier-3 corrections on ASR reliability
        payload["confidence"] = round(float(confidence), 2)
    if language:
        # per-utterance Whisper language detection (en/hi/...) — feeds the
        # six-parameter assessment engine and the learning digest
        payload["lang"] = str(language)
    for attempt in range(HTTP_RETRIES + 1):
        try:
            return httpx.post(f"{API_URL}/audio/ingest", headers=headers,
                              timeout=HTTP_TIMEOUT_S, json=payload)
        except httpx.HTTPError as e:
            if attempt >= HTTP_RETRIES:
                print(f"❌ API unreachable ({e}) — transcript dropped after "
                      f"{HTTP_RETRIES + 1} attempts")
                return None
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# v6.2.3 experience learning loop: local decision mirror + teacher rules
# (text metadata only; nothing here trains anything — see experience.py)
# ---------------------------------------------------------------------------
EXP: Optional["ExperienceStore"] = None
_EXP_WARNED = {"flag": False}


def init_experience(lesson_id: Optional[str] = None) -> None:
    """Create the local experience store (if enabled and importable).
    Never raises — a broken store must not take the listener down."""
    global EXP
    if not EXPERIENCE_ENABLED or not _EXPERIENCE_OK:
        EXP = None
        if EXPERIENCE_ENABLED and not _EXPERIENCE_OK and not _EXP_WARNED["flag"]:
            _EXP_WARNED["flag"] = True
            print("[i]   experience.py not found — the learning loop is "
                  "disabled (transcription is unaffected)")
        return
    try:
        EXP = ExperienceStore(db_path=EXPERIENCE_DB, lesson_id=lesson_id)
        n = reload_custom_allowlist()
        if n:
            print(f"📚 Experience allowlist: {n} teacher-accepted phrase "
                  f"pattern(s) loaded")
    except Exception as e:
        EXP = None
        if not _EXP_WARNED["flag"]:
            _EXP_WARNED["flag"] = True
            print(f"[i]   experience store unavailable ({e}) — continuing "
                  f"without the learning loop")


def _exp_log_ingest(transcript: str, route: Optional[str],
                    confidence: Optional[float], noise_db: int) -> None:
    if EXP is None:
        return
    try:
        EXP.log_ingest(transcript, route=route, confidence=confidence,
                       noise_db=noise_db)
    except Exception:
        pass


def _exp_log_short_drop(transcript: str, route: Optional[str],
                        noise_db: int, reason: str = SHORT_NOISE) -> None:
    if EXP is None:
        return
    try:
        EXP.log_short_drop(transcript, route=route, noise_db=noise_db,
                           reason=reason)
    except Exception:
        pass


def _exp_log_math_proposal(statement: str, transcript: str,
                           route: Optional[str], note: str = "") -> None:
    if EXP is None:
        return
    try:
        EXP.log_math_proposal(statement, transcript=transcript, route=route,
                              note=note or None)
    except Exception:
        pass


def _route_label(model_tag: Optional[str], lang: Optional[str]) \
        -> Optional[str]:
    """Map the decode route to an experience-store label: 'stock'->'en',
    'small-hi'->'hi'; single-model mode falls back to the detected lang."""
    if model_tag == "stock":
        return "en"
    if model_tag == "small-hi":
        return "hi"
    return lang if lang in ("en", "hi") else None


def _apply_teacher_decision(item: dict) -> None:
    """One teacher decision from the dashboard/endpoint: store the row,
    apply the derived-learning rule, reload the allowlist on accept."""
    if EXP is None:
        return
    dec = item.get("decision")
    text = (item.get("text") or "").strip()
    try:
        EXP.log_teacher_decision(dec, text,
                                 edited_text=item.get("edited_text"),
                                 route=item.get("route"))
        note = EXP.apply_rules(dec, text, item.get("edited_text"))
        if dec == "accept":
            reload_custom_allowlist()
        print(f"📚 Teacher {dec} recorded — {note}")
    except Exception:
        pass


def _feedback_poller(headers: dict, stop: "threading.Event") -> None:
    """Best-effort poll for teacher Accept/Reject/Edit decisions.

    The dashboard can POST decisions to the backend, which exposes them at
    GET {API_URL}/lesson/feedback?since_id=<last-id> (config override:
    listener.feedback_url). Shapes other than a list/wrapped-list are
    ignored; a 404/missing endpoint prints ONE info line and then stays
    silent — the loop is a mirror, never a hard dependency.
    """
    global FEEDBACK_URL
    if EXP is None:
        return
    since_id = 0
    url = FEEDBACK_URL or f"{API_URL}/lesson/feedback"
    missing_notes = 0
    while not stop.is_set() and not STOP.is_set():
        try:
            r = httpx.get(url, headers=headers, timeout=5.0,
                          params={"since_id": since_id})
            if r.status_code == 200:
                items = parse_feedback_items(r.json())
                for it in items:
                    try:
                        iid = int(it.get("id") or 0)
                    except (TypeError, ValueError):
                        iid = 0
                    _apply_teacher_decision(it)
                    if iid > since_id:
                        since_id = iid
                if items:
                    print(f"📚 {len(items)} teacher decision(s) applied to "
                          f"the experience store")
                missing_notes = 0
            elif r.status_code == 404:
                missing_notes += 1
                if missing_notes == 2:
                    print("[i]   No /lesson/feedback endpoint on the backend "
                          "— teacher decisions can still reach the store via "
                          "the dashboard callback; polling disabled quietly.")
                    return
            # other statuses: stay silent, retry next cycle
        except Exception:
            pass          # server down / offline — retry next cycle
        stop.wait(FEEDBACK_POLL_S)


def run_experience_report(db_path: Optional[str] = None) -> int:
    """--experience-report: end-of-session / weekly summary. Works with no
    config.json, no mic and no models — it only reads the local store.
    v6.3.0: the renderer moved to tools/experience_report.py so
    `python -m tools.experience_report` is the same output."""
    _force_utf8_console()
    try:
        from tools.experience_report import render_report
    except Exception as e:                        # pragma: no cover
        print(f"❌ tools/experience_report.py not available: {e}")
        return 1
    return render_report(db_path or EXPERIENCE_DB)


def run_experience_export(out_dir: str = "data",
                          db_path: Optional[str] = None) -> int:
    """--experience-export: write accepted/edited (asr, ref) text pairs to
    data/asr/{en,hi}/ — an OFFLINE, opt-in step; nothing runs by itself."""
    _force_utf8_console()
    path = db_path or EXPERIENCE_DB
    if not _EXPERIENCE_OK:
        print("❌ experience.py not found next to mic_listener.py")
        return 1
    if not os.path.exists(path):
        print(f"📭 No experience store yet at '{path}' — nothing to export")
        return 0
    try:
        store = ExperienceStore(db_path=path)
        n, manifest = store.export_pairs(out_dir)
    except Exception as e:
        print(f"❌ Export failed: {e}")
        return 1
    if n == 0:
        print("📭 No accepted/edited pairs in the store yet — accept or "
              "edit a proposal first")
        return 0
    print(f"📦 Exported {n} (asr, ref) pair(s) under {out_dir}/asr/{{en,hi}}/")
    print(f"   manifest: {manifest}")
    print("   Add audio by copying matching --save-audio WAVs (same "
          "timestamp prefix) into data/asr/<lang>/wav/")
    print("   Training stays a SEPARATE, opt-in offline step — see "
          "docs/FINETUNE_HI_OPTIONAL.md; enable via listener.hi_model / "
          "en_model only.")
    return 0


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
def transcription_worker(engine, utt_q: "queue.Queue", stats: dict,
                         headers: dict, ids: dict,
                         save_dir: Optional[str] = None) -> None:
    """Consume utterances and transcribe them forever.

    v6.1.6 NO-DROP BACKLOG: after taking one utterance, everything ELSE
    already waiting in the queue is drained and merged into ONE decode
    (up to listener.merge_max_s, default 25 s, 0.35 s gaps). On a CPU
    that decodes slower than the teacher speaks, v6.1.5 dropped the
    oldest utterances when the 12-slot queue filled — the teacher saw
    the first sentence work, then nothing. Now speech arrives late but
    complete, the queue drains in single jobs, and a ⏳ line shows the
    catch-up. Merged decodes measured 1.52x faster than separate ones.

    `engine` is either a WhisperRouter ("small-hi" mode) or a plain
    faster-whisper model (single-model mode) — both expose
    decode(audio_f32, base_kwargs, beam_override=None) -> (segments,
    info, tag) and pick their own route kwargs.
    """
    # v6.2.1 CRASH FIX: the watchdog below ASSIGNS MAX_UTTERANCE_FRAMES
    # (shortening the chunk cap when the CPU falls behind). Without this
    # `global`, Python treated the name as function-local everywhere in
    # this worker, and the FIRST read (the watchdog comparison) raised
    # UnboundLocalError — killing the whole transcriber thread after the
    # first sentence: 'initially it recognize but not after that'. The
    # global also matters for correctness: the assembler reads the same
    # module-level cap every frame, so only a global update makes the
    # shortened cap take effect in the capture pipeline.
    global MAX_UTTERANCE_FRAMES
    # self-seed: the worker must never die on a missing counter
    for _k in ("utterances", "sent", "short", "duplicate", "blips",
               "errors", "retries", "beam_retries", "rejected", "asr_s",
               "audio_s"):
        stats.setdefault(_k, 0)
    stats.setdefault("audio_s", 0.0)
    base_kwargs = build_transcribe_kwargs()
    carry = {"words": None, "t": 0.0}     # left-context continuation state
    adaptive = {"step": 0, "last": 0.0}   # sustained-RTF watchdog state
    # v6.2.1: the backlog drain below can CONSUME the None shutdown
    # sentinel while merging queued speech (it must not decode it). It
    # used to be dropped silently, leaving the worker polling an empty
    # queue forever after Ctrl+C. Preserve it and exit after this job.
    stop_after = {"none": False}

    while not STOP.is_set() and not stop_after["none"]:
        try:
            item = utt_q.get(timeout=0.5)
        except queue.Empty:
            continue
        if item is None:
            break
        # ---- drain + merge whatever is already queued ----
        parts = [item]
        total_s = item[2] / 1000.0
        while total_s < MERGE_MAX_S:
            try:
                nxt = utt_q.get_nowait()
            except queue.Empty:
                break
            if nxt is None:
                stop_after["none"] = True    # shutdown requested — finish
                break                        # this job, then exit
            parts.append(nxt)
            total_s += nxt[2] / 1000.0
        if len(parts) > 1:
            gap = np.zeros(int(SAMPLE_RATE * MERGE_GAP_S), dtype=np.int16)
            cat = []
            for i, part in enumerate(parts):
                if i:
                    cat.append(gap)
                cat.append(part[0])
            audio16 = np.concatenate(cat)
            noise_db = max(p[1] for p in parts)
            dur_ms = int(audio16.size / SAMPLE_RATE * 1000)
            stats["merged_jobs"] = stats.get("merged_jobs", 0) + 1
            stats["merged_chunks"] = \
                stats.get("merged_chunks", 0) + len(parts)
            print(f"⏳ Merged {len(parts)} queued chunks "
                  f"({dur_ms / 1000:.1f}s) into one decode — catching up, "
                  f"nothing dropped")
        else:
            audio16, noise_db, dur_ms = item
        stats["utterances"] = stats.get("utterances", 0) + len(parts)
        stats["audio_s"] = stats.get("audio_s", 0.0) + dur_ms / 1000.0
        if save_dir:
            try:
                _save_wav(save_dir, audio16, dur_ms)
            except Exception as e:
                print(f"⚠️ Could not save WAV: {e}")
        kept_segs = []
        lang = None
        model_tag = None
        t0 = time.time()
        audio_f32 = audio16.astype(np.float32) / 32768.0
        # v6.2.0 left-context continuation: the tail of the previous GOOD
        # transcript becomes the decoder's initial_prompt, so a chunk that
        # starts mid-sentence decodes in context. The echo is stripped
        # after decode (below), and the seam trim is a second net.
        job_kwargs = base_kwargs
        carry_used = None
        if CARRY_PROMPT_WORDS > 0 and carry["words"] and \
                time.time() - carry["t"] < 60.0:
            job_kwargs = dict(base_kwargs)
            job_kwargs["initial_prompt"] = " ".join(carry["words"])
            carry_used = carry["words"]
        raw_segs = []                        # v6.2.3: unfiltered decode output
        try:
            try:
                seg_iter, _info, model_tag = engine.decode(
                    audio_f32, job_kwargs, backlog_fn=utt_q.qsize)
                raw_segs = list(seg_iter)    # materialize once — the router
                                             # may hand back a one-shot
                                             # generator
                kept_segs = [seg for seg in raw_segs if segment_ok(seg)]
            except Exception as first_err:
                # Windows/Anaconda MKL allocator hiccup — recover with a
                # smaller beam instead of dropping the utterance
                msg = str(first_err).lower()
                if "mkl" in msg or "allocat" in msg:
                    stats["retries"] = stats.get("retries", 0) + 1
                    print("⚠️ ASR memory hiccup — retrying once with beam 2")
                    seg_iter, _info, model_tag = engine.decode(
                        audio_f32, job_kwargs, beam_override=2)
                    raw_segs = list(seg_iter)
                    kept_segs = [seg for seg in raw_segs if segment_ok(seg)]
                else:
                    raise
            # v6.1.5: the router already routes by language; only the
            # printed/sent label still uses smoothed auto detections in
            # single-model mode (router mode reports the real route).
            if model_tag is None:
                lang = smooth_language(getattr(_info, "language", None))
            else:
                lang = getattr(_info, "language", None) or lang
            conf = seg_confidence(kept_segs)   # duration-weighted, used
                                               # for EVERY decision below
            stats["asr_s"] = stats.get("asr_s", 0.0) + (time.time() - t0)
        except Exception as e:  # never kill the worker
            stats["errors"] = stats.get("errors", 0) + 1
            print(f"❌ Transcription error: {e}")
            continue

        # ---- v6.2.0 adaptive stability watchdog ----
        # Sustained RTF > 1 means this CPU cannot keep up: shorten the cap
        # (12 -> 9 -> 7 s, never below) so decodes stay small and the
        # merger catches up more often. Cooldown between steps; one-time
        # notice. Listener behaviour only — never blocks, never drops.
        if ADAPTIVE_MAX_UTT:
            # v6.2.1: guarded — a watchdog bug must never cost an utterance
            # (this is the block that killed v6.2.0's worker thread).
            try:
                a_s = stats.get("audio_s", 0.0)
                rtf_now = (stats.get("asr_s", 0.0) / a_s) if a_s > 1.0 \
                    else 0.0
                min_frames = round(ADAPTIVE_STEPS_S[-1] * 1000 / FRAME_MS)
                if (rtf_now > ADAPTIVE_RTF_TRIGGER
                        and adaptive["step"] < len(ADAPTIVE_STEPS_S)
                        and time.monotonic() - adaptive["last"]
                        > ADAPTIVE_COOLDOWN_S
                        and MAX_UTTERANCE_FRAMES > min_frames):
                    adaptive["last"] = time.monotonic()
                    new_s = ADAPTIVE_STEPS_S[adaptive["step"]]
                    adaptive["step"] += 1
                    MAX_UTTERANCE_FRAMES = round(new_s * 1000 / FRAME_MS)
                    print(f"🌡 CPU is behind (RTF {rtf_now:.1f}) — max "
                          f"chunk shortened to {new_s:.0f}s so the backlog "
                          f"clears faster (config: listener.adaptive_max_utt)")
                    if adaptive["step"] == 1:
                        # v6.2.2 (B2): one-time advice when the CPU cannot
                        # keep up — model/ pinning choices, measured.
                        print("      Behind by a lot? For Hindi-medium "
                              "periods \"language\": \"hi\" skips EN "
                              "probes; \"model_size\": \"base\" is the "
                              "fastest honest option (bench first: "
                              "--bench --ref).")
            except Exception as watchdog_err:
                print(f"⚠️ Watchdog check skipped: {watchdog_err}")

        # ---- opt-in adaptive beam retry (listener.beam_retry > 0) ----
        # Empty or very-low-confidence decode -> try ONCE at a wider beam.
        # Off by default: measured to double latency on slow CPUs and it
        # cannot rescue Hindi from a model that cannot parse Hindi.
        if (WHISPER_BEAM_RETRY
                and WHISPER_BEAM_RETRY > WHISPER_BEAM_SIZE
                and (conf is None or conf < CONF_RETRY_DB)):
            stats["beam_retries"] = stats.get("beam_retries", 0) + 1
            try:
                seg2, info2, tag2 = engine.decode(
                    audio_f32, job_kwargs,
                    beam_override=WHISPER_BEAM_RETRY)
                kept2 = [seg for seg in seg2 if segment_ok(seg)]
                conf2 = seg_confidence(kept2)
                if kept2 and (conf2 is not None
                              and (conf is None or conf2 > conf + 0.02)):
                    kept_segs, conf = kept2, conf2
                    lang = getattr(info2, "language", None) or lang
                    model_tag = tag2 or model_tag
                    print(f"🔁 Low confidence — re-decoded at beam "
                          f"{WHISPER_BEAM_RETRY} (conf {conf:.2f})")
            except Exception as e:
                print(f"⚠️ Beam retry skipped: {e}")

        texts = [seg.text.strip() for seg in kept_segs]
        transcript = clean_transcript(texts)
        # ---- v6.2.0 janitor: nothing noisy/loopy/symbol-only ships ----
        transcript = strip_meta_tokens(transcript)
        transcript, collapsed = collapse_repetition(transcript)
        if collapsed:
            stats["loops_collapsed"] = stats.get("loops_collapsed", 0) + 1
            print("🧹 Collapsed a repetition loop before posting")
        if not transcript or not has_letters(transcript):
            # v6.2.3/v6.3.0: WHY did this chunk produce nothing shippable?
            # Structured reason codes (spec P2 #9) instead of one opaque
            # line — every drop prints reason=<code> and is counted under
            # that code:
            #   no_speech    — VAD/decode found no speech at all
            #   low_conf     — speech detected but every segment fell
            #                  below the confidence gates
            #   short_noise  — the min-words gate (further below)
            #   duplicate / prompt_echo — repetition guards (below)
            # The gates themselves are NEVER disabled — but real speech
            # that landed just under the thresholds gets ONE budget-
            # gated second decode (soft_retry).
            if transcript:
                stats["rejected"] = stats.get("rejected", 0) + 1
                stats[SYMBOL_ONLY] = stats.get(SYMBOL_ONLY, 0) + 1
                print(f"⚠️ Ignored symbol-only output (reason={SYMBOL_ONLY}): "
                      f"'{transcript[:40]}'")
                continue
            nsp = [s for s in raw_segs
                   if getattr(s, "no_speech_prob", 0.0) > NO_SPEECH_DROP]
            if not raw_segs or (nsp and len(nsp) == len(raw_segs)):
                reason = NO_SPEECH
            else:
                reason = LOW_CONF
            # ---- v6.2.3 borderline rescue: ONE re-decode, budget-gated ----
            # A full utterance (the energy gate saw sustained speech) that
            # produced zero shippable segments is usually a decode that
            # landed just under the thresholds. One retry with slightly
            # lower decode thresholds and a hair lower hard-logprob floor
            # recovers it; the combo/compression/hallucination gates are
            # IDENTICAL on the retry, so junk still cannot ship. Max once
            # per utterance; skipped when the CPU is behind (rolling
            # RTF > 1) so a backlog never deepens.
            rescued = False
            a_s = stats.get("audio_s", 0.0)
            rtf_now = (stats.get("asr_s", 0.0) / a_s) if a_s > 1.0 else 0.0
            if (EMPTY_RETRY and dur_ms >= EMPTY_RETRY_MIN_MS
                    and rtf_now <= 1.0):
                stats["empty_retries"] = stats.get("empty_retries", 0) + 1
                t_retry = time.time()
                try:
                    retry_kwargs = dict(job_kwargs)
                    retry_kwargs["log_prob_threshold"] = EMPTY_RETRY_LOGPROB
                    retry_kwargs["no_speech_threshold"] = EMPTY_RETRY_NO_SPEECH
                    seg_iter2, info2, tag2 = engine.decode(audio_f32,
                                                           retry_kwargs)
                    kept2 = [s for s in seg_iter2
                             if segment_ok(s, logprob_hard=LOGPROB_RETRY_DROP)]
                    stats["asr_s"] = stats.get("asr_s", 0.0) + \
                        (time.time() - t_retry)
                    if kept2:
                        kept_segs = kept2
                        conf = seg_confidence(kept_segs)
                        lang = getattr(info2, "language", None) or lang
                        model_tag = tag2 or model_tag
                        transcript = clean_transcript(
                            [s.text.strip() for s in kept_segs])
                        transcript = strip_meta_tokens(transcript)
                        transcript, collapsed = collapse_repetition(transcript)
                        rescued = bool(transcript) and has_letters(transcript)
                        if rescued:
                            stats["empty_retry_wins"] = \
                                stats.get("empty_retry_wins", 0) + 1
                            print(f"♻️ Borderline chunk rescued on one "
                                  f"re-decode (first pass: {reason}"
                                  + (f", conf {conf:.2f})"
                                     if conf is not None else ")"))
                except Exception as retry_err:
                    print(f"⚠️ Retry decode skipped: {retry_err}")
            if not rescued:
                stats["rejected"] = stats.get("rejected", 0) + 1
                stats[reason] = stats.get(reason, 0) + 1
                print(f"🔇 drop (reason={reason}): captured "
                      f"{dur_ms / 1000:.1f}s but "
                      + ("no speech survived the decode"
                         if reason == NO_SPEECH
                         else "the confidence gate rejected every segment")
                      + (f" (conf {conf:.2f})" if conf is not None else "")
                      + " — speech unclear or too far from the mic")
                continue
        # ---- v6.2.2 A2: math fragment allowlist at the MIN_WORDS gate ----
        # 'three quarters.' / 'तीन चौथाई' are real math, not noise. The
        # exemption is decided ONCE here (symbol-only and hallucination
        # junk were already rejected above and can never ride it); the
        # keep note prints after the remaining gates so it reflects the
        # final text that actually ships.
        is_short = len(transcript.split()) < MIN_WORDS
        frag_allowed = is_short and math_fragment_allowed(transcript)
        if is_short and not frag_allowed:
            stats["short"] += 1
            stats[SHORT_NOISE] = stats.get(SHORT_NOISE, 0) + 1
            print(f"⚠️ Ignored short noise (reason={SHORT_NOISE}): "
                  f"'{transcript}'")
            # v6.2.3: short drops are experience too — the report shows how
            # much speech the min-words gate is eating (with the reason
            # code since v6.3.0)
            _exp_log_short_drop(transcript, _route_label(model_tag, lang),
                                noise_db, reason=SHORT_NOISE)
            continue
        if is_duplicate(transcript):
            stats["duplicate"] += 1
            print(f"⚠️ Ignored duplicate (reason={DUPLICATE}): "
                  f"'{transcript}'")
            continue
        # v6.1.6 seam-overlap trim: cap-split carries re-decode their tail
        # at the head of the next chunk; trim >= 4 matching seam words.
        try:
            transcript, n_trim = trim_overlap(transcript)
        except Exception:
            n_trim = 0
        if not transcript:
            # the whole chunk was the repeated tail — nothing new to post
            stats["duplicate"] += 1
            print(f"⚠️ Ignored repeated tail (reason={DUPLICATE}; "
                  f"{n_trim} words already posted from the previous "
                  f"chunk)")
            continue
        if n_trim:
            print(f"✂️ Trimmed {n_trim} repeated seam words (chunk overlap)")
        # v6.2.0 prompt-echo strip: with continuation prompting, Whisper
        # occasionally re-emits the prompt words first — drop them.
        if carry_used and transcript:
            ttoks = transcript.split()
            pk = [_word_key(w) for w in carry_used]
            tk = [_word_key(w) for w in ttoks]
            m = 0
            for k in range(min(len(pk), len(tk)), 0, -1):
                if tk[:k] == pk[-k:]:
                    m = k
                    break
            if m:
                transcript = " ".join(ttoks[m:]).strip()
                stats[PROMPT_ECHO] = stats.get(PROMPT_ECHO, 0) + 1
                if not transcript:
                    print(f"⚠️ Ignored prompt echo (reason={PROMPT_ECHO}; "
                          f"nothing new spoken)")
                    continue
        # ---- v6.2.2 A1: math phrase-tail stitch (before send) ----
        # If the PREVIOUS accepted transcript ended mid-claim ('one half is
        # greater than') or THIS text starts with a continuation cue
        # ('greater than three quarters'), join them into ONE transcript so
        # MathGuard sees the full claim — the tail that used to die as
        # 'Ignored short noise'. The janitor runs once on the combined
        # text; min_repeat=2 also un-doubles a seam the trim missed
        # ('…greater than' + 'greater than three quarters').
        stitched_prev = None
        try:
            transcript, stitched_prev = maybe_stitch(transcript)
        except Exception as stitch_err:
            print(f"⚠️ Stitch check skipped: {stitch_err}")
        if stitched_prev:
            transcript = collapse_repetition(
                strip_meta_tokens(transcript), min_repeat=2)[0]
            if not transcript or not has_letters(transcript):
                stats["rejected"] = stats.get("rejected", 0) + 1
                stats[LOW_CONF] = stats.get(LOW_CONF, 0) + 1
                print("⚠️ Stitched result failed the gate — dropped "
                      f"(reason={LOW_CONF})")
                continue
            stats["stitched"] = stats.get("stitched", 0) + 1
            print(f"🧩 Stitched onto the previous tail "
                  f"({len(stitched_prev)} words) — mid-claim split repaired")
        if looks_degenerate(transcript) and not stats.get("degen_hinted"):
            stats["degen_hinted"] = 1
            print("[i]   That transcript looks like a Whisper repetition "
                  "loop — the audio is hard to hear. Two fixes:\n"
                  '      1. Pin the language — add "language": "hi" (or '
                  '"en") to the listener section of config.json\n'
                  "      2. Hear what the mic captures:  python "
                  "mic_listener.py --save-audio")

        asr_t = time.time() - t0
        print(f"✅ Teacher said: {transcript}")
        print(f"📊 Noise: {noise_db}dB | ⏱ utterance {dur_ms / 1000:.1f}s | "
              f"⚡ ASR {asr_t:.1f}s"
              + (f" | 🎯 conf {conf:.2f}" if conf is not None else "")
              + (f" | 🗣 {lang}" if lang else "")
              + (f" | 🧠 {model_tag}" if model_tag else ""))
        if frag_allowed:
            print("🧮 Kept a math fragment below min-words (listener "
                  "allowlist — short fractions are real math, not noise)")
        _last_posted["text"], _last_posted["t"] = transcript, time.time()
        # v6.2.2: the stitch tail is refreshed from every ACCEPTED
        # transcript so the next mid-claim chunk can join it.
        _update_stitch_tail(transcript)
        # v6.2.0: refresh the continuation context from GOOD transcripts
        # only — never continue from garble (conf gate) or from a collapsed
        # loop (the tail is unreliable).
        if CARRY_PROMPT_WORDS > 0 and conf is not None and \
                conf >= CARRY_PROMPT_MIN_CONF and not collapsed:
            carry["words"] = transcript.split()[-CARRY_PROMPT_WORDS:]
            carry["t"] = time.time()
        else:
            carry["words"] = None
        if asr_t > (dur_ms / 1000.0) * 1.5 and not stats.get("slow_hinted"):
            stats["slow_hinted"] = 1
            print("[i]   ASR is slower than real time on this CPU. The "
                  "merger keeps every word (late but complete) and the "
                  "watchdog shortens chunks automatically. For real-time "
                  "output add this to config.json:\n"
                  '      "listener": { "model_size": "base", '
                  '"beam_size": 1, "cpu_threads": 0, "language": "hi" }')
        # v6.2.3: mirror EVERY ingest attempt into the experience store
        # (before the send — an unreachable API is still an attempt)
        _exp_log_ingest(transcript, _route_label(model_tag, lang), conf,
                        noise_db)
        resp = send_transcript(transcript, noise_db, headers, ids, conf, lang)
        if resp is not None:
            stats["sent"] += 1
            try:
                data = resp.json()
            except Exception:
                print(f"🤖 Response: HTTP {resp.status_code}")
                continue
            _print_agent_response(data)
            # v6.2.3: a Tier-3 proposal is an experience event. The
            # teacher's Accept/Reject/Edit arrives via the feedback
            # poller and lands as teacher_decision rows (accept ->
            # allowlist, reject -> false-pattern file, edit -> pair).
            try:
                math_info = data.get("math") or {}
                if data.get("approval_required") or math_info.get("statement"):
                    _exp_log_math_proposal(
                        str(math_info.get("statement")
                            or data.get("proposal") or ""),
                        transcript, _route_label(model_tag, lang),
                        note=f"tier={data.get('tier')}")
            except Exception:
                pass


def _transcriber_supervisor(engine, utt_q: "queue.Queue", stats: dict,
                            headers: dict, ids: dict,
                            save_dir: Optional[str] = None) -> None:
    """v6.2.1: the transcriber must NEVER die for the rest of a session.

    v6.2.0 shipped the missing-`global` watchdog bug: the worker thread
    raised UnboundLocalError on its first slow-CPU decode and everything
    stayed '⏳ queued' forever with no error visible after the traceback.
    The root cause is fixed in transcription_worker, but this supervisor
    guarantees the failure MODE can never return: if the worker exits for
    ANY reason while the session is live, it is restarted within a second
    and every chunk still in the queue is transcribed (nothing is lost —
    the merger picks them up)."""
    restarts = 0
    while not STOP.is_set():
        t = threading.Thread(target=transcription_worker,
                             args=(engine, utt_q, stats, headers, ids),
                             kwargs={"save_dir": save_dir}, daemon=True,
                             name="transcriber")
        t.start()
        t.join()
        if STOP.is_set():
            break
        restarts += 1
        stats["worker_restarts"] = restarts
        print(f"⚠️ Transcriber thread died and was restarted automatically "
              f"(#{restarts}) — {utt_q.qsize()} chunk(s) still queued and "
              f"safe; speech keeps flowing")
        time.sleep(1.0)


def _print_agent_response(data: dict) -> None:
    """Pretty-print the agent's structured decision for the teacher."""
    status = data.get("status")
    if status == "ignored":
        print(f"⏸ {data.get('reason', 'Agent is paused')}")
        return
    if data.get("math_verified"):
        print(f"🧮 Math verified — correct, no action needed.")
        return
    tier = data.get("tier")
    math_info = data.get("math") or {}   # NOT 'math' — that shadowed the
                                         # math module (AST audit finding)
    if status == "action_triggered":
        print(f"🤖 Event: {data.get('reason', '')}")
        if math_info.get("statement"):
            print(f"   🧮 Detected claim: {math_info['statement']} "
                  f"(verdict: {math_info.get('verdict')})")
    if data.get("approval_required"):
        print(f"⏳ Tier {tier} PROPOSAL — awaiting your YES (dashboard → Approvals): "
              f"{data.get('proposal', '')}")
        print(f"   {data.get('teacher_note', '')}")
    elif data.get("note"):
        print(f"📝 {data['note']}")


def assembler_loop(frame_q: "queue.Queue", utt_q: "queue.Queue",
                   stats: dict) -> None:
    asm = UtteranceAssembler()
    res = np.empty(0, dtype=np.int16)   # partial-frame carry between blocks
    last_block_ts = time.monotonic()
    last_hb_ts = time.monotonic()
    peak_db = -100.0
    stall_warned = False
    calibrated = False
    while not STOP.is_set():
        try:
            block = frame_q.get(timeout=0.5)
        except queue.Empty:
            block = None
        now = time.monotonic()

        # heartbeat: the console must never be a silent void — the teacher
        # should always see WHY nothing happens (mic peak vs. gate), and
        # since v6.1.6, how much speech is queued for transcription.
        if calibrated and HEARTBEAT_S > 0 and now - last_hb_ts >= HEARTBEAT_S:
            last_hb_ts = now
            gate = asm.floor_db + SPEECH_START_MARGIN_DB
            qn = utt_q.qsize()
            print(f"👂 listening… floor {asm.floor_db:.0f} dBFS | gate opens "
                  f"at {gate:.0f} | mic peak since last beat {peak_db:.0f} | "
                  f"utterances {stats['utterances']}"
                  + (f" | ⏳ {qn} queued" if qn else ""))
            if peak_db <= gate + 1.0:
                print("[i]   Mic peak never reached the gate — if you WERE "
                      "speaking, raise the mic volume / move closer, or set "
                      '"start_margin_db": 4 in config.json listener.')
            peak_db = -100.0

        if block is None:
            if now - last_block_ts > STALL_WARN_S and not stall_warned:
                stall_warned = True
                print(f"⚠️ No audio from the mic for {STALL_WARN_S:.0f} s — "
                      "device muted, disconnected, or the Windows default "
                      "input changed.\n"
                      "      Diagnose live:  python mic_listener.py --meter")
            continue

        last_block_ts = now
        stall_warned = False
        notice = asm.pop_calibration_notice()
        if notice:
            print(f"🔊 {notice}")
            calibrated = True
        frame_samples = max(1, int(ACTIVE_SR * FRAME_MS / 1000))
        try:
            if res.size:
                block = np.concatenate([res, block])
            n_full = block.size // frame_samples
            if n_full == 0:             # tiny block — carry it over
                res = block
                continue
            res = block[n_full * frame_samples:]
            for i in range(n_full):
                frame = block[i * frame_samples:(i + 1) * frame_samples]
                db = frame_dbfs(frame)   # cheap — feeds the heartbeat peak
                if db > peak_db:
                    peak_db = db
                out = asm.feed(frame)
                if out is None:
                    continue
                if not out["emit"]:
                    if out.get("reason"):
                        stats["blips"] += 1
                        print(f"⚠️ {out['reason']}")
                    continue
                if out.get("capped"):
                    stats["capped"] = stats.get("capped", 0) + 1
                    shift = out.get("cut_shift_ms", 0) / 1000.0
                    print(f"✂️ Long stretch — split at a quiet spot "
                          f"({shift:.1f} s carried into the next chunk)")
                    if stats["capped"] == 3:
                        print("[i]   Teacher speaks in long stretches — I "
                              "split at the quietest pause every ~12 s so "
                              "Whisper always gets clean word boundaries.\n"
                              "      Tune it with \"max_utt_s\" in the "
                              "config.json listener section.")
                audio16 = out["audio"]
                if ACTIVE_SR != SAMPLE_RATE:
                    audio16 = downsample_to_16k(audio16, ACTIVE_SR)
                try:
                    utt_q.put_nowait(
                        (audio16, out["noise_db"], out["dur_ms"]))
                except queue.Full:
                    try:                # drop the oldest, keep the newest
                        utt_q.get_nowait()
                        utt_q.put_nowait(
                            (audio16, out["noise_db"], out["dur_ms"]))
                        stats["backlog_dropped"] += 1
                        print("⚠️ Transcription is far behind — the merger "
                              "is already batching queued chunks; if this "
                              "keeps appearing, set \"model_size\": "
                              "\"base\" in config.json")
                    except queue.Empty:
                        pass
        except Exception as e:
            stats["errors"] += 1
            print(f"❌ Assembler error: {e}")


_last_status_ts = 0.0


def audio_callback(indata, frames, time_info, status, frame_q=None, stats=None):
    global _last_status_ts
    if status:
        stats["overflows"] = stats.get("overflows", 0) + 1
        now = time.monotonic()
        if now - _last_status_ts >= 10.0:    # throttled — no console spam
            _last_status_ts = now
            print(f"⚠️ audio status: {status} "
                  f"({stats['overflows']} so far)")
            if stats["overflows"] >= 3:
                print("[i]   Recurring overflow = samples are DROPPED before "
                      "ASR (garbles words). Fixes, in order of impact:\n"
                      "      1. Use a USB/headset mic instead of WO Mic / "
                      "Bluetooth\n"
                      "      2. Free CPU for capture: v6.1.1 already "
                      "reserves cores via cpu_threads — add \"model_size\": "
                      "\"base\" if it persists\n"
                      "      3. Keep \"block_ms\": 200 and latency \"high\" "
                      "(the defaults)")
    try:
        frame_q.put_nowait(indata[:, 0].copy())
    except queue.Full:
        stats["frame_dropped"] += 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def list_input_devices() -> None:
    import sounddevice as sd
    print("🎤 Input devices:")
    default_in = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "   ← default" if i == default_in else ""
            print(f"  [{i}] {d['name']}  ({int(d['default_samplerate'])} Hz){mark}")


def resolve_input_device(sd):
    dev = LISTENER_CFG.get("input_device")
    if dev is None or dev == "":
        return None
    if isinstance(dev, int):
        return dev
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and dev.lower() in str(d["name"]).lower():
            print(f"🎤 Using input device [{i}] {d['name']}")
            return i
    print(f"⚠️ Input device '{dev}' not found — using system default")
    return None


def check_api() -> None:
    try:
        httpx.get(f"{API_URL}/health", timeout=3.0)
        print("🩺 API healthy")
    except Exception:
        print("⚠️ API not reachable yet — transcripts will retry, but start "
              "the server to see responses")


def fetch_learning_hotwords(headers: dict) -> None:
    """Learning loop: pull evolved hotwords (roster aliases + tokens the
    teacher taught us by rejecting misheard corrections).

    v6.1.6: hotwords measured to DESTABILIZE decode on both models (EN:
    RTF 2.13 vs 0.23, 3/5 chunks rejected; HI fine-tune: conf -0.60,
    recovery 0.33). They are applied ONLY when the teacher opts in:
      "hotwords": "…custom words…"  (config wins; this fetch never
                                    overrides it)
      "hotwords": true              (use the learning-loop evolved set)
    Anything else — including the old default — means OFF."""
    global WHISPER_HOTWORDS
    if LISTENER_CFG.get("hotwords") and not _HOTWORDS_FROM_LEARNING:
        return          # the teacher's explicit hotwords always win
    try:
        r = httpx.get(f"{API_URL}/learning/prompt", headers=headers,
                      timeout=5.0)
        if r.status_code == 200:
            hw = (r.json() or {}).get("hotwords")
            if not hw:
                return
            if _HOTWORDS_FROM_LEARNING:
                WHISPER_HOTWORDS = hw
                print(f"📚 Learning loop: {len(hw.split())} evolved hotwords "
                      f"loaded (opted in via listener.hotwords = true)")
            else:
                print(f"[i]   Learning loop has {len(hw.split())} evolved "
                      "hotwords available — hotwords are OFF in v6.1.6 "
                      "(measured to slow decode 3-9x and destabilize it). "
                      "Opt in with \"hotwords\": true in the listener "
                      "section of config.json.")
    except Exception:
        pass          # offline / old backend — defaults still work


def _load_wav_f32(path: str):
    """Read a WAV (any common rate) as 16 kHz float32 for ASR."""
    import wave as _wave
    with _wave.open(path, "rb") as w:
        sr = w.getframerate()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if sr != SAMPLE_RATE:
        raw = downsample_to_16k(raw, sr)
    return raw.astype(np.float32) / 32768.0


def _bench_decode_production(engine, audio_f32, base_kwargs):
    """Decode one WAV through the PRODUCTION path: real UtteranceAssembler
    (12 s cap, word-gap cuts, pre-roll/trailing silence) + per-chunk decode
    + the segment gates + the janitor. This is what would ship live, so the
    bench WER is the honest number. Returns (text, conf, wall_s).

    2.2 s of digital silence is PREPENDED to mirror the live calibration
    ritual ("stay quiet for 2 s") — a recording that starts speaking
    immediately would otherwise have its first words eaten by calibration,
    which never happens in class.
    \"\"\""""
    pad = np.zeros(int(SAMPLE_RATE * 2.2), dtype=np.int16)
    audio16 = np.concatenate([pad, (audio_f32 * 32768.0).astype(np.int16)])
    asm = UtteranceAssembler()
    fs = int(SAMPLE_RATE * FRAME_MS / 1000)
    n = audio16.size // fs
    texts, confs, wall, audio_s = [], [], 0.0, 0.0
    for i in range(n):
        frame = audio16[i * fs:(i + 1) * fs]
        out = asm.feed(frame)
        if out is None or not out.get("emit"):
            continue
        a16 = out["audio"]
        f32 = a16.astype(np.float32) / 32768.0
        audio_s += f32.size / SAMPLE_RATE
        t0 = time.time()
        try:
            seg_iter, info, tag = engine.decode(f32, base_kwargs)
            kept = [s for s in seg_iter if segment_ok(s)]
        except Exception:
            continue
        wall += time.time() - t0
        c = seg_confidence(kept)
        if c is not None:
            confs.append((c, f32.size / SAMPLE_RATE))
        t = clean_transcript([s.text.strip() for s in kept])
        texts.append(collapse_repetition(strip_meta_tokens(t))[0])
    conf = (sum(c * d for c, d in confs) / sum(d for _, d in confs)
            if confs else None)
    text = clean_transcript(texts)
    return text, conf, wall, max(audio_s, 0.2)


def run_bench(wav_paths, ref: Optional[str] = None,
              models_csv: str = "base,small,small-hi") -> int:
    """--bench WAV... [--ref "exact words"]: transcribe each recording with
    the candidate models and rank them by word-level WER (when --ref is
    given) plus real-time factor and confidence. No mic, no API, no
    credentials needed — record a lesson with --save-audio first.

    Candidates: base (fastest), small (stock), small-hi (router: EN->stock,
    HI->fine-tune). WER is Devanagari-safe (whitespace tokens, punctuation
    and spoken-digit spellings normalized). Each WAV is decoded through
    the PRODUCTION path (real assembler chunking + gates + janitor), so
    the WER/RTF numbers reflect what would ship live.
    """
    _force_utf8_console()
    if os.path.exists(CONFIG_FILE):
        try:
            apply_overrides(load_config())
        except Exception:
            apply_overrides({})
    else:
        apply_overrides({})
    if HINDI_FT_MODEL != _HINDI_FT_DEFAULT:
        print(f"[i] Hindi model override active (listener.hi_model): "
              f"{HINDI_FT_MODEL} — the 'small-hi' row below benches THIS "
              f"model")
    want = [m.strip() for m in models_csv.split(",") if m.strip()]
    # --ref accepts "ref1 | ref2 | …" mapping 1:1 onto the WAV list (bench a
    # different passage per recording); a single ref applies to every WAV.
    per_wav_refs: dict = {}
    if ref and "|" in ref:
        parts = [p.strip() for p in ref.split("|") if p.strip()]
        if len(parts) == len(wav_paths):
            per_wav_refs = dict(zip(wav_paths, parts))
        else:
            print(f"⚠️ --ref has {len(parts)} '|'-separated passages but "
                  f"{len(wav_paths)} WAVs — using the full reference for "
                  "every WAV")
    from faster_whisper import WhisperModel
    print("🧠 Loading bench models (once per run)...")
    small = hi = None
    engines = []
    for m in want:
        try:
            if m == "small-hi":
                if small is None:
                    small = WhisperModel(EN_STOCK_MODEL or "small",
                                         device=WHISPER_DEVICE,
                                         compute_type=WHISPER_COMPUTE,
                                         cpu_threads=WHISPER_CPU_THREADS)
                if hi is None:
                    hi = WhisperModel(HINDI_FT_MODEL, device=WHISPER_DEVICE,
                                      compute_type=WHISPER_COMPUTE,
                                      cpu_threads=WHISPER_CPU_THREADS)
                stats: dict = {}
                router = WhisperRouter(small, hi, stats)
                # warm both models once so the first chunk's wall time does
                # not inflate RTF (in live class the models warm up on the
                # first utterance anyway)
                try:
                    list(router.decode(np.zeros(SAMPLE_RATE,
                                                dtype=np.float32),
                                       build_transcribe_kwargs()))
                except Exception:
                    pass
                # The live router probes language on the STOCK model, which
                # is reliable on real classroom audio but returns junk on
                # robotic/synthetic recordings. A bench recording of a KNOWN
                # passage has a known language — seed the sticky state from
                # the per-file reference script so the bench measures
                # model+pipeline, not the synthetic-audio probe artifact.
                seed_refs = per_wav_refs or (
                    {p: ref for p in wav_paths} if ref else {})
                if seed_refs:
                    langs = {"hi": 0, "en": 0}
                    for rtxt in seed_refs.values():
                        d, l = script_counts(rtxt)
                        langs["hi" if d > l else "en"] += 1
                    seed = "hi" if langs["hi"] >= langs["en"] else "en"
                    router._record(seed)
                    print(f"   🧭 small-hi router seeded '{seed}' from the "
                          f"reference script(s)")
                engines.append(("small-hi", router))
            else:
                mdl = WhisperModel(m, device=WHISPER_DEVICE,
                                   compute_type=WHISPER_COMPUTE,
                                   cpu_threads=WHISPER_CPU_THREADS)
                if m == "small" and small is None:
                    small = mdl
                engines.append((m, SingleEngine(mdl)))
        except Exception as e:
            print(f"⚠️ {m}: unavailable ({e}) — skipped")
    if not engines:
        print("❌ no bench model could be loaded")
        return 1
    base_kwargs = build_transcribe_kwargs()
    rows = []
    print()
    for name, engine in engines:
        wavs = []
        for p in wav_paths:
            try:
                audio_f32 = _load_wav_f32(p)
            except Exception as e:
                print(f"⚠️ {p}: cannot read ({e}) — skipped")
                continue
            wav_ref = per_wav_refs.get(p, ref)
            try:
                text, conf, wall, audio_s = _bench_decode_production(
                    engine, audio_f32, base_kwargs)
            except Exception as e:
                print(f"⚠️ {p}: decode failed on {name} ({e})")
                continue
            wavs.append({"wav": os.path.basename(p), "text": text,
                         "conf": conf, "rtf": wall / audio_s,
                         "ref": wav_ref, "tag": name})
        if wavs:
            rows.append((name, wavs))
        print(f"   ✔ {name} done")
    print()
    header = (f"{'model':<10} {'wav':<28} {'RTF':>5} {'conf':>6} "
              f"{'WER':>7}  text")
    print(header)
    print("-" * len(header))
    summary = []
    for name, wavs in rows:
        wers = []
        for wv in wavs:
            w = wer(wv["ref"], wv["text"]) if wv.get("ref") else None
            if w is not None:
                wers.append(w)
            print(f"{name:<10} {wv['wav']:<28} {wv['rtf']:>5.2f} "
                  f"{wv['conf'] if wv['conf'] is None else round(wv['conf'], 2)!s:>6} "
                  f"{('--' if w is None else f'{w * 100:5.1f}%'):>7}  "
                  f"{wv['text'][:60]}")
        if wers:
            summary.append((name, sum(wers) / len(wers),
                            sum(wv["rtf"] for wv in wavs) / len(wavs)))
    if summary:
        print()
        key = "WER" if ref else "RTF"
        for name, avg_w, avg_r in sorted(summary,
                                         key=lambda x: x[1] if ref else x[2]):
            print(f"   🏆 {name:<10} avg {key} "
                  f"{avg_w * 100:.1f}%" if ref else
                  f"   🏆 {name:<10} avg RTF {avg_r:.2f}x")
        if not ref:
            print('\n   Add --ref "the exact words spoken" for WER ranking.')
    print("\n[i]   Bench RTF is measured on THIS machine — if small-hi is "
          "above ~1.0x, prefer 'base' for live class; 'small-hi' stays the "
          "accuracy pick when the backlog merger keeps up.")
    print("[i]   Bench ONE recording per run (or several of the SAME "
          "language): the language router locks onto one language per "
          "run. Real classroom audio routes reliably; robotic/synthetic "
          "recordings may misprobe — the reference-seeding above covers "
          "the common case.")
    return 0


def run_meter() -> int:
    """Live mic level vs. speech gate — diagnoses 'not listening at all'.
    No Whisper needed; runs the exact same capture settings as the listener."""
    try:
        import sounddevice as sd
    except Exception:
        print("❌ Missing dependency: pip install sounddevice")
        return 1
    cfg = load_config()
    apply_overrides(cfg)
    device = resolve_input_device(sd)
    probe = device if device is not None else sd.default.device[0]
    try:
        name = sd.query_devices(probe)["name"]
    except Exception:
        name = "?"
    print(f"🎤 Metering: {name}")
    print("Speak normally. Each line = 0.5 s. The gate opens when 2 of the")
    print("last 3 frames exceed floor + start margin. Ctrl+C to stop.\n")
    meter_q: "queue.Queue" = queue.Queue(maxsize=100)
    window: deque = deque(maxlen=FLOOR_WINDOW_FRAMES)
    recent3: deque = deque(maxlen=3)
    got_audio = False
    first_ts = time.monotonic()

    def cb(indata, frames, time_info, status):
        nonlocal got_audio
        got_audio = True
        try:
            meter_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE,
                                blocksize=int(SAMPLE_RATE * BLOCK_MS / 1000),
                                dtype="int16", channels=1, device=device,
                                latency=AUDIO_LATENCY, callback=cb)
    except Exception as e:
        print(f"❌ Could not open the mic ({e}) — run --list-mics and set "
              "listener.input_device in config.json")
        return 1
    with stream:
        try:
            while True:
                time.sleep(0.5)
                dbs = []
                while True:
                    try:
                        blk = meter_q.get_nowait()
                    except queue.Empty:
                        break
                    fs = max(1, int(SAMPLE_RATE * FRAME_MS / 1000))
                    for i in range(blk.size // fs):
                        dbs.append(frame_dbfs(blk[i * fs:(i + 1) * fs]))
                if not dbs:
                    if not got_audio and time.monotonic() - first_ts > 5:
                        print("⚠️ Still no audio after 5 s — wrong device or "
                              "muted. Check:  python mic_listener.py --list-mics")
                    continue
                window.extend(dbs)
                cur = dbs[-1]
                if len(window) >= 20:
                    vals = sorted(window)
                    floor = vals[max(0, int(len(vals) * FLOOR_PERCENTILE / 100))]
                else:
                    floor = -45.0
                gate = floor + SPEECH_START_MARGIN_DB
                recent3.append(max(dbs))
                hot = sum(1 for m in recent3 if m > gate)
                bar = "#" * max(0, min(30, int(cur - floor)))
                opens = "SPEECH!" if hot >= 2 else ("warm" if hot == 1 else "-")
                print(f"  {cur:6.0f} dBFS |{bar:<30}| floor {floor:5.0f} | "
                      f"gate {gate:5.0f} | {opens}")
        except KeyboardInterrupt:
            pass
    print("\nMeter guide:")
    print("  - Bar does not move when you speak → Windows is capturing the "
          "wrong/quiet device. Fix it in Settings > Sound > Input, or set "
          "listener.input_device in config.json (see --list-mics).")
    print("  - Bar moves but stays below the gate → raise mic volume, move "
          "closer, or set \"start_margin_db\": 4 in config.json listener.")
    print("  - Shows SPEECH! here but the main listener stays deaf → report "
          "back (that would be a listener bug).")
    return 0


def main() -> int:
    global ACTIVE_SR
    _force_utf8_console()
    parser = argparse.ArgumentParser(description="Pro classroom mic listener")
    parser.add_argument("--list-mics", action="store_true",
                        help="list input devices and exit")
    parser.add_argument("--meter", action="store_true",
                        help="live mic level vs. speech gate — diagnose "
                             "'not listening at all' without Whisper")
    parser.add_argument("--save-audio", dest="save_audio", nargs="?",
                        const="saved_audio", default=None, metavar="DIR",
                        help="save every captured utterance as a WAV "
                             "(default dir: saved_audio) so you can hear "
                             "exactly what Whisper hears")
    parser.add_argument("--test-wav", dest="test_wav", nargs="+",
                        metavar="WAV",
                        help="transcribe WAV file(s) through the exact "
                             "live engine (router + gates) and print text "
                             "+ confidence — no mic needed. Pair it with "
                             "--save-audio recordings")
    parser.add_argument("--bench", dest="bench", nargs="+", metavar="WAV",
                        help="rank models (base / small / small-hi) on WAV "
                             "recording(s): WER vs --ref, real-time factor, "
                             "confidence. Use --save-audio recordings of a "
                             "real lesson for honest numbers")
    parser.add_argument("--ref", dest="ref", default=None,
                        help="the exact words spoken in the --bench WAVs "
                             '(quote it: --ref "तीन चौथाई एक आधे से बड़ा है")')
    parser.add_argument("--bench-models", dest="bench_models",
                        default="base,small,small-hi",
                        help="comma-separated bench candidates "
                             "(default: base,small,small-hi)")
    parser.add_argument("--preset", dest="preset", default=None,
                        metavar="NAME",
                        help="session preset: math_en (English math pilot: "
                             "stock EN model only, NO hi-model calls) | "
                             "hindi_class (Hindi-medium: hi model, no EN "
                             "probes) | auto (default: the measured "
                             "router). Overrides listener.preset in "
                             "config.json")
    parser.add_argument("--experience-report", dest="experience_report",
                        action="store_true",
                        help="summarize the local experience store: ingest / "
                             "short-drop / proposal counts, teacher "
                             "accept-reject-edit, latest corrected pairs "
                             "(no mic, no models, no credentials needed)")
    parser.add_argument("--experience-export", dest="experience_export",
                        nargs="?", const="data", default=None, metavar="DIR",
                        help="write accepted/edited (asr, ref) text pairs to "
                             "DIR/asr/{en,hi}/ (default: data) — OFFLINE and "
                             "opt-in; nothing is exported or trained "
                             "automatically")
    parser.add_argument("--experience-db", dest="experience_db",
                        default=None, metavar="PATH",
                        help="override the experience store path (default: "
                             "experience.db or listener.experience_db)")
    args = parser.parse_args()
    if args.experience_report:
        return run_experience_report(args.experience_db)
    if args.experience_export is not None:
        return run_experience_export(args.experience_export, args.experience_db)
    if args.meter:
        return run_meter()
    if args.list_mics:
        try:
            list_input_devices()
        except Exception as e:
            print(f"❌ Cannot list devices: {e}")
            print("   → pip install sounddevice")
        return 0
    if args.test_wav:
        return run_test_wav(args.test_wav)
    if args.bench:
        return run_bench(args.bench, args.ref, args.bench_models)

    cfg = load_config()
    # v6.3.0 (P2 #7): --preset math_en | hindi_class | auto wins over
    # listener.preset in config.json (apply_overrides does the merge and
    # prints the preset banner).
    if getattr(args, "preset", None):
        lis = cfg.get("listener") or {}
        lis["preset"] = args.preset
        cfg["listener"] = lis
    apply_overrides(cfg)
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    ids = {"class_id": cfg["class_id"], "lesson_id": cfg["lesson_id"]}

    try:
        import sounddevice as sd
    except Exception:
        print("❌ Missing dependency: pip install sounddevice")
        return 1

    check_api()
    fetch_learning_hotwords(headers)

    # v6.2.3: experience learning loop — local SQLite mirror + teacher
    # decision poller (best-effort; a missing endpoint stays silent)
    init_experience(ids["lesson_id"])
    exp_t0 = time.time()
    if EXP is not None:
        threading.Thread(target=_feedback_poller, args=(headers, STOP),
                         daemon=True, name="experience-feedback").start()
        print(f"📚 Experience loop on — every ingest/drop/proposal is "
              f"mirrored to {EXPERIENCE_DB}; teacher decisions are polled "
              f"every {FEEDBACK_POLL_S:.0f}s")

    print(f"🧠 Loading Whisper ({MODEL_SIZE}; first run downloads it once, "
          f"then fully offline)...")
    t0 = time.time()
    try:
        model, hi_model = load_models()
    except Exception as e:
        print(f"❌ Could not load faster-whisper: {e}")
        print("   → pip install faster-whisper")
        return 1
    frame_q: "queue.Queue" = queue.Queue(
        maxsize=max(10, int(12000 / BLOCK_MS)))
    utt_q: "queue.Queue" = queue.Queue(maxsize=TRANSCRIBE_QUEUE_MAX)
    stats = {"utterances": 0, "sent": 0, "short": 0, "duplicate": 0,
             "blips": 0,
             "capped": 0, "errors": 0, "backlog_dropped": 0,
             "frame_dropped": 0, "asr_s": 0.0, "audio_s": 0.0,
             "rejected": 0}
    if hi_model is not None:
        engine = WhisperRouter(model, hi_model, stats)
        route_txt = "router small-hi (EN->stock, HI->fine-tune)"
    else:
        engine = SingleEngine(model)
        route_txt = ("pinned " + WHISPER_LANGUAGE if WHISPER_LANGUAGE
                     else "auto")
    hw_txt = (f"hotwords on ({len(WHISPER_HOTWORDS.split())} words, EN route)"
              if WHISPER_HOTWORDS else "hotwords off")
    ip_txt = "domain-prompt on (EN)" if INITIAL_PROMPT else "domain-prompt off"
    if MATH_INITIAL_PROMPT:
        ip_txt += " +math-prompt(EN)"
    if HINDI_CLASSROOM_PROMPT:
        ip_txt += " +hi-classroom-prompt(HI)"
    st_txt = (f"math-stitch {STITCH_TAIL_WORDS}w" if STITCH_TAIL_WORDS > 0
              else "math-stitch off")
    print(f"✅ Whisper ready in {time.time() - t0:.1f}s "
          f"({WHISPER_DEVICE}/{WHISPER_COMPUTE}, beam {WHISPER_BEAM_SIZE}, "
          f"cpu_threads {WHISPER_CPU_THREADS}, {BLOCK_MS} ms blocks, "
          f"{MODEL_SIZE}, language={route_txt}, {hw_txt}, {ip_txt}, "
          f"no-timestamps={'on' if WITHOUT_TIMESTAMPS else 'off'}, "
          f"backlog-merge<={MERGE_MAX_S:.0f}s, carry-prompt "
          f"{CARRY_PROMPT_WORDS}w, {st_txt}, watchdog "
          f"{'on' if ADAPTIVE_MAX_UTT else 'off'})")
    # v6.2.3: the session language lock, spelled out so the teacher knows
    # exactly what is guaranteed
    if WHISPER_LANGUAGE == "en":
        print("🔒 Language lock: EN — every chunk decodes on the stock "
              "English model; NOTHING can route to the Hindi model, so "
              "accented English math can no longer come out as Devanagari "
              "soup. Hindi-medium lesson instead? Set \"language\": \"hi\".")
    elif WHISPER_LANGUAGE == "hi":
        print("🔒 Language lock: HI — every chunk decodes on the Hindi "
              "model, EN probes skipped (less CPU thrash). English math "
              "pilot instead? Set \"language\": \"en\".")
    else:
        print("🗣 Language: auto (the measured router). Mixed lesson? Lock "
              "it for the hour: \"language\": \"en\" for the math pilot, "
              "\"hi\" for Hindi-medium.")

    import functools
    cb = functools.partial(audio_callback, frame_q=frame_q, stats=stats)

    device = resolve_input_device(sd)
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE,
                                blocksize=int(SAMPLE_RATE * BLOCK_MS / 1000),
                                dtype="int16", channels=1, device=device,
                                latency=AUDIO_LATENCY,
                                callback=cb)
        ACTIVE_SR = SAMPLE_RATE
    except Exception:
        probe = device if device is not None else sd.default.device[0]
        native = int(sd.query_devices(probe)["default_samplerate"]) or 48000
        print(f"⚠️ 16 kHz not supported by this device — capturing at "
              f"{native} Hz and resampling to 16 kHz")
        stream = sd.InputStream(samplerate=native,
                                blocksize=int(native * BLOCK_MS / 1000),
                                dtype="int16", channels=1, device=device,
                                latency=AUDIO_LATENCY,
                                callback=cb)
        ACTIVE_SR = native

    threads = [
        threading.Thread(target=assembler_loop, args=(frame_q, utt_q, stats),
                         daemon=True, name="assembler"),
        # v6.2.1: the supervisor wraps the worker — a worker crash now
        # costs one warning line + a restart, never the session.
        threading.Thread(target=_transcriber_supervisor,
                         args=(engine, utt_q, stats, headers, ids),
                         kwargs={"save_dir": args.save_audio},
                         daemon=True, name="transcriber-supervisor"),
    ]
    for t in threads:
        t.start()

    max_utt_s = MAX_UTTERANCE_FRAMES * FRAME_MS / 1000.0
    print(f"\n🎤 Pro Continuous Listening Engaged — local Whisper, adaptive "
          "noise floor, VAD on, six-parameter assessment, no-drop backlog.")
    print(f"   Speak normally; ~1.2 s of quiet closes a sentence "
          f"(~{max_utt_s:.0f} s max chunk, split at the quietest pause). "
          f"Ctrl+C to stop.")
    print("   (Calibrating from room noise for 2 s — stay quiet)")
    print(f"   👂 A 'listening…' status line prints every {HEARTBEAT_S:.0f} s — "
          "if the mic peak never reaches the gate, run:  "
          "python mic_listener.py --meter")
    print("   🖥 Teacher dashboard: http://localhost:8501  (start_all.py "
          "launches it when streamlit is installed)")
    if not args.save_audio:
        print("   🔍 Text garbled? Record what the mic hears:  "
              "python mic_listener.py --save-audio")

    with stream:
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nStopping listener...")
            STOP.set()

    utt_q.put(None)
    for t in threads:
        t.join(timeout=5.0)
    print(f"📈 Session: {stats['utterances']} utterances transcribed, "
          f"{stats['sent']} sent, {stats['short']} short-noise ignored, "
          f"{stats.get('duplicate', 0)} duplicates suppressed, "
          f"{stats['blips']} blips "
          f"filtered, {stats['capped']} cap-splits, "
          f"{stats.get('merged_jobs', 0)} merged jobs "
          f"({stats.get('merged_chunks', 0)} chunks), "
          f"{stats.get('rejected', 0)} empty rejects, "
          f"{stats.get('loops_collapsed', 0)} loops collapsed, "
          f"{stats.get('stitched', 0)} claims stitched, "
          f"{stats.get('frag_kept', 0)} math fragments kept, "
          f"{stats.get('script_fixes', 0)} script-fixes, "
          f"{stats.get('beam_retries', 0)} beam-retries, "
          f"{stats['errors']} errors"
          + (f", {stats['worker_restarts']} worker restarts"
             if stats.get("worker_restarts") else "")
          + (f", {stats.get('routed_hi', 0)} hi-routed/"
             f"{stats.get('routed_en', 0)} en-routed"
             f" ({stats.get('probes_skipped', 0)} probes skipped)"
             if stats.get("routed_hi") or stats.get("routed_en") else ""))
    print(f"   🚫 Drops by reason (grep 'reason='): "
          f"{stats.get(NO_SPEECH, 0)} {NO_SPEECH} | "
          f"{stats.get(LOW_CONF, 0)} {LOW_CONF} | "
          f"{stats.get(SHORT_NOISE, 0)} {SHORT_NOISE} | "
          f"{stats.get(DUPLICATE, 0)} {DUPLICATE} | "
          f"{stats.get(PROMPT_ECHO, 0)} {PROMPT_ECHO} | "
          f"{stats.get(SYMBOL_ONLY, 0)} {SYMBOL_ONLY} "
          f"({stats.get('empty_retries', 0)} borderline retried, "
          f"{stats.get('empty_retry_wins', 0)} rescued)")
    if EXP is not None:
        try:
            es = EXP.summary(since=exp_t0)
            print(f"   📚 Experience this session: {es.get('total', 0)} "
                  f"events ({es.get('teacher_decision', 0)} teacher "
                  f"decisions: {es.get('accept', 0)} accept / "
                  f"{es.get('reject', 0)} reject / {es.get('edit', 0)} "
                  f"edit) — see: python mic_listener.py "
                  f"--experience-report")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())