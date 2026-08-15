# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
conda create -n shadowingtts python=3.11 -y
conda activate shadowingtts
pip install -r requirements.txt
cp .env.example .env
# fill in provider keys, then:
```

`ffmpeg` must be installed for audio concatenation (dialogue mode) and reference audio extraction (ElevenLabs cloning / GPT-SoVITS).

## Run Commands

**Single-model quick test:**

```bash
python -m tts_arena.cli --models edge
```

**All models, long sentence:**

```bash
python -m tts_arena.cli --text-file examples/japanese_long_sentence.txt --output-dir outputs --format mp3
```

**Dialogue mode:**

```bash
python -m tts_arena.cli --dialogue-file examples/dialogue_shadowing.json --output-dir outputs --format mp3 --models edge,azure,openai
```

**Retry only failed providers from the previous run:**

```bash
python -m tts_arena.cli --text-file examples/japanese_long_sentence.txt --rerun-failed
```

**Telegram bot service:**

```bash
python -m tts_arena.telegram_bot
```

**Daily 3PL/SCM bilingual lesson (scheduled job):**

```bash
python -m tts_arena.daily                      # today's rotation, JA + EN
python -m tts_arena.daily --list-scenarios     # scenario library
python -m tts_arena.daily --dry-run --scenario incident_mis_shipment --no-push
python -m tts_arena.daily --provider edge --skip-subtitles --no-push --force
python -m tts_arena.daily --scene-text "客户投诉托盘破损要求赔偿"
```

`--dry-run` costs only a Gemini call; `--provider edge` keeps audio free while testing.
Point `DAILY_NAS_DIR` somewhere local when testing off the GPU host, otherwise the job
writes to `/mnt/nas/videos/TTS`.

There is no test suite and no linter config. The cheapest smoke test is `python -m tts_arena.cli --models edge` — Edge TTS needs no credentials, so it exercises the adapter/arena/manifest path end-to-end. Add `--dialogue-file examples/dialogue_shadowing.json` to also cover the ffmpeg concat path.

`build_adapters()` calls `required_env()` only for the models named in `--models`, so a run limited to one provider never trips on missing keys for the others. The default `--models` value is all six, which requires every provider key.

## Architecture

### Core Adapter Pattern

Every TTS provider implements `TTSAdapter` ([tts_arena/base.py](tts_arena/base.py)):

- `name: str` — human-readable ("Edge TTS"); `adapter_key()` in `dialogue.py` normalizes it to `edge_tts`, `google_chirp_3`, etc.
- `async def synthesize(request: TTSRequest) -> TTSResult`
- `TTSRequest` carries: `text`, `output_dir`, `output_format`, `reference_video`, `voice`, `speaker`, `output_stem`, `voice_settings`
- `TTSAdapter.output_path(request)` is the shared naming helper — use it instead of building paths, so `output_stem` is honored.

Adapters live in [tts_arena/adapters/](tts_arena/adapters/). They import their heavy SDK inside `synthesize()` (see [edge.py](tts_arena/adapters/edge.py)) so a missing optional dependency only breaks the provider that needs it. To add a provider: subclass `TTSAdapter`, implement `synthesize`, export it from [adapters/\_\_init\_\_.py](tts_arena/adapters/__init__.py), register it in `build_adapters()` and `MODEL_ALIASES` in [tts_arena/cli.py](tts_arena/cli.py), and add its voice branch to `default_dialogue_voices()` in [tts_arena/pipeline.py](tts_arena/pipeline.py).

**Three parallel naming spaces** — keep them in sync when touching providers:

| Space | Example | Used by |
| --- | --- | --- |
| CLI alias | `gpt-sovits` | `--models`, `MODEL_ALIASES`, `DEFAULT_TTS_PROVIDER`, `default_dialogue_voices(provider)` |
| `adapter.name` | `GPT-SoVITS` | `results.json`, `result_table()`, `--rerun-failed` lookup via `MODEL_NAMES_TO_ALIASES` |
| `adapter_key()` | `gpt_sovits` | dialogue voice maps, segment directories, default output filenames |

### Two Execution Paths

**Arena (monologue):** `TTSArena.run()` in [tts_arena/arena.py](tts_arena/arena.py) calls all adapters concurrently with `asyncio.gather`. Results and pass/fail status are written to `outputs/results.json` by `write_results_manifest()`.

**Dialogue:** `run_dialogue()` in [tts_arena/dialogue.py](tts_arena/dialogue.py) fans out across adapters concurrently but walks each adapter's turns sequentially, then uses `ffmpeg` to concatenate segments with configurable `pause_ms` silence between them. Segment files land under `outputs/_dialogue_segments/<adapter_key>/`; concat scratch files under `_dialogue_concat/`. Everything is normalized to mono 44.1 kHz before concat. The merged file is `<adapter_key>_dialogue.<format>` unless `output_stem` is passed (the Telegram service passes `<topic_slug>_<timestamp>`).

Failure isolation differs by path: the arena catches per-adapter exceptions in `_safe_synthesize()`; dialogue catches inside `_run_adapter_dialogue()` and fails the whole conversation for that provider if any single turn fails.

### VideoSRT Integration (watch_dir)

[tts_arena/subtitle.py](tts_arena/subtitle.py) provides three async helpers:

- `submit_to_watch_dir(audio_path, watch_dir, lang)` — copies the file in as `{stem}.{lang}{ext}`, appending `_2`, `_3` … if that name already exists so an in-flight job is never overwritten
- `wait_for_subtitle(audio_stem, out_dir, bilingual, timeout)` — polls for `{stem}_bi.srt`
- `submit_and_wait(...)` — wrapper; derives the polling stem by stripping the trailing `.{lang}` segment, because VideoSRT drops the lang code when naming its output

The filename contract is load-bearing: VideoSRT reads the language from the submitted filename and **keeps** it on its own outputs, so `dialogue.ja.mp3` produces `dialogue.ja_bi.srt` (ShadowReader classifies by that suffix). `wait_for_subtitle()` polls that name first and the lang-stripped `dialogue_bi.srt` second, so either side can be upgraded independently. Changing the naming on both sides at once silently breaks subtitle delivery — the poll just times out. The interface is documented in [forTTS/SUBTITLE_INTERFACE.md](forTTS/SUBTITLE_INTERFACE.md) — that directory holds the VideoSRT-side reference docs, and `forTTS.bak/` is a gitignored snapshot.

The Telegram bot calls `submit_and_wait` as an `asyncio.create_task` background task after sending audio, so audio delivery is never blocked on subtitles. If either `VIDEOSRT_WATCH_DIR` or `VIDEOSRT_OUT_DIR` is empty, the feature is silently skipped. VideoSRT itself runs as an independent process (`python master_multiprcs.py`) on the GPU host monitoring the watch directory.

### Daily Lesson Pipeline (tts_arena/daily/)

A second product on top of the same adapters: one 3PL/SCM/warehouse workplace scene per
day, rendered as **parallel Japanese and English dialogues** (same facts and conclusions,
each idiomatic rather than translated), subtitled by VideoSRT and published to the NAS.

`run_lesson()` in [daily/job.py](tts_arena/daily/job.py) is the single orchestration entry
point, shared by two triggers: the systemd timer (`python -m tts_arena.daily`) and the
Telegram commands `/daily`, `/scene`, `/scenes`, `/pick`. Sequence: pick scenario → one
Gemini call producing `DailyLesson` (ja_turns + en_turns + glossary) → `run_dialogue()` per
language → publish audio → submit both to the VideoSRT watch dir → wait for
`{stem}.{lang}_bi.srt` → publish subtitles, script markdown and meta JSON → Telegram push.

- **Stems**: `{YYYYMMDD}_{topic_slug}`, plus `_{HHMM}` for ad-hoc bot runs. The stem must
  never contain the lang code — `submit_to_watch_dir()` appends it, so per-language audio
  is kept in separate `outputs/daily/{date}/{lang}/` directories to avoid a name clash and
  is renamed to `{stem}.{lang}.mp3` only when published.
- **Single-flight lock**: `outputs/daily/.lock` holds the owning pid (stale locks from dead
  pids are cleared). The timer and the bot run in different processes; the loser gets
  `LessonBusy` rather than queueing, because ElevenLabs quota and the single Whisper worker
  do not tolerate parallel runs.
- **Rotation**: `outputs/daily/state.json` keeps a shuffled queue of scenario ids; a
  scenario is consumed only when a *scheduled* run succeeds. `/pick` and `/scene` do not
  consume the queue, they only append to `outputs/daily/history.jsonl` (which also enforces
  `DAILY_ADHOC_LIMIT`).
- **Subtitles come from the script, not from ASR** (`DAILY_SUBTITLE_SOURCE=script`, the
  default). Every turn is synthesized as its own file, so
  [daily/srtgen.py](tts_arena/daily/srtgen.py) ffprobes the segments, lays them out with
  `DAILY_PAUSE_MS` between them, and scales the timeline to the merged file's real duration
  to absorb mp3 encoder padding — sub-10ms accurate, with the exact text plus the `text_zh`
  translation carried in the lesson. `DAILY_SUBTITLE_SOURCE=whisper` restores the VideoSRT
  round trip (needed only for audio we did not generate); in that mode a timeout is not a
  failure — the stem is recorded in `outputs/daily/pending_srt.json` and
  `reconcile_pending()`, called at the start of every run, publishes whatever arrived late.
- **Japanese text must be TTS-safe**: `unsafe_ja_turns()` rejects Latin runs and 〇〇-style
  placeholders in Japanese turns, and one repair pass rewrites them. See the ElevenLabs note
  under Provider-Specific Notes for the measurements behind this.
- **Content bank**: [daily/content/scenarios.json](tts_arena/daily/content/scenarios.json)
  (54 scenarios across `daily_ops`, `reporting`, `customer`, `supplier`, `incident`,
  `negotiation`) and `glossary.json` (per-category term lists injected into the prompt to
  keep terminology consistent). A scenario's `register` (`formal` / `casual`) drives both
  the Japanese politeness level and `voice_settings_for_register()`.

### Telegram Service Flow

[tts_arena/telegram_bot.py](tts_arena/telegram_bot.py) → user sends text → bot prompts for language + dialogue/monologue → [tts_arena/pipeline.py](tts_arena/pipeline.py) `synthesize_user_dialogue()` → `GeminiDialogueNormalizer` converts free-form input to structured `DialogueScript` → `run_dialogue()` with ElevenLabs → MP3 sent back. Each run is isolated under `outputs/service/<timestamp>/`, alongside a `dialogue.json` dump of the normalized script.

The bot's language choice affects only the Gemini prompt language and the `.{lang}` suffix on the file sent to Telegram and to the VideoSRT watch dir. It does not change voice selection — `default_dialogue_voices()` resolves the same env-configured (Japanese-oriented) voices for every language.

If `ENABLE_GEMINI_DIALOGUE_PARSER=false`, `normalize_without_llm()` in [tts_arena/gemini_normalizer.py](tts_arena/gemini_normalizer.py) handles `A:/B:` lines or plain text as a fallback — note it also loses the LLM-generated `topic_slug` (falls back to the mode name), which in turn changes output filenames and the topic-based voice tuning below.

Alongside that free-text flow, the bot exposes the daily lesson pipeline: `/daily` (rotation
scenario now), `/pick <id>`, `/scenes`, and `/scene <描述>` (Gemini drafts a structured
scenario from a free-form description, then the normal lesson run). `/scene` with no argument
sets `user_data["pending_action"] = "scene"`, which `handle_text()` checks **before** the
existing shadowing flow — that early branch is the only change to the original text path.
Callback data uses the `lesson:` prefix so it cannot collide with `lang:` / `mode:`.
Runs are dispatched with `asyncio.create_task` and report progress by editing one status
message; they take 5–20 minutes and must never block the polling loop.

The bot's handlers swallow all exceptions and reply with a generic Chinese error message; real causes only reach the log via `logger.exception`. When debugging a service failure, read the log, not the chat.

`TELEGRAM_ALLOWED_USER_IDS` empty means *everyone* is allowed (warn-only) — fine locally, not in deployment.

### Configuration

All env access goes through helpers in [tts_arena/config.py](tts_arena/config.py): `env()`, `required_env()`, `env_path()`. `env()` treats whitespace-only values as unset and returns the default, so a blank line in `.env` behaves like an absent key. `load_environment()` loads `.env` from the project root first, then falls back to shell env, and is called only from the two entrypoints (`cli.main_async()`, `telegram_bot.main()`) — a new entrypoint or script must call it itself.

`pipeline.py` imports `build_adapters` and `env_bool` from `cli.py`, so the CLI module is a dependency of the service path, not just a script. Keep it import-safe.

### Dialogue Voice Resolution

Voice per speaker per provider is stored in `DialogueScript.voices: dict[str, dict[str, str]]` — keyed as `voices[speaker][adapter_key]`. `_voice_for()` in `dialogue.py` resolves this; falling back to `"default"` if provider-specific voice is absent. For the Telegram service, `default_dialogue_voices()` in `pipeline.py` reads per-provider env vars (`ELEVENLABS_VOICE_ID` / `ELEVENLABS_VOICE_ID2`, `EDGE_TTS_VOICE_A` / `B`, etc.). Note the dialogue-only `_A` / `_B` env vars are not in `.env.example`; the monologue CLI uses the single-voice vars (`AZURE_TTS_VOICE`, `OPENAI_TTS_VOICE`, …) instead.

### Topic-Aware Voice Settings

`_voice_settings_for_topic()` in `pipeline.py` matches keyword substrings against the Gemini-produced `topic_slug` and returns an ElevenLabs `voice_settings` dict (formal / casual / general presets). It flows through `run_dialogue(voice_settings_override=...)` → `TTSRequest.voice_settings` → the request body. Only [adapters/elevenlabs.py](tts_arena/adapters/elevenlabs.py) consumes this field; every other adapter ignores it, so tuning changes are inert unless the ElevenLabs provider is in play. The adapter has its own hardcoded default settings for when the field is `None`.

## Provider-Specific Notes

- **ElevenLabs**: constructor rejects any model outside `eleven_flash_v2_5` / `eleven_turbo_v2_5` (cost control). Dialogue uses `ELEVENLABS_VOICE_ID` (speaker A) and `ELEVENLABS_VOICE_ID2` (speaker B); if `ELEVENLABS_VOICE_ID2` is unset, B silently reuses A's voice. With no voice id and cloning off, the adapter picks the *first voice in the account* — an easy source of "why did the voice change" confusion. Set `ELEVENLABS_ENABLE_CLONING=true` to create an Instant Voice Clone from the reference media (leave `ELEVENLABS_VOICE_ID` empty); each run creates a new cloned voice in the account.
- **Google Chirp 3**: uses Application Default Credentials or `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service account JSON.
- **GPT-SoVITS**: calls a local HTTP API. Sends `GPT_SOVITS_CKPT_PATH` to `/set_model` before synthesis. If running on a remote host, set `GPT_SOVITS_REF_AUDIO_PATH` to the WAV path on that machine; otherwise the adapter extracts `ref_japanese.mp4` locally.
- **Azure**: requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` (default `japaneast`).
- **ElevenLabs Japanese, measured** (A/B over 17 clips, scored by transcribing each back with
  faster-whisper large-v3):
  - Always send `language_code` (`TTSRequest.language`). Flash/Turbo v2.5 support language
    enforcement — without it the model re-guesses per request and can voice kanji with
    Chinese readings. It is *not* supported by `eleven_multilingual_v2`.
  - Ordinary Japanese, dates and counters are fine (`5月15日`, `10個` came back verbatim in
    every variant). The failure mode is **Latin codes and digits fused to kanji**: `AS987便`,
    `987便`, `第987便`, `九八七便` and even the kana `エーエス987便` all came back as noise
    (`急遽ペン`, `局場機弁`). Separating them works: `品番ピー001` → `P001`,
    「便名はエー・エス、番号はきゅうはちなな」 → `AS`, `987`.
  - `apply_text_normalization: "on"` made v2.5 output *worse*, not better; leave it at `auto`.
  - `eleven_multilingual_v2` was the worst of all variants for these voices, and it cannot
    take `language_code`. Stay on turbo/flash v2.5.
  - High `style` with low `stability` slurs articulation; the register presets are now
    calm (`stability` 0.40–0.45, `style` 0.30–0.35).
- **Whisper round-trip is lossy**, which is why the daily job no longer uses it for its own
  audio: domain vocabulary degraded (`3PL` → `スリンPL`, `仕入先` → `支入船`, `貨物` → `刃物`)
  even when the audio was correct.
- **Reference media**: `TTS_REFERENCE_VIDEO` defaults to `ref_japanese.mp4`, but the repo only ships `ref_japanese.wav`. Anything needing a reference (ElevenLabs cloning, local GPT-SoVITS) requires pointing that var at a file that actually exists. `ensure_reference_wav()` in [tts_arena/audio.py](tts_arena/audio.py) caches the extracted WAV under `<output_dir>/_reference_audio/` and re-extracts only when the source is newer.
