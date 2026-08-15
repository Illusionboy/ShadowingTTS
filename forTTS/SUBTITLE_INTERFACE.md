# TTS 项目 - 双语字幕生成接口文档

本文档描述了如何在 TTS Agent 项目中集成**日文音视频→双语字幕**的自动转写和翻译功能。

---

## 🏗️ 推荐架构

```text
┌─────────────────────┐
│   TTS Agent         │
│  (独立进程/服务)    │
│  - 对话处理         │
│  - 生成 mp3 音频    │
│  - 写入 watch_dir   │
└────────────┬────────┘
             │
             ↓ (文件系统)
        ┌────────────┐
        │ watch_dir  │ (共享存储/NAS)
        └────────────┘
             ↑
             │ (热目录监控)
┌────────────┴────────────────┐
│   VideoSRT Agent            │
│  (独立后台服务)             │
│  - 监控 watch_dir           │
│  - Whisper 转写 (GPU)       │
│  - Gemini 翻译              │
│  - 输出双语字幕 to out_dir  │
└─────────────────────────────┘
```

**推荐方案**：watch_dir 热目录解耦（两个独立服务，完全解耦）

---

## 快速开始 - watch_dir 方案

### 1. 配置 VideoSRT 侧

编辑 `config.json`：

```json
{
  "watch_dir": "/mnt/nas/watch_input",      // 🔴 TTS 投递音频的地方
  "out_dir": "/mnt/nas/subtitle_output",    // 🟢 字幕输出的地方
  "input_dir": "./input_srt",
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "lang": "ja",
  "no_trans": false
}
```

### 2. 启动 VideoSRT 服务

```bash
# Linux 服务器（GPU 环境）
python master_multiprcs.py

# 或使用 systemd 后台运行
# 详见 CLAUDE.md 的 systemctl 命令
```

### 3. TTS 侧投递（最简单）

TTS Agent 生成 mp3 后，直接复制到 watch_dir：

```python
import shutil
import json
from pathlib import Path

# 读取配置
config = json.load(open("../JaVideoSrtGenAgent/config.json"))
watch_dir = Path(config["watch_dir"])
out_dir = Path(config["out_dir"])

# 确保目录存在
watch_dir.mkdir(parents=True, exist_ok=True)
out_dir.mkdir(parents=True, exist_ok=True)

# TTS 生成音频
generated_audio = "output.wav"  # 你的 TTS 模块生成的路径

# 投递到字幕服务
shutil.copy2(generated_audio, watch_dir / generated_audio)

print(f"✅ 已投递: {watch_dir / generated_audio}")
print(f"字幕将输出到: {out_dir}")

# VideoSRT Agent 会自动检测、转写、翻译、输出字幕
```

### 4. TTS 侧读取字幕（可选）

如果需要等待和读取字幕：

```python
import time
from pathlib import Path

def wait_for_subtitle(audio_file, config, timeout=600, bilingual=True):
    """等待字幕生成完成"""
    out_dir = Path(config["out_dir"])
    stem = Path(audio_file).stem
    srt_name = f"{stem}_bi.srt" if bilingual else f"{stem}.srt"
    srt_path = out_dir / srt_name
    
    for _ in range(timeout):
        if srt_path.exists():
            return srt_path
        time.sleep(1)
    
    return None

# 使用
config = json.load(open("../JaVideoSrtGenAgent/config.json"))
audio_file = "output.wav"

# 投递
shutil.copy2(audio_file, Path(config["watch_dir"]) / audio_file)

# 等待完成
srt_path = wait_for_subtitle(audio_file, config, timeout=600, bilingual=True)

if srt_path:
    print(f"✅ 字幕已完成: {srt_path}")
    with open(srt_path, encoding="utf-8") as f:
        print(f.read()[:500])
```

---

## 架构对比

### 方案 A：watch_dir（⭐ 推荐）

**原理**：VideoSRT Agent 作为独立后台服务，监控热目录

| 特性 | 优点 | 缺点 |
| ------ | ------ | ------ |
| **解耦度** | 完全独立，可在不同机器 | 需要共享存储 |
| **部署** | 简单（1 行复制命令） | 需要配置 NAS 或网络共享 |
| **可维护性** | 高（更新互不影响） | 文件系统延迟（秒级） |
| **扩展性** | 可轻松添加第三方服务 | - |
| **错误隔离** | 好（一个服务崩溃不影响另一个） | - |

**适用场景**：

- ✅ VideoSRT 是 Linux GPU 服务器上的独立服务
- ✅ TTS 可能在不同机器
- ✅ 需要稳定的长期部署
- ✅ 其他项目也需要字幕功能

### 方案 B：进程内 API 调用

**原理**：TTS 直接导入 VideoSRT 代码，两者在同一进程

```python
from master_multiprcs import start_pipeline, enqueue_media_for_subtitle

start_pipeline(config)  # 启动后台线程
srt = enqueue_media_for_subtitle("audio.wav", config)
```

| 特性 | 优点 | 缺点 |
| ------ | ------ | ------ |
| **解耦度** | - | 紧耦合，必须同一进程 |
| **部署** | 零延迟（毫秒级） | 复杂（要处理依赖冲突） |
| **可维护性** | - | 低（更新需要重启整个服务） |
| **扩展性** | 可同步等待结果 | 很难添加其他服务 |

**适用场景**：

- ❌ **不推荐**（对大多数场景而言）
- 仅当 TTS 和 VideoSRT 必须紧耦合时才考虑

---

## watch_dir 详细说明

### 语言选择：文件名 lang 后缀约定

VideoSRT Agent 通过 **文件名中的语言后缀** 识别每个文件应使用的转写语言，无需修改 config.json 或额外配置。

#### 命名规则

```text
{原始名}.{lang代码}.{扩展名}
```

| 示例文件名 | 识别语言 | 输出文件名 |
| ----------- | --------- | ----------- |
| `speech.ja.mp4` | 日文 | `speech.ja_bi.srt` |
| `lecture.en.wav` | 英文 | `lecture.en_bi.srt` |
| `podcast.zh.mp3` | 中文 | `podcast.zh_bi.srt` |
| `audio.mp4` | config 默认（ja） | `audio_bi.srt` |

**关键特性：**

- lang 后缀**保留在输出文件名中**：`audio.en.mp3` → `audio.en_bi.srt`，ShadowReader 可据此识别语言
- 若 stem 最后一段不是合法 Whisper 语言代码，回退到 config.json 的 `lang` 设置，不影响普通文件
- 支持所有 Whisper ISO 639-1 代码：`ja` `en` `zh` `ko` `fr` `de` `es` `pt` `ru` `ar` 等

#### TTS Agent 投递示例（自动添加后缀）

```python
import shutil
from pathlib import Path

def submit_with_lang(audio_path: str, lang: str, watch_dir: str) -> Path:
    """将音频以 lang 后缀格式投递到 watch_dir。"""
    src = Path(audio_path)
    # output.wav → output.ja.wav
    dest_name = f"{src.stem}.{lang}{src.suffix}"
    dest = Path(watch_dir) / dest_name
    shutil.copy2(src, dest)
    return dest

# 使用
submit_with_lang("output.wav", lang="ja", watch_dir="/mnt/nas/watch_input")
submit_with_lang("lecture.mp3", lang="en", watch_dir="/mnt/nas/watch_input")
```

---

### 工作流程

```text
1️⃣  TTS Agent 生成 audio.wav
        ↓
2️⃣  TTS 重命名为 audio.ja.wav 并复制到 watch_dir
        ↓
3️⃣  VideoSRT Agent 监控检测 (热目录)，解析 lang=ja，文件名保留 .ja
        ↓
4️⃣  whisper_worker 转写 → audio.ja.srt (日文)
        ↓
5️⃣  translation_worker 翻译 → audio.ja_bi.srt (日+中)
        ↓
6️⃣  字幕输出到 out_dir
        ↓
7️⃣  TTS Agent / ShadowReader 从 out_dir 读取字幕
```

### TTS 投递代码示例

**最小化投递**：

```python
import shutil
import json
from pathlib import Path

config = json.load(open("../JaVideoSrtGenAgent/config.json"))
audio_file = Path("output.wav")
lang = "ja"  # TTS 侧已知的语言

# 以 lang 后缀命名后投递
dest_name = f"{audio_file.stem}.{lang}{audio_file.suffix}"  # output.ja.wav
shutil.copy2(audio_file, Path(config["watch_dir"]) / dest_name)
```

**生产环境推荐**：

```python
import shutil
import time
import logging
from pathlib import Path
import json

logging.basicConfig(level=logging.INFO)

def submit_audio_to_subtitle_service(
    audio_path: str,
    lang: str = "ja",
    config_path: str = "../JaVideoSrtGenAgent/config.json",
    wait: bool = False,
    timeout: int = 600
):
    """
    投递音频到字幕服务（自动附加 lang 后缀）

    Args:
        audio_path: 音频文件路径
        lang: Whisper 识别语言代码，如 "ja" "en" "zh" "ko"
        config_path: JaVideoSrtGenAgent config.json 路径
        wait: 是否等待字幕完成
        timeout: 最长等待秒数

    Returns:
        (投递路径, 预期字幕路径, 实际字幕路径 or None)
    """
    config = json.load(open(config_path))
    watch_dir = Path(config["watch_dir"])
    out_dir = Path(config["out_dir"])

    watch_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 附加 lang 后缀：output.wav → output.ja.wav
    audio_file = Path(audio_path)
    dest_name = f"{audio_file.stem}.{lang}{audio_file.suffix}"
    watched_path = watch_dir / dest_name
    shutil.copy2(audio_path, watched_path)

    logging.info(f"✅ 已投递: {watched_path} (lang={lang})")

    # 输出 SRT 保留 lang 标签：output.ja.wav → output.ja_bi.srt
    expected_srt = out_dir / f"{audio_file.stem}.{lang}_bi.srt"
    logging.info(f"预期字幕: {expected_srt}")

    if not wait:
        return str(watched_path), str(expected_srt), None

    logging.info(f"⏳ 等待字幕生成（最多 {timeout} 秒）...")
    for i in range(timeout):
        if expected_srt.exists():
            logging.info("✅ 字幕已完成！")
            return str(watched_path), str(expected_srt), str(expected_srt)

        if i % 30 == 0:
            logging.info(f"   进度: {i}/{timeout} 秒...")

        time.sleep(1)

    logging.warning(f"⚠️ 超时：字幕未在规定时间内生成")
    return str(watched_path), str(expected_srt), None

# 使用示例
if __name__ == "__main__":
    submitted, expected, actual = submit_audio_to_subtitle_service(
        audio_path="output.wav",
        lang="ja",
        wait=True,
        timeout=600
    )

    if actual:
        print(f"字幕地址: {actual}")
        with open(actual, encoding="utf-8") as f:
            print(f.read())
```

### 配置说明

#### VideoSRT 端配置 (config.json)

```json
{
  "watch_dir": "/mnt/nas/subtitle_watch",
  "out_dir": "/mnt/nas/subtitle_output",
  "input_dir": "./input_srt",
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "lang": "ja",
  "no_trans": false
}
```

| 字段 | 必需 | 说明 |
| ------ | ------ | ------ |
| `watch_dir` | ✅ | 热目录路径（TTS 投递音频的地方，必须共享存储） |
| `out_dir` | ✅ | 字幕输出目录（TTS 可从这里读取字幕） |
| `gemini_api_key` | ✅ | Google Gemini API 密钥 |
| `lang` | 否 | 识别语言，默认 `"ja"`（日文） |
| `input_dir` | 否 | 临时字幕目录，默认 `"./input_srt"` |
| `no_trans` | 否 | 全局：是否跳过翻译，默认 `false` |

### 支持的媒体格式

```text
音频: .mp3, .wav, .m4a
视频: .mp4, .mkv, .avi, .webm, .mov
```

### 输出文件

两条路径均在输出文件名中保留 lang 标签，ShadowReader 可统一用 `detect_lang_from_srt()` 识别：

| 来源 | 输入示例 | 双语输出示例 |
| ------ | --------- | --------- |
| watch_dir（TTS Agent 投递） | `audio.ja.wav` | `audio.ja_bi.srt` |
| Telegram URL 下载 | 用户选 ja → `title.mp4` | `title.ja_bi.srt` |
| 无 lang 后缀（回退默认） | `audio.wav` | `audio_bi.srt` |

**所有文件输出到** `config["out_dir"]`

### 输出格式

**单语 SRT**：

```srt
1
00:00:00,000 --> 00:00:03,500
これはテキストです。

2
00:00:03,500 --> 00:00:07,000
別の例文です。
```

**双语 SRT**：

```srt
1
00:00:00,000 --> 00:00:03,500
これはテキストです。
这是文本。

2
00:00:03,500 --> 00:00:07,000
別の例文です。
另一个例子。
```

---

## 备选方案：进程内 API 调用（仅限特殊情况）

如果你的 TTS 和 VideoSRT 必须在同一进程内，可以使用：

```python
import sys
import json
from pathlib import Path

# 添加 JaVideoSrtGenAgent 路径
ja_agent_dir = Path("../JaVideoSrtGenAgent").resolve()
if str(ja_agent_dir) not in sys.path:
    sys.path.insert(0, str(ja_agent_dir))

from master_multiprcs import start_pipeline, enqueue_media_for_subtitle

# 初始化（仅一次）
config = json.load(open(ja_agent_dir / "config.json"))
start_pipeline(config)

# 生成字幕
srt_path = enqueue_media_for_subtitle(
    media_path="audio.wav",
    config=config,
    lang="ja",
    no_trans=False  # False = 双语, True = 单语
)

print(f"字幕: {srt_path}")
```

**警告**：此方案仅适用于 TTS 和 VideoSRT 紧耦合的情况，**不推荐**用于生产环境。

---

## 常见问题

### Q1：我的 TTS 在 Windows，能用吗？

**A**：watch_dir 方案可以。只要 TTS 能写到共享存储（NAS 或网络盘），VideoSRT（Linux GPU 服务器）就能监控。这是最优方案。

### Q2：watch_dir 和 NAS 在不同机器，会有延迟吗？

**A**：有，通常秒级（取决于网络 I/O）。总时间 = 网络延迟 + Whisper 转写 + 翻译。建议使用本地 SSD 的 NAS。

### Q3：字幕生成需要多长时间？

**A**：

- Whisper 转写：约 1-2 倍音频时长（A100 GPU）
- Gemini 翻译：约 0.5-1 倍时长
- **总耗时**：3-5 倍音频时长

例：10 分钟音频 → 30-50 分钟完成

### Q4：支持其他语言吗？

**A**：支持。修改 `config.json` 的 `lang` 或通过外部机制覆盖。翻译输出始终是**简体中文**。

```json
{
  "lang": "en"  // 英文
}
```

### Q5：Gemini API 失效会怎样？

**A**：

- 转写完成 (`.srt` 生成)
- 翻译失败，无 `_bi.srt`
- 错误记录到日志

### Q6：watch_dir 文件不会被 VideoSRT 删除吗？

**A**：VideoSRT 会将文件移动到 `input_dir/media_imports/`，watch_dir 会空闲。可定期清理，或让 TTS 定期覆盖。

### Q7：如何知道字幕何时完成？

**A**：轮询 `out_dir`，看 `{filename}_bi.srt` 是否存在。提供的示例代码已包含此逻辑。

### Q8：能否跳过翻译只要日文字幕？

**A**：可以。修改 `config.json`：

```json
{
  "no_trans": true
}
```

或通过外部机制通知 VideoSRT。

---

## 性能优化

### 1. 共享存储选择

- **首选**：本地 SSD + NFS（局域网 NAS）
- **次选**：SMB/CIFS (Windows 共享)
- **最后**：云存储 (S3, OSS 等) - 延迟较高

### 2. watch_dir 目录维护

```bash
# 定期清理已处理的文件（保留 3 天）
find /mnt/nas/watch_dir -type f -mtime +3 -delete
```

### 3. GPU 显存

Whisper large-v3 需约 10GB VRAM。确保：

- 不运行其他 CUDA 程序
- 显存充足（nvidia-smi 查看）

### 4. 并发限制

单个 VideoSRT 服务最多同时处理 3-5 个文件（GPU 限制）。如需更多，考虑部署多个 GPU 或使用队列调度。

---

---

## ShadowReader 语言识别规范

ShadowReader（影子跟读 App）消费 `out_dir` 中的双语 SRT 文件。根据文件来源不同，文件名携带 lang 标签的方式不同，需要统一的识别逻辑。

### 命名规则总结

| 文件名示例 | 来源 | 源语言获取方式 |
| ---------- | ---- | -------------- |
| `speech.ja_bi.srt` | Telegram URL 下载（用户选 ja） | 文件名解析 |
| `lecture.en_bi.srt` | Telegram URL 下载（用户选 en） | 文件名解析 |
| `audio_bi.srt` | watch_dir TTS 投递（lang 已剥离） | 无（回退到默认或不分类） |

### ShadowReader 实现：从文件名提取语言

```python
from pathlib import Path

# 与 VideoSRT Agent 保持一致的合法语言代码集合
WHISPER_LANG_CODES = {
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh",
}


def detect_lang_from_srt(srt_path: str) -> str | None:
    """从双语 SRT 文件名提取源语言代码。

    支持两种格式：
      speech.ja_bi.srt  → "ja"   (Telegram 下载路径)
      audio_bi.srt      → None   (watch_dir/TTS 路径，无 lang 标签)
    """
    stem = Path(srt_path).stem          # "speech.ja_bi"  或  "audio_bi"
    base = stem.removesuffix("_bi")     # "speech.ja"     或  "audio"
    parts = base.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in WHISPER_LANG_CODES:
        return parts[1].lower()
    return None


def get_real_title(srt_path: str) -> str:
    """提取去掉 lang 标签和 _bi 后缀的干净标题。

    speech.ja_bi.srt → "speech"
    audio_bi.srt     → "audio"
    """
    stem = Path(srt_path).stem          # "speech.ja_bi"
    base = stem.removesuffix("_bi")     # "speech.ja"
    parts = base.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in WHISPER_LANG_CODES:
        return parts[0]                 # "speech"
    return base                         # "audio"
```

### 使用示例

```python
from pathlib import Path

out_dir = Path("/mnt/nas/subtitle_output")

for srt_file in out_dir.glob("*_bi.srt"):
    lang = detect_lang_from_srt(str(srt_file))
    title = get_real_title(str(srt_file))

    if lang == "ja":
        category = "日语跟读"
    elif lang == "en":
        category = "英语跟读"
    elif lang is None:
        category = "未分类"   # watch_dir/TTS 来源
    else:
        category = f"{lang} 跟读"

    print(f"[{category}] {title} → {srt_file.name}")
```

**输出示例：**

```text
[日语跟读] speech → speech.ja_bi.srt
[英语跟读] lecture → lecture.en_bi.srt
[未分类] audio → audio_bi.srt
```

### 与媒体文件关联

Telegram 下载的视频文件同步带 lang 后缀，ShadowReader 可通过 stem 匹配：

```python
def find_media_for_srt(srt_path: str, out_dir: str) -> Path | None:
    """找到与 SRT 对应的媒体文件。"""
    title = get_real_title(srt_path)
    lang = detect_lang_from_srt(srt_path)
    media_exts = [".mp4", ".mkv", ".avi", ".webm", ".mov", ".mp3", ".wav", ".m4a"]

    for ext in media_exts:
        # speech.ja.mp4 / speech.ja.mp3 等
        candidate = Path(out_dir) / f"{title}.{lang}{ext}" if lang else Path(out_dir) / f"{title}{ext}"
        if candidate.exists():
            return candidate
    return None
```

---

## 许可与支持

本接口由 JaVideoSrtGenAgent 项目提供。

- [AGENTS.md](../AGENTS.md) - 项目架构详解
- [CLAUDE.md](../CLAUDE.md) - 开发者指南
- [README.md](../README.md) - 项目主文档

---

**最后更新**：2026-05-17
