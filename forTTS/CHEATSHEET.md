# API 速查表 (Cheat Sheet)

快速参考，无需翻阅完整文档。

---

## 导入

```python
import sys
sys.path.insert(0, "../JaVideoSrtGenAgent")

from master_multiprcs import start_pipeline, enqueue_media_for_subtitle
import json

config = json.load(open("../JaVideoSrtGenAgent/config.json"))
```

---

## 初始化（一次）

```python
start_pipeline(config)
```

---

## 生成双语字幕

```python
srt = enqueue_media_for_subtitle(
    media_path="audio.wav",      # 必需
    config=config,               # 必需
    lang="ja",                   # 可选，默认 config["lang"]
    no_trans=False               # False = 双语，True = 单语
)
```

---

## 常用变体

### 仅日文字幕（跳过翻译）

```python
enqueue_media_for_subtitle("audio.wav", config, no_trans=True)
```

### 英文识别

```python
enqueue_media_for_subtitle("audio.wav", config, lang="en", no_trans=False)
```

### 自定义输出目录

```python
cfg = config.copy()
cfg["out_dir"] = "./my_output"
enqueue_media_for_subtitle("audio.wav", cfg)
```

---

## 输出文件

| 类型 | 文件名 | 路径 |
|------|--------|------|
| 双语 | `{名称}_bi.srt` | `config["out_dir"]` |
| 单语 | `{名称}.srt` | `config["out_dir"]` |

---

## 支持的格式

```
.mp3, .wav, .m4a (音频)
.mp4, .mkv, .avi, .webm, .mov (视频)
```

---

## 等待完成（可选）

```python
import time
from pathlib import Path

srt_path = Path(config["out_dir"]) / "audio_bi.srt"
enqueue_media_for_subtitle("audio.wav", config)

while not srt_path.exists():
    time.sleep(1)
print(f"完成: {srt_path}")
```

或使用提供的 `SubtitleGenerator` 类（见 `subtitle_integration_example.py`）：

```python
from subtitle_integration_example import SubtitleGenerator

gen = SubtitleGenerator("../JaVideoSrtGenAgent")
gen.initialize()

# 同步等待
srt_path = gen.generate_subtitle(
    "audio.wav",
    bilingual=True,
    wait=True,
    timeout=600
)
```

---

## 读取字幕

```python
with open(srt_path, "r", encoding="utf-8") as f:
    print(f.read())
```

---

## 错误处理

```python
try:
    srt = enqueue_media_for_subtitle("audio.wav", config)
except FileNotFoundError:
    print("文件不存在")
except ValueError:
    print("不支持的格式")
```

---

## 配置最小要求

```json
{
    "gemini_api_key": "YOUR_API_KEY",
    "out_dir": "./exports"
}
```

---

## 完整最小示例

```python
#!/usr/bin/env python3
import sys, json
from pathlib import Path

sys.path.insert(0, "../JaVideoSrtGenAgent")
from master_multiprcs import start_pipeline, enqueue_media_for_subtitle

# 1. 配置
config = json.load(open("../JaVideoSrtGenAgent/config.json"))

# 2. 启动
start_pipeline(config)

# 3. 生成字幕
srt = enqueue_media_for_subtitle("audio.wav", config)

# 4. 读取
with open(srt) as f:
    print(f.read())
```

---

## 配置继承

```python
# 保留 JaVideoSrtGenAgent 的配置
base_config = json.load(open("../JaVideoSrtGenAgent/config.json"))

# 添加或覆盖
base_config["out_dir"] = "./tts_output"
base_config["lang"] = "en"

enqueue_media_for_subtitle("audio.wav", base_config)
```

---

## 多个文件

```python
audio_files = ["audio1.wav", "audio2.wav", "audio3.wav"]

for audio in audio_files:
    enqueue_media_for_subtitle(audio, config)
    print(f"已投递: {audio}")

# 后台依次处理
```

---

## 日志配置

字幕系统已配置日志，会输出到终端。查看进度：

```bash
# macOS/Linux 查看终端输出
# 或导出日志
python -c "
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='subtitle.log'
)
"
```

---

## 性能提示

- **大文件** (>2GB) → 可能失败，建议分割
- **快速模式** → 用 `no_trans=True` 跳过翻译，快 60%
- **多任务** → 最多 3-5 个并发任务（GPU 限制）
- **API 频率** → Gemini 自动加延迟，无需手动处理

---

## 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `FileNotFoundError` | 文件不存在 | 检查路径 |
| `ValueError: 不支持的格式` | 扩展名错误 | 用支持的格式 |
| `ImportError: No module named 'master_multiprcs'` | 路径错误 | 检查 `sys.path.insert` |
| Gemini 翻译失败 | API 密钥无效 | 检查 `config.json` |
| 字幕缺失 | 流水线未启动 | 调用 `start_pipeline` |

---

**更新时间**：2026-05-17
