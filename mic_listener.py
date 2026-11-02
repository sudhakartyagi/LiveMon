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

PIPELINE
  mic (16 kHz mono) -> frame queue -> adaptive gate + utterance assembler
      (390 ms pre-roll, ~1.2 s trailing silence closes an utterance)
    -> transcription queue -> faster-whisper (VAD on, beam 5, math hotwords)
    -> confidence / hallucination / duplicate filters
    -> POST {API_URL}/audio/ingest   (JSON contract + confidence field)

SETUP (Windows PowerShell)
  pip install -r requirements_audio.txt
  python mic_listener.py --list-mics     # optional: see / pick a microphone
  python mic_listener.py

  First run downloads the Whisper model once (small = ~475 MB), then it is
  fully offline. On a weak laptop use "base"; on a GPU use "medium"/"large-v3".

CONFIG (optional — config.json keeps working exactly as before)
  {
    "token": "...", "class_id": "...", "lesson_id": "...",
    "api_url": "http://localhost:8000",
    "listener": {
      "input_device": "WO Mic",
      "model_size": "small",
      "language": null,
      "hotwords": "fraction half quarter numerator denominator greater than",
      "min_words": 3
    }
  }
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

# ---------------------------------------------------------------------------
# Tunables (config.json -> "listener" section can override most of these)
# ---------------------------------------------------------------------------
API_URL = "http://localhost:8000"
CONFIG_FILE = "config.json"

SAMPLE_RATE = 16000          # Whisper's native rate
FRAME_MS = 30                # analysis frame = 30 ms (independent of mic rate)

SPEECH_START_MARGIN_DB = 8.0     # speech starts when frame > floor + 8 dB
SPEECH_CONTINUE_MARGIN_DB = 4.0  # utterance stays open while > floor + 4 dB
FLOOR_WINDOW_FRAMES = 100        # ~3 s rolling window for the noise floor
FLOOR_PERCENTILE = 20            # floor = 20th percentile of recent frames
ABSOLUTE_SILENCE_DB = -85.0      # below this = digital dropout, NOT room tone
WARMUP_FRAMES = 66               # 2 s of listening-only calibration at start
PRE_ROLL_FRAMES = 13             # ~390 ms kept BEFORE speech starts
SILENCE_FRAMES_TO_END = 40       # ~1.2 s of quiet closes an utterance
                                 # (teacher mid-thought pauses are 0.8-1.1 s;
                                 # 0.9 s clipped words like "whole tea[m]")
MAX_UTTERANCE_FRAMES = 1000      # ~30 s hard cap
MIN_UTTERANCE_MS = 400           # shorter than this = noise blip
MIN_SPEECH_FRAMES = 4            # needs >=120 ms of real speech energy

MODEL_SIZE = "small"             # tiny | base | small | medium | large-v3
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
WHISPER_LANGUAGE: Optional[str] = None   # None = auto (good for Hinglish)
WHISPER_BEAM_SIZE = 5

# Vocabulary bias for Class 4-5 math (kills "one third" -> "three letters"
# style mishearings). Override with config.json -> listener.hotwords.
WHISPER_HOTWORDS: Optional[str] = (
    "fraction half quarter one half one third three fourths "
    "numerator denominator plus minus into divided by equals "
    "not equal to greater than less than place value carry over remainder"
)

MIN_WORDS = 3
DEDUPE_WINDOW_S = 10.0

NOISE_DB_OFFSET = 5              # parity with previous API tuning (+5)
NOISE_DB_CAP = 100

NO_SPEECH_DROP = 0.6             # segment filters (hallucination guard)
LOGPROB_COMBO_DROP = -0.75
LOGPROB_HARD_DROP = -1.1
COMPRESSION_LOOP_DROP = 2.4

FRAME_QUEUE_MAX = 400
TRANSCRIBE_QUEUE_MAX = 12
HTTP_TIMEOUT_S = 30.0
HTTP_RETRIES = 2

HALLUCINATION_RE = re.compile(
    r"(thanks?\s+for\s+watching|thank\s+you\s+(so\s+much\s+)?for\s+watching"
    r"|like\s+and\s+subscribe|please\s+subscribe|^\s*subscribe\b"
    r"|\bamara\.org\b|字幕|^\s*subtitles?\b|^\s*mbc\s"
    r"|^\s*\[(music|applause|laughter|silence|inaudible|noise|blanks?_?audio)\]\s*[.!]?\s*$"
    r"|^\s*(ok(ay)?|bye|yeah|you|so|and|the|a|uh|um|hmm|mm-?hmm)\s*[.!?,]?\s*$)",
    re.IGNORECASE,
)

ACTIVE_SR = SAMPLE_RATE          # actual capture rate (fallback resamples)
STOP = threading.Event()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LISTENER_CFG: dict = {}


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
    global WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_BEAM_SIZE
    lis = cfg.get("listener") or {}
    LISTENER_CFG.update(lis)
    API_URL = lis.get("api_url", cfg.get("api_url", API_URL))
    MODEL_SIZE = lis.get("model_size", MODEL_SIZE)
    WHISPER_LANGUAGE = lis.get("language", WHISPER_LANGUAGE)
    WHISPER_HOTWORDS = lis.get("hotwords", WHISPER_HOTWORDS)
    MIN_WORDS = int(lis.get("min_words", MIN_WORDS))
    WHISPER_DEVICE = lis.get("device", WHISPER_DEVICE)
    WHISPER_COMPUTE = lis.get("compute_type", WHISPER_COMPUTE)
    WHISPER_BEAM_SIZE = int(lis.get("beam_size", WHISPER_BEAM_SIZE))


# ---------------------------------------------------------------------------
# Pure audio helpers (unit-testable, no hardware needed)
# ---------------------------------------------------------------------------
def frame_dbfs(frame: np.ndarray) -> float:
    """Energy of an int16 frame in dBFS (0 dBFS = full scale)."""
    if frame.size == 0:
        return -100.0
    rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))))
    if rms <= 0:
        return -100.0
    return max(-100.0, 20.0 * math.log10(rms / 32768.0))


def api_noise_db(rms16: float) -> int:
    """Same formula the API was tuned with: min(100, 20*log10(rms)+5)."""
    if rms16 <= 0:
        return 0
    return min(NOISE_DB_CAP, int(20.0 * math.log10(rms16) + NOISE_DB_OFFSET))


def downsample_to_16k(x: np.ndarray, native_sr: int) -> np.ndarray:
    """Cheap anti-aliased decimation to 16 kHz for ASR (mono int16)."""
    if native_sr == SAMPLE_RATE or x.size == 0:
        return x
    xf = x.astype(np.float64)
    factor = native_sr / SAMPLE_RATE
    win = max(1, int(round(factor)))
    kernel = np.ones(win) / win
    xf = np.convolve(xf, kernel, mode="same")   # cheap low-pass
    idx = np.arange(0.0, xf.size, factor)
    out = np.interp(idx, np.arange(xf.size, dtype=np.float64), xf)
    return out.astype(np.int16)


class UtteranceAssembler:
    """Adaptive-gate utterance builder.

    - Noise floor = 20th percentile of recent background frames, so it follows
      the room (fan, AC, corridor noise) instead of a hard-coded 200/400.
    - Speech starts when 2 of the last 3 frames exceed floor + 8 dB.
    - The pre-roll ring guarantees the first word is never clipped.
    - ~0.9 s of trailing silence (or a 30 s cap) closes the utterance.
    - The floor is updated ONLY from non-speech frames, so continuous teacher
      speech never drags the floor up and hides quieter students.
    """

    def __init__(self) -> None:
        self._floor: deque = deque(maxlen=FLOOR_WINDOW_FRAMES)
        self._warmup = WARMUP_FRAMES
        self._cal_notice = False
        self._reset()

    def _reset(self) -> None:
        self._state = "idle"
        self._pre: deque = deque(maxlen=PRE_ROLL_FRAMES)
        self._buf: list = []
        self._recent: deque = deque(maxlen=3)
        self._silence = 0
        self._speech_frames = 0
        self._speech_sq = 0.0
        self._speech_n = 0

    @property
    def floor_db(self) -> float:
        if len(self._floor) < 20:
            return -45.0
        vals = sorted(self._floor)
        return vals[max(0, int(len(vals) * FLOOR_PERCENTILE / 100))]

    def pop_calibration_notice(self) -> Optional[str]:
        if self._cal_notice:
            self._cal_notice = False
            return (f"Calibrated. Noise floor: {self.floor_db:.0f} dBFS "
                    f"(adapts to the room continuously)")
        return None

    def feed(self, frame: np.ndarray) -> Optional[dict]:
        """Consume one 30 ms frame. Returns a result dict when an utterance
        closes, else None. Result: {emit, audio, noise_db, dur_ms, reason}."""
        db = frame_dbfs(frame)
        floor = self.floor_db
        margin = db - floor

        # Adapt the floor only from frames that look like background.
        # Digital dropouts (all-zero frames — espeak pauses, USB/WO Mic
        # glitches) must NEVER seed the floor, or room tone starts looking
        # like speech and the gate never closes. -85 dBFS is far below any
        # real acoustic noise floor a laptop mic can produce.
        if margin < SPEECH_START_MARGIN_DB and db > ABSOLUTE_SILENCE_DB:
            self._floor.append(db)

        if self._warmup > 0:
            self._warmup -= 1
            if self._warmup == 0:
                self._cal_notice = True
            self._pre.append(frame)
            return None

        if self._state == "idle":
            self._pre.append(frame)
            self._recent.append(margin)
            hot = sum(1 for m in self._recent if m > SPEECH_START_MARGIN_DB)
            if len(self._recent) == 3 and hot >= 2:
                self._state = "speech"
                self._buf = list(self._pre)          # pre-roll included
                self._silence = 0
                self._speech_frames = 0
                self._speech_sq = 0.0
                self._speech_n = 0
            return None

        # ---- speech state ----
        self._buf.append(frame)
        if margin > SPEECH_CONTINUE_MARGIN_DB:
            self._silence = 0
            self._speech_frames += 1
            self._speech_sq += float(np.sum(np.square(frame.astype(np.float64))))
            self._speech_n += frame.size
        else:
            self._silence += 1

        if self._silence < SILENCE_FRAMES_TO_END and len(self._buf) < MAX_UTTERANCE_FRAMES:
            return None

        # ---- finalize ----
        audio = np.concatenate(self._buf)
        dur_ms = len(self._buf) * FRAME_MS
        if self._speech_n > 0:
            rms16 = math.sqrt(self._speech_sq / self._speech_n)
        else:
            rms16 = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
        speech_frames = self._speech_frames      # snapshot BEFORE reset
        self._reset()

        if dur_ms < MIN_UTTERANCE_MS:
            return {"emit": False, "reason": f"skipped: too short ({dur_ms} ms)"}
        if speech_frames < MIN_SPEECH_FRAMES:
            return {"emit": False,
                    "reason": "skipped: noise blip without sustained speech"}
        return {"emit": True, "audio": audio, "noise_db": api_noise_db(rms16),
                "dur_ms": dur_ms}


_last = {"norm": "", "t": 0.0}


def is_duplicate(transcript: str) -> bool:
    """Suppress Whisper repetition loops: same normalized text within 10 s."""
    now = time.time()
    norm = re.sub(r"[^a-z0-9\u0900-\u097F]+", "", transcript.lower())
    dup = bool(norm) and norm == _last["norm"] and (now - _last["t"]) < DEDUPE_WINDOW_S
    if not dup:
        _last["norm"], _last["t"] = norm, now
    return dup


def clean_transcript(texts: list) -> str:
    return re.sub(r"\s+", " ", " ".join(t for t in texts if t)).strip()


def segment_ok(seg) -> bool:
    """Confidence + hallucination gate for one Whisper segment."""
    t = (getattr(seg, "text", "") or "").strip()
    if not t:
        return False
    if getattr(seg, "no_speech_prob", 0.0) > NO_SPEECH_DROP and \
       getattr(seg, "avg_logprob", 0.0) < LOGPROB_COMBO_DROP:
        return False
    if getattr(seg, "avg_logprob", 0.0) < LOGPROB_HARD_DROP:
        return False
    if getattr(seg, "compression_ratio", 0.0) > COMPRESSION_LOOP_DROP:
        return False
    if HALLUCINATION_RE.search(t):
        return False
    return True


def send_transcript(transcript: str, noise_db: int, headers: dict, ids: dict,
                    confidence: Optional[float] = None):
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
# Threads
# ---------------------------------------------------------------------------
def transcription_worker(model, utt_q: "queue.Queue", stats: dict,
                         headers: dict, ids: dict) -> None:
    kwargs = dict(
        language=WHISPER_LANGUAGE,
        beam_size=WHISPER_BEAM_SIZE,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 160},
        condition_on_previous_text=False,   # stops hallucination carry-over
        temperature=[0.0, 0.2],
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
    )
    if WHISPER_HOTWORDS:
        kwargs["hotwords"] = WHISPER_HOTWORDS

    while not STOP.is_set():
        try:
            item = utt_q.get(timeout=0.5)
        except queue.Empty:
            continue
        if item is None:
            break
        audio16, noise_db, dur_ms = item
        stats["utterances"] += 1
        kept_segs = []
        try:
            t0 = time.time()
            segments, _info = model.transcribe(
                audio16.astype(np.float32) / 32768.0, **kwargs)
            kept_segs = [seg for seg in segments if segment_ok(seg)]
            texts = [seg.text.strip() for seg in kept_segs]
            transcript = clean_transcript(texts)
            stats["asr_s"] += time.time() - t0
        except Exception as e:  # never kill the worker
            stats["errors"] += 1
            print(f"❌ Transcription error: {e}")
            continue

        if not transcript:
            continue
        if len(transcript.split()) < MIN_WORDS:
            stats["short"] += 1
            print(f"⚠️ Ignored short noise: '{transcript}'")
            continue
        if is_duplicate(transcript):
            stats["dupes"] += 1
            print(f"⚠️ Ignored duplicate: '{transcript}'")
            continue

        # average log-prob of the kept segments -> ASR confidence signal
        conf = None
        if kept_segs:
            try:
                conf = sum(getattr(s, "avg_logprob", 0.0) or 0.0
                           for s in kept_segs) / len(kept_segs)
            except Exception:
                conf = None

        print(f"✅ Teacher said: {transcript}")
        print(f"📊 Noise: {noise_db}dB | ⏱ utterance {dur_ms / 1000:.1f}s | "
              f"⚡ ASR {(time.time() - t0):.1f}s"
              + (f" | 🎯 conf {conf:.2f}" if conf is not None else ""))
        resp = send_transcript(transcript, noise_db, headers, ids, conf)
        if resp is not None:
            stats["sent"] += 1
            try:
                data = resp.json()
            except Exception:
                print(f"🤖 Response: HTTP {resp.status_code}")
                continue
            _print_agent_response(data)


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
    math = data.get("math") or {}
    if status == "action_triggered":
        print(f"🤖 Event: {data.get('reason', '')}")
        if math.get("statement"):
            print(f"   🧮 Detected claim: {math['statement']} (verdict: {math.get('verdict')})")
    if data.get("approval_required"):
        print(f"⏳ Tier {tier} PROPOSAL — awaiting your YES (dashboard → Approvals): "
              f"{data.get('proposal', '')}")
        print(f"   {data.get('teacher_note', '')}")
    elif data.get("note"):
        print(f"📝 {data['note']}")


def assembler_loop(frame_q: "queue.Queue", utt_q: "queue.Queue",
                   stats: dict) -> None:
    asm = UtteranceAssembler()
    while not STOP.is_set():
        try:
            frame = frame_q.get(timeout=0.5)
        except queue.Empty:
            continue
        notice = asm.pop_calibration_notice()
        if notice:
            print(f"🔊 {notice}")
        try:
            out = asm.feed(frame)
        except Exception as e:
            stats["errors"] += 1
            print(f"❌ Assembler error: {e}")
            continue
        if out is None:
            continue
        if not out["emit"]:
            if out.get("reason"):
                stats["blips"] += 1
                print(f"⚠️ {out['reason']}")
            continue
        audio16 = out["audio"]
        if ACTIVE_SR != SAMPLE_RATE:
            audio16 = downsample_to_16k(audio16, ACTIVE_SR)
        try:
            utt_q.put_nowait((audio16, out["noise_db"], out["dur_ms"]))
        except queue.Full:
            try:                      # drop the oldest, keep the newest
                utt_q.get_nowait()
                utt_q.put_nowait((audio16, out["noise_db"], out["dur_ms"]))
                stats["backlog_dropped"] += 1
                print("⚠️ Speech is faster than transcription — consider "
                      "\"model_size\": \"base\" in config.json")
            except queue.Empty:
                pass


def audio_callback(indata, frames, time_info, status, frame_q=None, stats=None):
    if status:
        print(f"⚠️ audio status: {status}")
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


def main() -> int:
    global ACTIVE_SR
    parser = argparse.ArgumentParser(description="Pro classroom mic listener")
    parser.add_argument("--list-mics", action="store_true",
                        help="list input devices and exit")
    args = parser.parse_args()
    if args.list_mics:
        try:
            list_input_devices()
        except Exception as e:
            print(f"❌ Cannot list devices: {e}")
            print("   → pip install sounddevice")
        return 0

    cfg = load_config()
    apply_overrides(cfg)
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    ids = {"class_id": cfg["class_id"], "lesson_id": cfg["lesson_id"]}

    try:
        import sounddevice as sd
    except Exception:
        print("❌ Missing dependency: pip install sounddevice")
        return 1

    check_api()

    print(f"🧠 Loading Whisper '{MODEL_SIZE}' "
          f"(first run downloads it once, then fully offline)...")
    t0 = time.time()
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(MODEL_SIZE, device=WHISPER_DEVICE,
                             compute_type=WHISPER_COMPUTE)
    except Exception as e:
        print(f"❌ Could not load faster-whisper: {e}")
        print("   → pip install faster-whisper")
        return 1
    print(f"✅ Whisper ready in {time.time() - t0:.1f}s "
          f"({WHISPER_DEVICE}/{WHISPER_COMPUTE}, beam {WHISPER_BEAM_SIZE}, "
          f"language={'auto' if not WHISPER_LANGUAGE else WHISPER_LANGUAGE})")

    frame_q: "queue.Queue" = queue.Queue(maxsize=FRAME_QUEUE_MAX)
    utt_q: "queue.Queue" = queue.Queue(maxsize=TRANSCRIBE_QUEUE_MAX)
    stats = {"utterances": 0, "sent": 0, "short": 0, "dupes": 0, "blips": 0,
             "errors": 0, "backlog_dropped": 0, "frame_dropped": 0, "asr_s": 0.0}

    import functools
    cb = functools.partial(audio_callback, frame_q=frame_q, stats=stats)

    device = resolve_input_device(sd)
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE,
                                blocksize=int(SAMPLE_RATE * FRAME_MS / 1000),
                                dtype="int16", channels=1, device=device,
                                callback=cb)
        ACTIVE_SR = SAMPLE_RATE
    except Exception:
        probe = device if device is not None else sd.default.device[0]
        native = int(sd.query_devices(probe)["default_samplerate"]) or 48000
        print(f"⚠️ 16 kHz not supported by this device — capturing at "
              f"{native} Hz and resampling to 16 kHz")
        stream = sd.InputStream(samplerate=native,
                                blocksize=int(native * FRAME_MS / 1000),
                                dtype="int16", channels=1, device=device,
                                callback=cb)
        ACTIVE_SR = native

    threads = [
        threading.Thread(target=assembler_loop, args=(frame_q, utt_q, stats),
                         daemon=True, name="assembler"),
        threading.Thread(target=transcription_worker,
                         args=(model, utt_q, stats, headers, ids),
                         daemon=True, name="transcriber"),
    ]
    for t in threads:
        t.start()

    print("\n🎤 Pro Continuous Listening Engaged — local Whisper, adaptive "
          "noise floor, VAD on, math hotwords.")
    print("   Speak normally; ~1.2 s of quiet closes a sentence. Ctrl+C to stop.")
    print("   (Calibrating from room noise for 2 s — stay quiet)")

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
          f"{stats['dupes']} duplicates suppressed, {stats['blips']} blips "
          f"filtered, {stats['errors']} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())