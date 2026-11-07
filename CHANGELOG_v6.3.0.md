# CHANGELOG — classroom_copilot live listener v6.3.0 ("Pilot Workbench")

Scope: presets, structured drop reasons, modular codebase, hardened math
stitch, experience-report CLI. **No behavior change outside the presets +
stitch + experience + reason codes**; FastAPI `/audio/ingest` contract,
MathGuard Tier-3 approval, watchdog/merger/stitch/router and the default-OFF
hotwords are all preserved.

Maps the four open production pains:

| Pain (production log) | Fix in v6.3.0 |
| --- | --- |
| "confidence gate rejected every segment" (opaque empty rejects) | Every drop now prints a structured `reason=` code (`no_speech`, `low_conf`, `short_noise`, `duplicate`, `prompt_echo`); the borderline rescue is an explicit `soft_retry` flag (once per utterance, budget-gated, gates never disabled) |
| Accented English math → Devanagari soup | `--preset math_en` / `listener.language: "en"` HARD LOCK: the Hindi model is never loaded (`load_models` skips it) and never called (router refuses the hi route and skips script-sanity cross-decodes under the lock) |
| "three quarters" tail dropped as short noise (split claim) | math-stitch hardened: more incomplete cues (EN "is greater"/"is less"/"is equal"; HI "इससे बड़ा"/"इससे छोटा"/"बराबर है") and a wider spoken-fraction allowlist ("three by four", "one upon two", "एक बटा दो"…) |
| No learning between lessons | `experience_store` (+drop-reason column), teacher accept→allowlist / reject→false-pattern / edit→(asr→teacher) pair, `python -m tools.experience_report` (and `mic_listener.py --experience-report`) |

## Added
- **Presets (P2 #7)**: `listener.preset` in config.json and `--preset math_en | hindi_class | auto` on the CLI (CLI wins). `math_en` = English math pilot with the hard lock above; `hindi_class` = Hindi-medium (hi model pinned, EN probes skipped, no EN math hotwords, no EN-route prompts); `auto` = unchanged measured router. Preset keys override the user's config; unknown preset names warn and fall back to auto (never wedge the router). Both teaching presets force `hotwords: null` — they stay OFF (measured 3–9× slower).
- **Structured drop reason codes (P2 #9)**: `listener/reasons.py`; every drop line prints `reason=<code>`; session summary prints a per-code breakdown (grep `reason=` in a pilot log).
- **`listener/` package (P3 #12)**: `audio_gate` (AdaptiveGate + dBFS math), `assembler` (utterance state machine + word-gap cap cuts), `asr_router` (RouteConfig + dual-model router + segment gates + WER), `math_stitch` (cues + allowlist), `janitor` (loops/meta/symbol-only), `experience_store`, `reasons`, `presets`. `mic_listener.py` remains the main listener loop / composition root. All modules import without faster-whisper/sounddevice → CI-able offline.
- **`tools/experience_report.py` (P2 #11)**: `python -m tools.experience_report [--db PATH]` — counts by event type, teacher accept/reject/edit, short drops by reason, latest corrected pairs. Same renderer as `--experience-report`.
- **Drop reason in the experience store**: `experience_events.reason` column (auto-migrated in place for v6.2.3 DBs); the report shows short drops by reason.
- **`listener.soft_retry`** config key (v6.3.0 name for the borderline empty-reject rescue; `listener.empty_retry` still honored, `soft_retry` wins if both set). Default unchanged (on) because it is strictly once-per-utterance, RTF-budget-gated and the confidence gates never relax.
- **Tests**: `tests/test_v63_acceptance.py` — 31 offline pytest tests, including the four mandatory regressions (math_en never calls hi; stitch "three quarters"; short math allowlist not dropped; experience row on accept) plus ingest-contract, merger, watchdog, soft-retry and preset coverage. Legacy `tests/test_listener.py` = 172 checks, all green.

## Changed
- `mic_listener.py` is now the composition root: tunables/config/threads stay, moved logic is imported from `listener/*` with thin delegates (public API surface preserved — legacy tests pass unchanged except 4 reason-key assertions updated to the new codes).
- Worker drop lines now carry structured codes: `⚠️ Ignored short noise (reason=short_noise)`, `🔇 drop (reason=low_conf|no_speech)`, `⚠️ Ignored duplicate (reason=duplicate)`, `⚠️ Ignored prompt echo (reason=prompt_echo)`, `⚠️ Ignored symbol-only output (reason=symbol_only)` (extra operational code).
- Session summary counters renamed to the codes (`dupes`→`duplicate`, `prompt_echoes`→`prompt_echo`, `rejected_*`→code names).
- `experience.py` is now a backward-compatibility shim over `listener/experience_store.py`.
- `python tests/test_listener.py` no longer `sys.exit()`s at import time (pytest-safe).

## Fixed
- EN-route script-sanity cross-decode can no longer fire under the `language: "en"` lock (belt-and-braces on top of the v6.2.3 route lock; caught by the new acceptance suite).
- `config.example.json` now ships the preset + soft_retry keys.

## Will NOT do in this PR
- No global hotwords by default (presets force them off; opt-in unchanged).
- No runtime fine-tuning, no silent weight updates; training stays an offline, opt-in export (`--experience-export`) + separate recipe.
- No cloud ASR; no change to the FastAPI ingest contract; no MathGuard/teacher-approval changes; no emotion/discipline logic touched.
