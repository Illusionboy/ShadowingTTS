# TTS 项目快速入门 - watch_dir 方案

快速指南帮助 TTS 项目通过 watch_dir 接入字幕服务。

---

## ⚡ 3 步快速接入

### 步骤 1：配置 VideoSRT Agent（一次）

在 VideoSRT 服务器上，编辑 `config.json`：

```json
{
  "watch_dir": "/mnt/nas/watch",           // ← 关键：TTS 写到这里
  "out_dir": "/mnt/nas/subtitle_out",      // ← 关键：字幕输出到这里
  "gemini_api_key": "YOUR_KEY",
  "lang": "ja"
}
```

启动服务：

```bash
cd /path/to/JaVideoSrtGenAgent
python master_multiprcs.py

# 或后台运行
nohup python master_multiprcs.py > subtitle_service.log 2>&1 &
```

完成！VideoSRT 现在监控 watch_dir。

### 步骤 2：TTS 项目投递代码（一次集成）

在 TTS 项目中，添加投递函数：

```python
# subtitle_helper.py
import shutil
import json
import time
from pathlib import Path

def post_audio_to_subtitle_service(
    audio_path: str,
    subtitle_config_path: str,
    wait_for_completion: bool = False
):
    """投递音频到字幕服务"""
    
    # 读取配置
    config = json.load(open(subtitle_config_path))
    watch_dir = Path(config["watch_dir"])
    out_dir = Path(config["out_dir"])
    
    # 确保目录存在
    watch_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 投递
    audio_file = Path(audio_path).name
    watched_path = watch_dir / audio_file
    shutil.copy2(audio_path, watched_path)
    
    print(f"✅ 已投递: {watched_path}")
    print(f"字幕输出目录: {out_dir}")
    
    # 预期字幕文件
    stem = Path(audio_path).stem
    expected_srt = out_dir / f"{stem}_bi.srt"
    
    if wait_for_completion:
        # 等待字幕完成（最多 10 分钟）
        for i in range(600):
            if expected_srt.exists():
                print(f"✅ 字幕已完成: {expected_srt}")
                return str(expected_srt)
            time.sleep(1)
        
        print(f"⚠️ 超时，字幕未生成")
        return None
    
    return str(expected_srt)
```

### 步骤 3：在 TTS 流程中调用

TTS 生成音频后调用：

```python
from subtitle_helper import post_audio_to_subtitle_service

# 你的 TTS 逻辑
audio_output = "output.wav"  # TTS 生成的音频

# 投递到字幕服务
subtitle_path = post_audio_to_subtitle_service(
    audio_path=audio_output,
    subtitle_config_path="../JaVideoSrtGenAgent/config.json",
    wait_for_completion=False  # 异步：投递后立即返回
)

print(f"字幕将输出到: {subtitle_path}")

# 如果需要等待
# subtitle_path = post_audio_to_subtitle_service(
#     audio_path=audio_output,
#     wait_for_completion=True
# )
```

完成！就这么简单。

---

## 📋 清单

- [x] VideoSRT Agent 在 Linux GPU 服务器上运行
- [x] 配置了 watch_dir（共享存储路径）
- [x] 配置了 out_dir（字幕输出路径）
- [x] Gemini API 密钥有效
- [x] TTS 项目可访问 watch_dir 和 out_dir
- [x] TTS 项目复制了 `subtitle_helper.py`

---

## 🎯 工作原理

```
TTS Project
  │
  ├─ 生成 audio.wav
  │
  └─ 复制到 watch_dir ──→ /mnt/nas/watch/audio.wav
                            │
                            ↓
                        VideoSRT Agent
                        (后台监控)
                            │
                            ├─ Whisper 转写
                            │
                            └─ Gemini 翻译
                                  │
                                  ↓
                        /mnt/nas/subtitle_out/audio_bi.srt ←── TTS 读取
```

---

## 场景示例

### 场景 1：投递后立即返回（异步）

TTS 生成音频后立即继续，不等待字幕：

```python
subtitle_path = post_audio_to_subtitle_service(
    audio_path="output.wav",
    subtitle_config_path="../JaVideoSrtGenAgent/config.json",
    wait_for_completion=False  # ← 异步
)

print(f"音频已投递，字幕预期输出: {subtitle_path}")

# TTS 继续处理其他任务...
# 稍后需要时再从 out_dir 读取字幕
```

### 场景 2：等待完成后读取（同步）

需要拿到字幕才能继续：

```python
subtitle_path = post_audio_to_subtitle_service(
    audio_path="output.wav",
    subtitle_config_path="../JaVideoSrtGenAgent/config.json",
    wait_for_completion=True  # ← 同步等待
)

if subtitle_path:
    with open(subtitle_path, encoding="utf-8") as f:
        subtitles = f.read()
        print(f"✅ 已获得字幕")
else:
    print(f"❌ 字幕生成失败")
```

### 场景 3：多个音频批量投递

```python
audio_files = ["output1.wav", "output2.wav", "output3.wav"]

for audio in audio_files:
    # 异步投递，不等待
    post_audio_to_subtitle_service(
        audio_path=audio,
        subtitle_config_path="../JaVideoSrtGenAgent/config.json",
        wait_for_completion=False
    )
    print(f"已投递: {audio}")

# VideoSRT Agent 会依次处理所有文件
print("所有文件已投递，后台处理中...")
```

### 场景 4：从 out_dir 定期读取

```python
import os
from pathlib import Path

config = json.load(open("../JaVideoSrtGenAgent/config.json"))
out_dir = Path(config["out_dir"])

# 检查是否有新的字幕
def check_new_subtitles(last_check_time):
    subtitles = []
    for srt_file in out_dir.glob("*.srt"):
        if srt_file.stat().st_mtime > last_check_time:
            subtitles.append(str(srt_file))
    return subtitles

# 使用
import time
last_check = time.time()

while True:
    new_subs = check_new_subtitles(last_check)
    if new_subs:
        print(f"🆕 新字幕: {new_subs}")
        last_check = time.time()
    
    time.sleep(5)
```

---

## 常见问题

### Q：TTS 和 VideoSRT 不在同一机器，可以吗？

**A**：完全可以！这是 watch_dir 方案的优势。只要两者都能访问共享存储（NAS）：

```
TTS Agent (Windows/macOS/Linux) ──┐
                                   ├──→ NAS /watch_dir ←── VideoSRT (Linux GPU)
                                   │
                        out_dir ←──┘
```

### Q：watch_dir 需要多大空间？

**A**：不大。文件会被 VideoSRT 移动走。建议最少 10GB，用于暂存。

### Q：字幕何时才能读取？

**A**：当 `out_dir/{filename}_bi.srt` 出现时。可轮询或监控文件系统事件。

### Q：如何确认 VideoSRT 在运行？

**A**：

```bash
# SSH 到 VideoSRT 服务器
tail -f subtitle_service.log

# 或检查进程
ps aux | grep master_multiprcs

# 或检查目录
ls -lh /mnt/nas/watch/      # 应该有新文件
ls -lh /mnt/nas/subtitle_out/  # 应该有输出的字幕
```

### Q：投递了但字幕没有生成

**A**：检查：
1. watch_dir 路径是否正确 ✓
2. VideoSRT 进程是否运行 ✓
3. Gemini API 密钥是否有效 ✓
4. 文件格式是否支持 (`.wav`, `.mp3` 等) ✓
5. 查看 VideoSRT 日志看是否有错误 ✓

### Q：字幕翻译不满意怎么办？

**A**：修改 `srt_transltr.py` 的 Gemini Prompt（见 AGENTS.md）。或投递单语字幕（只做转写不翻译）。

### Q：能否只要日文不要中文？

**A**：两种方法：
1. 在 `config.json` 设 `"no_trans": true`
2. 只读 `.srt`（不读 `_bi.srt`）

---

## 生产部署建议

### 1. watch_dir 定期清理

```bash
# crontab -e
# 每天凌晨 2 点清理 7 天前的文件
0 2 * * * find /mnt/nas/watch -type f -mtime +7 -delete
```

### 2. 监控 VideoSRT 服务

```bash
# 检查服务是否运行
*/5 * * * * ps aux | grep master_multiprcs || /path/to/restart.sh

# 或使用 systemd
sudo systemctl status subtitle-service
```

### 3. 日志备份

```bash
# 定期备份日志
0 0 * * * gzip /mnt/nas/subtitle_service.log
```

### 4. NAS 存储监控

```bash
# 监控磁盘使用
df -h /mnt/nas/

# 如果快满了，清理旧文件
find /mnt/nas/watch -type f -mtime +30 -delete
find /mnt/nas/subtitle_out -type f -mtime +60 -delete
```

---

## 完整集成示例

```python
#!/usr/bin/env python3
# tts_agent_with_subtitle.py

import json
import logging
from subtitle_helper import post_audio_to_subtitle_service

logging.basicConfig(level=logging.INFO)

class TTSAgentWithSubtitle:
    def __init__(self, subtitle_config_path):
        self.subtitle_config = subtitle_config_path
    
    def process(self, text: str) -> tuple:
        """
        处理对话并生成音频和字幕
        
        Returns:
            (audio_path, subtitle_path)
        """
        # 1. TTS 生成音频
        logging.info(f"🎤 TTS 处理: {text[:50]}...")
        audio_path = self.generate_tts_audio(text)  # 你的 TTS 逻辑
        logging.info(f"✅ 音频已生成: {audio_path}")
        
        # 2. 投递到字幕服务
        logging.info("📤 投递到字幕服务...")
        subtitle_path = post_audio_to_subtitle_service(
            audio_path=audio_path,
            subtitle_config_path=self.subtitle_config,
            wait_for_completion=True  # 等待完成
        )
        
        if subtitle_path:
            logging.info(f"✅ 字幕已生成: {subtitle_path}")
            return audio_path, subtitle_path
        else:
            logging.warning(f"⚠️ 字幕生成失败")
            return audio_path, None
    
    def generate_tts_audio(self, text: str) -> str:
        """你的 TTS 模块"""
        # ... TTS 逻辑，生成 output.wav ...
        return "output.wav"

# 使用
if __name__ == "__main__":
    agent = TTSAgentWithSubtitle(
        subtitle_config_path="../JaVideoSrtGenAgent/config.json"
    )
    
    audio, subtitle = agent.process("こんにちは、これはテスト音声です。")
    
    if subtitle:
        with open(subtitle, encoding="utf-8") as f:
            print("=== 字幕内容 ===")
            print(f.read())
```

---

**更新时间**：2026-05-17
