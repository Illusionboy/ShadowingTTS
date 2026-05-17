# Ubuntu 服务器配置指南 - watch_dir 方案

你的配置有一个关键问题，我来帮你修复。

---

## 🔴 问题分析

你的当前配置：

```json
{
  "out_dir": "/mnt/nas/videos",
  "watch_dir": "/mnt/nas/videos/watch_dir"
}
```

**问题**：`watch_dir` 是 `out_dir` 的子目录！

这会导致：

1. ❌ 文件放入 `watch_dir` 被检测
2. ❌ Whisper 处理完后输出到 `out_dir` = `/mnt/nas/videos`
3. ❌ 输出文件与 `watch_dir` 混在一起
4. ❌ 热目录监控可能卡顿或死循环

---

## ✅ 正确的配置

将目录**完全分离**：

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "telegram_api_token": "YOUR_TELEGRAM_TOKEN",
  "allowed_user_id": 1039601553,
  "chunk_size": 40,
  
  "watch_dir": "/mnt/nas/watch_input",        // 🔴 TTS 投递音频
  "out_dir": "/mnt/nas/subtitle_output",      // 🟢 字幕输出
  
  "input_dir": "./input_srt",
  "video_dir": "./video_dir",
  "lang": "ja",
  "sleep_time": 2,
  "max_res": 720,
  "no_trans": false
}
```

**关键点**：

- `watch_dir` 和 `out_dir` 完全独立，在不同位置
- `watch_dir`：TTS 放音频的地方
- `out_dir`：VideoSRT 输出字幕的地方

---

## 修改步骤

### 1. 更新配置文件

```bash
# 编辑配置文件
nano config.json
```

替换为：

```json
{
  "gemini_api_key": "",
  "telegram_api_token": "YOUR_TOKEN",
  "allowed_user_id": 1039601553,
  "chunk_size": 40,
  "video_dir": "./video_dir",
  "input_dir": "./input_srt",
  "watch_dir": "/mnt/nas/watch_input",
  "out_dir": "/mnt/nas/subtitle_output",
  "lang": "ja",
  "sleep_time": 2,
  "max_res": 720,
  "no_trans": false
}
```

### 2. 创建必要的目录

```bash
mkdir -p /mnt/nas/watch_input
mkdir -p /mnt/nas/subtitle_output

# 验证
ls -la /mnt/nas/watch_input
ls -la /mnt/nas/subtitle_output
```

### 3. 重启 VideoSRT 服务

```bash
# 停止当前进程
pkill -f "python master_multiprcs.py"

# 验证已停止
ps aux | grep master_multiprcs

# 重启
python master_multiprcs.py &

# 或使用 systemd（如果配置过）
sudo systemctl restart dtv_bot
```

### 4. 验证服务启动

```bash
# 查看日志
tail -f nohup.out

# 应该看到：
# 👁️  热目录监控已启动: /mnt/nas/watch_input
```

---

## 测试配置

使用诊断脚本：

```bash
python diagnose_watch_dir.py
```

这个脚本会检查：

- ✅ 配置文件正确性
- ✅ 目录存在和权限
- ✅ Gemini API 连接
- ✅ Whisper 环境
- ✅ 文件处理流程（创建测试文件）

---

## TTS 投递代码（保持不变）

你的 TTS 投递代码保持原样：

```python
import shutil
import json
from pathlib import Path

config = json.load(open("../JaVideoSrtGenAgent/config.json"))

# 投递到 watch_dir
audio_file = "output.wav"
watch_dir = Path(config["watch_dir"])
shutil.copy2(audio_file, watch_dir / audio_file)

print(f"✅ 已投递: {watch_dir / audio_file}")
```

---

## 验证工作流

```bash
# 1. 确认 VideoSRT 在运行
ps aux | grep master_multiprcs

# 2. 查看 watch_dir（应该是空的或只有处理中的文件）
ls -lh /mnt/nas/watch_input/

# 3. 查看 out_dir（应该有字幕输出）
ls -lh /mnt/nas/subtitle_output/

# 4. 查看日志
tail -f nohup.out | grep -E "(监控|投递|转写|翻译|输出)"
```

---

## 常见问题

### Q1：修改后还是不工作？

A：检查：

1. VideoSRT 进程是否真的重启了（`ps aux | grep master_multiprcs`）
2. watch_dir 是否可写（`touch /mnt/nas/watch_input/test.txt`）
3. Whisper 模型是否加载完毕（查看日志有 `[Whisper 模型加载完毕]`）

### Q2：怎样知道文件被处理了？

A：检查日志：

```bash
tail -f nohup.out | grep "新文件就绪\|转写\|翻译"
```

或查看目录变化：

```bash
# 终端 1：监控 watch_dir
watch -n 1 'ls -lh /mnt/nas/watch_input/'

# 终端 2：监控 out_dir
watch -n 1 'ls -lh /mnt/nas/subtitle_output/'
```

### Q3：字幕输出了但是空的？

A：检查：

1. Gemini API 是否有效（看日志有无翻译错误）
2. 音频格式是否支持 (`.wav`, `.mp3` 等)
3. 运行诊断：`python diagnose_watch_dir.py`

---

## 快速测试

放一个 mp3 到 watch_dir，然后：

```bash
# 监控输出
for i in {1..60}; do
  sleep 1
  if [ -f "/mnt/nas/subtitle_output/你的文件名_bi.srt" ]; then
    echo "✅ 字幕已生成！"
    cat /mnt/nas/subtitle_output/你的文件名_bi.srt
    break
  fi
  echo "⏳ 等待中... ($i/60)"
done
```

---

## 完整流程图

```
┌─────────────────────────┐
│   TTS Agent             │
│   生成 audio.wav        │
└──────────┬──────────────┘
           │
           ↓ shutil.copy2()
┌──────────────────────────────┐
│ /mnt/nas/watch_input/        │ ← 热目录
│  audio.wav ←── TTS 放这里    │
└──────────┬───────────────────┘
           │ watchdog 监控
           ↓
┌──────────────────────────────┐
│   VideoSRT Agent             │
│  - Whisper 转写              │
│  - Gemini 翻译               │
└──────────┬───────────────────┘
           │
           ↓ 输出
┌──────────────────────────────┐
│ /mnt/nas/subtitle_output/    │ ← 输出目录
│  audio_bi.srt ←── 字幕文件   │
└──────────────────────────────┘
           ↑
           │ TTS 读取（可选）
           │
┌──────────────────────────────┐
│   TTS Agent                  │
│   使用字幕和音频继续处理     │
└──────────────────────────────┘
```

---

**修改后重启，问题应该就解决了！**

如果还有问题，运行诊断脚本并分享输出：

```bash
python diagnose_watch_dir.py 2>&1 | tee diagnose_result.txt
```
