# Multi-Model TTS Evaluation Arena

This module compares Japanese speech synthesis across six providers through one async Adapter Pattern interface.

## Architecture

- `tts_arena/base.py`: shared `TTSAdapter`, `TTSRequest`, and `TTSResult` contracts.
- `tts_arena/adapters/*`: one adapter per TTS provider.
- `tts_arena/arena.py`: concurrent orchestration with `asyncio.gather`.
- `tts_arena/audio.py`: extracts `ref_japanese.mp4` to WAV for cloning providers.
- `tts_arena/cli.py`: script entrypoint for long Japanese sentence testing.

## Adapter Pattern

Every engine implements:

```python
class TTSAdapter:
    name: str

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        ...
```

The arena only depends on this interface, so Edge TTS, Google Chirp 3, Azure, ElevenLabs, OpenAI, and GPT-SoVITS can be called in parallel without leaking vendor-specific API details into the orchestration layer.

## Setup

```bash
conda create -n shadowingtts python=3.11 -y
conda activate shadowingtts
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with provider keys and endpoints. Google auth uses Application Default Credentials or `GOOGLE_APPLICATION_CREDENTIALS`.

`ffmpeg` is required to extract audio from `ref_japanese.mp4` for ElevenLabs Instant Voice Cloning and GPT-SoVITS.

## Run

```bash
python -m tts_arena.cli \
  --text-file examples/japanese_long_sentence.txt \
  --output-dir outputs \
  --format mp3
```

Run a subset while setting up credentials:

```bash
python -m tts_arena.cli --models edge
python -m tts_arena.cli --models edge,openai,elevenlabs
```

Run a two-person dialogue for shadowing:

```bash
python -m tts_arena.cli \
  --dialogue-file examples/dialogue_shadowing.json \
  --output-dir outputs \
  --format mp3 \
  --models edge,azure,openai
```

Dialogue output files are named by model, for example `outputs/edge_tts_dialogue.mp3`.
Individual utterance files are kept under `outputs/_dialogue_segments/` for inspection.

Rerun only the models that failed in the previous run:

```bash
python -m tts_arena.cli \
  --text-file examples/japanese_long_sentence.txt \
  --output-dir outputs \
  --format mp3 \
  --rerun-failed
```

The CLI stores the latest run status in `outputs/results.json`.

Outputs are named by model:

- `outputs/edge_tts.mp3`
- `outputs/google_chirp_3.mp3`
- `outputs/azure_tts.mp3`
- `outputs/elevenlabs.mp3`
- `outputs/openai_tts.mp3`
- `outputs/gpt_sovits.mp3`

## VideoSRT Integration

After the bot sends the audio, it automatically submits it to a running [VideoSRT Agent](https://github.com/your-org/JaVideoSrtGenAgent) (watch_dir pattern) and sends the bilingual `.srt` back to the user when ready.

Configure in `.env`:

```env
VIDEOSRT_WATCH_DIR=/path/to/videosrt/watch_input
VIDEOSRT_OUT_DIR=/path/to/videosrt/subtitle_output
VIDEOSRT_TIMEOUT=600
```

Leave `VIDEOSRT_WATCH_DIR` empty to disable. VideoSRT must be running independently (`python master_multiprcs.py` on the GPU host), monitoring `VIDEOSRT_WATCH_DIR`. The bot fires the submission as a background task — audio is sent to the user immediately, the `.srt` arrives a few minutes later.

## Provider Notes

- ElevenLabs default model is `eleven_turbo_v2_5`. Also accepts `eleven_flash_v2_5`.
- ElevenLabs does not clone by default. Set `ELEVENLABS_VOICE_ID` to use a specific existing voice, or leave it empty to use the first voice available in your account.
- To create an Instant Voice Clone from `ref_japanese.mp4`, set `ELEVENLABS_ENABLE_CLONING=true` and leave `ELEVENLABS_VOICE_ID` empty.
- GPT-SoVITS calls a configurable local API and sends `GPT_SOVITS_CKPT_PATH` to `/set_model` before synthesis.
- If GPT-SoVITS runs on another Ubuntu host, set `GPT_SOVITS_REF_AUDIO_PATH` to the reference WAV path on that host. Otherwise the adapter extracts `ref_japanese.mp4` locally and passes that local path.
- GPT-SoVITS API shapes vary by deployment. If your local server exposes different field names, only `tts_arena/adapters/gpt_sovits.py` should need editing.

## Dialogue JSON

`--dialogue-file` accepts JSON with `turns`, optional per-speaker `voices`, and optional `pause_ms`:

```json
{
  "pause_ms": 450,
  "voices": {
    "A": {
      "edge_tts": "ja-JP-NanamiNeural",
      "azure_tts": "ja-JP-KeitaNeural",
      "openai_tts": "alloy",
      "elevenlabs": "VOICE_ID_FOR_A"
    },
    "B": {
      "edge_tts": "ja-JP-KeitaNeural",
      "azure_tts": "ja-JP-NanamiNeural",
      "openai_tts": "onyx",
      "elevenlabs": "VOICE_ID_FOR_B"
    }
  },
  "turns": [
    {"speaker": "A", "text": "すみません、この電車は新宿まで行きますか。"},
    {"speaker": "B", "text": "はい、行きます。ただし、途中で急行に乗り換えたほうが早いですよ。"}
  ]
}
```

Voice keys match normalized adapter names: `edge_tts`, `google_chirp_3`, `azure_tts`, `elevenlabs`, `openai_tts`, `gpt_sovits`.

## Telegram Service

For the first deployable service version, use Telegram polling as the frontend and ElevenLabs as the default TTS provider:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
TELEGRAM_MAX_TEXT_LENGTH=2000
TELEGRAM_DEBUG_REPLY_JSON=false
DEFAULT_TTS_PROVIDER=elevenlabs
SERVICE_OUTPUT_DIR=outputs/service

GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
ENABLE_GEMINI_DIALOGUE_PARSER=true

ELEVENLABS_API_KEY=...
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
ELEVENLABS_ENABLE_CLONING=false
ELEVENLABS_VOICE_ID=VOICE_FOR_SPEAKER_A
ELEVENLABS_VOICE_ID2=VOICE_FOR_SPEAKER_B
```

Start the bot:

```bash
python -m tts_arena.telegram_bot
```

For production, set `TELEGRAM_ALLOWED_USER_IDS`. If it is empty, the bot allows requests and writes a warning to the log, which is only appropriate for local testing.
`TELEGRAM_DEBUG_REPLY_JSON=true` makes the bot send the normalized JSON back to users; keep it false for normal use.

Runtime flow:

1. Telegram receives user text.
2. The bot asks the user to choose a language: Japanese, English, Chinese, or Korean.
3. The bot asks whether the material should be dialogue or monologue.
4. Gemini converts free-form input or `A:/B:` text into structured turns.
5. The dialogue pipeline assigns `ELEVENLABS_VOICE_ID` to speaker A and `ELEVENLABS_VOICE_ID2` to speaker B.
6. ElevenLabs generates each turn.
7. ffmpeg concatenates the turns into one MP3 and the bot sends it back.

If `ENABLE_GEMINI_DIALOGUE_PARSER=false`, the service skips Gemini and uses a simple local parser: lines starting with `A:` or `B:` keep their speaker; other lines alternate A/B.
For monologue mode, all lines are assigned to speaker A.
