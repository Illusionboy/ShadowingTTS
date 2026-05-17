# API 速查表 - watch_dir 方案

最常用的代码片段速查，无需翻阅完整文档。

---

## 最简单的投递方式

```python
import shutil
import json

config = json.load(open("../JaVideoSrtGenAgent/config.json"))
audio = "output.wav"

# 一行代码投递到 watch_dir
shutil.copy2(audio, config["watch_dir"])

# 完成！VideoSRT 会自动转写和翻译
```

---

## 带等待的完整版

```python
import shutil, time, json
from pathlib import Path

config = json.load(open("../JaVideoSrtGenAgent/config.json"))
watch_dir = Path(config["watch_dir"])
out_dir = Path(config["out_dir"])

# 1. 投递
audio = "output.wav"
shutil.copy2(audio, watch_dir / audio)

# 2. 等待字幕（最多 10 分钟）
expected_srt = out_dir / f"{Path(audio).stem}_bi.srt"
for i in range(600):
    if expected_srt.exists():
        print(f"✅ 字幕完成！{expected_srt}")
        break
    time.sleep(1)
```

---

## 生产推荐版本

```python
import shutil, time, json
from pathlib import Path

def post_audio_for_subtitle(audio_path, config_path, wait=False, timeout=600):
    """投递音频，返回字幕路径"""
    cfg = json.load(open(config_path))
    watch = Path(cfg["watch_dir"])
    out = Path(cfg["out_dir"])
    
    # 投递
    watch.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio_path, watch / Path(audio_path).name)
    expected = out / f"{Path(audio_path).stem}_bi.srt"
    
    if wait:
        # 等待完成
        for _ in range(timeout):
            if expected.exists():
                return expected
            time.sleep(1)
        return None
    
    return expected

# 使用
srt = post_audio_for_subtitle(
    "output.wav",
    "../JaVideoSrtGenAgent/config.json",
    wait=True,
    timeout=600
)

if srt:
    with open(srt, encoding="utf-8") as f:
        print(f.read())
```

---

## VideoSRT 服务启动（一次）

```bash
cd /path/to/JaVideoSrtGenAgent
python master_multiprcs.py &

# 或使用 systemd
sudo systemctl start dtv_bot
```

---

## 配置关键项

```json
{
  "watch_dir": "/mnt/nas/watch_input",
  "out_dir": "/mnt/nas/subtitle_output",
  "gemini_api_key": "YOUR_KEY",
  "lang": "ja"
}
```

---

## 支持的格式

```
音频: .mp3, .wav, .m4a
视频: .mp4, .mkv, .avi, .webm, .mov
```

---

## 输出文件命名

| 输入 | 双语输出 | 单语输出 |
|------|---------|---------|
| `audio.wav` | `audio_bi.srt` | `audio.srt` |
| `video.mp4` | `video_bi.srt` | `video.srt` |

位置：`config["out_dir"]`

---

## 读取字幕

```python
with open(srt_path, "r", encoding="utf-8") as f:
    subtitle_text = f.read()
```

---

## 检查处理状态

```bash
# 监控 watch_dir（应该是空或有正在处理的文件）
ls -lh /mnt/nas/watch_input/

# 监控 out_dir（应该有输出的字幕）
ls -lh /mnt/nas/subtitle_output/

# 查看日志
tail -f nohup.out | grep -E "新文件|转写|翻译"
```

---

## 常见问题速解

| 问题 | 原因 | 修复 |
|------|------|------|
| 字幕不生成 | watch_dir 路径错 | 检查 config.json |
| 权限拒绝 | NAS 权限不足 | `chmod 755 /mnt/nas/*` |
| 服务卡顿 | watch_dir 和 out_dir 重叠 | 分离目录（见 WATCH_DIR_CONFIG_FIX.md） |
| Gemini 失败 | API 密钥无效 | 更新 config.json |
| 文件未检测 | VideoSRT 未运行 | `ps aux \| grep master_multiprcs` |

---

## 完整工作流

```
TTS 生成 audio.wav
  ↓
shutil.copy2(audio.wav, watch_dir/)
  ↓
VideoSRT 监控到文件
  ↓
Whisper 转写 → audio.srt
  ↓
Gemini 翻译 → audio_bi.srt
  ↓
字幕输出到 out_dir
  ↓
TTS 从 out_dir 读取字幕
```

---

**更新时间**：2026-05-18
