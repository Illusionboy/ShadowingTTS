# Ubuntu Server Deployment Notes

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

## 2. Python environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. Minimal `.env` for Telegram + ElevenLabs

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_MAX_TEXT_LENGTH=2000
TELEGRAM_DEBUG_REPLY_JSON=false
DEFAULT_TTS_PROVIDER=elevenlabs
TTS_OUTPUT_FORMAT=mp3
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

## 4. Run polling bot

```bash
python -m tts_arena.telegram_bot
```

For production, run the command under `systemd`, `supervisor`, or Docker.
