# 多模型 TTS 评测竞技场

本项目通过统一的异步适配器接口，对比六家提供商的语音合成效果，主要用于英语和日语影子跟读学习素材的生成。

## 架构

- `tts_arena/base.py`：公共契约 `TTSAdapter`、`TTSRequest`、`TTSResult`。
- `tts_arena/adapters/*`：每家 TTS 提供商对应一个适配器。
- `tts_arena/arena.py`：通过 `asyncio.gather` 并发调度所有适配器。
- `tts_arena/audio.py`：从 `ref_japanese.mp4` 提取 WAV，供声音克隆使用。
- `tts_arena/cli.py`：命令行入口，用于长句测试。
- `tts_arena/subtitle.py`：VideoSRT 集成，异步投递音频并等待双语字幕。

## 适配器模式

每个引擎都实现以下接口：

```python
class TTSAdapter:
    name: str

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        ...
```

竞技场只依赖这一接口，因此 Edge TTS、Google Chirp 3、Azure、ElevenLabs、OpenAI 和 GPT-SoVITS 可以并行调用，无需将各厂商 API 细节暴露给调度层。

## 安装

```bash
conda create -n shadowingtts python=3.11 -y
conda activate shadowingtts
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中填写各提供商的密钥和端点。Google 认证使用 Application Default Credentials 或 `GOOGLE_APPLICATION_CREDENTIALS` 环境变量。

ElevenLabs 声音克隆和 GPT-SoVITS 需要安装 `ffmpeg`。

## 运行

**全量测试（所有模型）：**

```bash
python -m tts_arena.cli \
  --text-file examples/japanese_long_sentence.txt \
  --output-dir outputs \
  --format mp3
```

**仅测试部分模型（配置密钥期间）：**

```bash
python -m tts_arena.cli --models edge
python -m tts_arena.cli --models edge,openai,elevenlabs
```

**对话模式（影子跟读）：**

```bash
python -m tts_arena.cli \
  --dialogue-file examples/dialogue_shadowing.json \
  --output-dir outputs \
  --format mp3 \
  --models edge,azure,openai
```

对话输出按模型命名，例如 `outputs/edge_tts_dialogue.mp3`。各句段文件保存在 `outputs/_dialogue_segments/` 供单独检查。

**仅重跑上次失败的模型：**

```bash
python -m tts_arena.cli \
  --text-file examples/japanese_long_sentence.txt \
  --output-dir outputs \
  --format mp3 \
  --rerun-failed
```

运行状态记录在 `outputs/results.json`。

各模型输出文件：

- `outputs/edge_tts.mp3`
- `outputs/google_chirp_3.mp3`
- `outputs/azure_tts.mp3`
- `outputs/elevenlabs.mp3`
- `outputs/openai_tts.mp3`
- `outputs/gpt_sovits.mp3`

## VideoSRT 集成

Bot 发送音频后，自动将音频投递到独立运行的 VideoSRT Agent（watch_dir 模式），双语字幕生成完成后发回给用户。

在 `.env` 中配置：

```env
VIDEOSRT_WATCH_DIR=/path/to/videosrt/watch_input
VIDEOSRT_OUT_DIR=/path/to/videosrt/subtitle_output
VIDEOSRT_TIMEOUT=600
```

`VIDEOSRT_WATCH_DIR` 留空则禁用此功能。VideoSRT 需在 GPU 主机上独立运行（`python master_multiprcs.py`），监控 `VIDEOSRT_WATCH_DIR` 目录。Bot 以后台任务方式投递，音频立即发给用户，字幕稍后单独发送。

## 提供商说明

- **ElevenLabs**：默认模型为 `eleven_turbo_v2_5`，也支持 `eleven_flash_v2_5`。默认不克隆声音，设置 `ELEVENLABS_VOICE_ID` 可指定已有声音，留空则使用账号内第一个可用声音。设置 `ELEVENLABS_ENABLE_CLONING=true` 并清空 `ELEVENLABS_VOICE_ID` 可从 `ref_japanese.mp4` 创建即时声音克隆。
- **Google Chirp 3**：使用 Application Default Credentials 或 `GOOGLE_APPLICATION_CREDENTIALS` 指向服务账号 JSON 文件。
- **GPT-SoVITS**：调用本地 HTTP API，合成前先将 `GPT_SOVITS_CKPT_PATH` 发送至 `/set_model`。若运行在远程 Ubuntu 主机上，设置 `GPT_SOVITS_REF_AUDIO_PATH` 为该主机上的参考 WAV 路径；否则适配器会在本地提取 `ref_japanese.mp4`。不同部署的 API 字段名可能不同，仅需修改 `tts_arena/adapters/gpt_sovits.py`。
- **Azure**：需要 `AZURE_SPEECH_KEY` 和 `AZURE_SPEECH_REGION`（默认 `japaneast`）。

## 对话 JSON 格式

`--dialogue-file` 接受包含 `turns`、可选的每说话人 `voices` 和可选 `pause_ms` 的 JSON：

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

声音键名与适配器规范化名称一致：`edge_tts`、`google_chirp_3`、`azure_tts`、`elevenlabs`、`openai_tts`、`gpt_sovits`。

## Telegram Bot 服务

使用 Telegram 轮询作为前端，ElevenLabs 作为默认 TTS 提供商：

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
ELEVENLABS_MODEL_ID=eleven_turbo_v2_5
ELEVENLABS_ENABLE_CLONING=false
ELEVENLABS_VOICE_ID=VOICE_FOR_SPEAKER_A
ELEVENLABS_VOICE_ID2=VOICE_FOR_SPEAKER_B
```

启动 Bot：

```bash
python -m tts_arena.telegram_bot
```

生产环境务必设置 `TELEGRAM_ALLOWED_USER_IDS`，留空时 Bot 会放行所有请求并输出警告日志（仅适合本地测试）。`TELEGRAM_DEBUG_REPLY_JSON=true` 会将规范化后的 JSON 发回给用户，正常使用时保持 `false`。

**运行时流程：**

1. 用户发送文本到 Telegram。
2. Bot 询问语言：日语、英语、中文或韩语。
3. Bot 询问形式：对话或独白。
4. Gemini 将自由格式输入或 `A:/B:` 文本规范化为结构化语句，并确保输出仅含目标语言（去除中文注释和解释）。
5. 对话流水线将 `ELEVENLABS_VOICE_ID` 分配给说话人 A，`ELEVENLABS_VOICE_ID2` 分配给说话人 B。
6. ElevenLabs 逐句合成音频。
7. ffmpeg 将各句拼接为一个 MP3 并发回用户。
8. 若配置了 VideoSRT，后台自动投递音频并在字幕生成后发送双语 `.srt` 文件。

`ENABLE_GEMINI_DIALOGUE_PARSER=false` 时跳过 Gemini，使用本地简易解析器：`A:` / `B:` 开头的行保留说话人标记，其余行按 A/B 交替分配。独白模式下所有行归属说话人 A。

## Ubuntu 部署

详见 [scripts/ubuntu_setup.md](scripts/ubuntu_setup.md)。
