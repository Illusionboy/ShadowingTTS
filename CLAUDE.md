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

## Architecture

### Core Adapter Pattern

Every TTS provider implements `TTSAdapter` ([tts_arena/base.py](tts_arena/base.py)):

- `name: str` — used as the normalized key (`edge_tts`, `google_chirp_3`, etc.)
- `async def synthesize(request: TTSRequest) -> TTSResult`
- `TTSRequest` carries: `text`, `output_dir`, `output_format`, `reference_video`, `voice`, `speaker`, `output_stem`

Adapters live in [tts_arena/adapters/](tts_arena/adapters/). To add a new provider, subclass `TTSAdapter`, implement `synthesize`, register it in `build_adapters()` in [tts_arena/cli.py](tts_arena/cli.py) and in `default_dialogue_voices()` in [tts_arena/pipeline.py](tts_arena/pipeline.py).

### Two Execution Paths

**Arena (monologue):** `TTSArena.run()` in [tts_arena/arena.py](tts_arena/arena.py) calls all adapters concurrently with `asyncio.gather`. Results and pass/fail status are written to `outputs/results.json` by `write_results_manifest()`.

**Dialogue:** `run_dialogue()` in [tts_arena/dialogue.py](tts_arena/dialogue.py) calls each adapter sequentially per turn, then uses `ffmpeg` to concatenate segments with configurable `pause_ms` silence between them. Segment files land under `outputs/_dialogue_segments/<adapter_key>/`. The final merged file is `<adapter_key>_dialogue.<format>`.

### VideoSRT Integration (watch_dir)

`tts_arena/subtitle.py` provides two async helpers:

- `submit_to_watch_dir(audio_path, watch_dir)` — copies the file over
- `wait_for_subtitle(audio_stem, out_dir, bilingual, timeout)` — polls for `{stem}_bi.srt`
- `submit_and_wait(...)` — convenience wrapper for both

The Telegram bot calls `submit_and_wait` as an `asyncio.create_task` background task after sending audio. When `{audio_stem}_bi.srt` appears in `VIDEOSRT_OUT_DIR`, it is sent back to the user as a document. If `VIDEOSRT_WATCH_DIR` is empty, the feature is silently skipped. VideoSRT itself runs as an independent process (`python master_multiprcs.py`) on the GPU host monitoring the watch directory.

### Telegram Service Flow

[tts_arena/telegram_bot.py](tts_arena/telegram_bot.py) → user sends text → bot prompts for language + dialogue/monologue → [tts_arena/pipeline.py](tts_arena/pipeline.py) `synthesize_user_dialogue()` → `GeminiDialogueNormalizer` converts free-form input to structured `DialogueScript` → `run_dialogue()` with ElevenLabs → MP3 sent back. Each run is isolated under `outputs/service/<timestamp>/`.

If `ENABLE_GEMINI_DIALOGUE_PARSER=false`, `normalize_without_llm()` in [tts_arena/gemini_normalizer.py](tts_arena/gemini_normalizer.py) handles `A:/B:` lines or plain text as a fallback.

### Configuration

All env access goes through helpers in [tts_arena/config.py](tts_arena/config.py): `env()`, `required_env()`, `env_path()`. `load_environment()` loads `.env` from the project root first, then falls back to shell env. `build_adapters()` in `cli.py` calls `required_env()` for provider keys, so missing credentials raise at startup rather than at synthesis time.

### Dialogue Voice Resolution

Voice per speaker per provider is stored in `DialogueScript.voices: dict[str, dict[str, str]]` — keyed as `voices[speaker][adapter_key]`. `_voice_for()` in `dialogue.py` resolves this; falling back to `"default"` if provider-specific voice is absent. For the Telegram service, `default_dialogue_voices()` in `pipeline.py` reads per-provider env vars (`ELEVENLABS_VOICE_ID` / `ELEVENLABS_VOICE_ID2`, `EDGE_TTS_VOICE_A` / `B`, etc.).

## Provider-Specific Notes

- **ElevenLabs**: restricted to `eleven_flash_v2_5` or `eleven_turbo_v2_5`. Dialogue uses `ELEVENLABS_VOICE_ID` (speaker A) and `ELEVENLABS_VOICE_ID2` (speaker B). Set `ELEVENLABS_ENABLE_CLONING=true` to create an Instant Voice Clone from `ref_japanese.mp4` (leave `ELEVENLABS_VOICE_ID` empty).
- **Google Chirp 3**: uses Application Default Credentials or `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service account JSON.
- **GPT-SoVITS**: calls a local HTTP API. Sends `GPT_SOVITS_CKPT_PATH` to `/set_model` before synthesis. If running on a remote host, set `GPT_SOVITS_REF_AUDIO_PATH` to the WAV path on that machine; otherwise the adapter extracts `ref_japanese.mp4` locally.
- **Azure**: requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` (default `japaneast`).
