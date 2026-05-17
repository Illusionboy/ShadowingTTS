# Ubuntu Server Deployment

## 1. 系统依赖

只需要 ffmpeg 和 git（Python 由 Conda 管理）：

```bash
sudo apt update
sudo apt install -y ffmpeg git
```

---

## 2. 配置 SSH Key（连 GitHub）

```bash
# 生成密钥（一路回车）
ssh-keygen -t ed25519 -C "your@email.com"

# 查看公钥，复制输出内容
cat ~/.ssh/id_ed25519.pub
```

把公钥粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key，保存后验证：

```bash
ssh -T git@github.com
# 输出 "Hi Illusionboy! You've successfully authenticated..." 即成功
```

---

## 3. 克隆项目

```bash
cd ~
git clone git@github.com:Illusionboy/ShadowingTTS.git
cd ShadowingTTS
```

---

## 4. Conda 环境 & 依赖

```bash
# 创建环境（Python 3.11）
conda create -n shadowingtts python=3.11 -y
conda activate shadowingtts

# 安装依赖
pip install -r requirements.txt
```

> **查找 Conda 环境的 Python 路径**（systemd 需要用绝对路径）：
>
> ```bash
> conda activate shadowingtts && which python
> # 示例输出：/home/youruser/miniconda3/envs/shadowingtts/bin/python
> ```
>
> 记下这个路径，第 7 节 systemd 配置里会用到。

---

## 5. 配置 `.env`

```bash
cp .env.example .env
nano .env   # 或 vim .env
```

Telegram + ElevenLabs 最小配置：

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_MAX_TEXT_LENGTH=2000
TELEGRAM_DEBUG_REPLY_JSON=false
DEFAULT_TTS_PROVIDER=elevenlabs
TTS_OUTPUT_FORMAT=mp3
SERVICE_OUTPUT_DIR=outputs/service

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
ENABLE_GEMINI_DIALOGUE_PARSER=true

ELEVENLABS_API_KEY=
ELEVENLABS_MODEL_ID=eleven_turbo_v2_5
ELEVENLABS_ENABLE_CLONING=false
ELEVENLABS_VOICE_ID=
ELEVENLABS_VOICE_ID2=

# 如果 VideoSRT Agent 跑在同一台机器上，填写路径；否则留空
VIDEOSRT_WATCH_DIR=
VIDEOSRT_OUT_DIR=
VIDEOSRT_TIMEOUT=600
```

---

## 6. 手动启动测试

```bash
conda activate shadowingtts
python -m tts_arena.telegram_bot
# Ctrl+C 停止
```

确认 bot 响应正常后，再配置 systemd。

---

## 7. systemd 开机自启

### 创建 service 文件

将以下占位符替换为实际值：

- `YOUR_USER` → 你的用户名（`whoami` 查看）
- `CONDA_PYTHON_PATH` → 第 4 节 `which python` 输出的绝对路径

```bash
sudo nano /etc/systemd/system/shadowingtts.service
```

写入：

```ini
[Unit]
Description=ShadowingTTS Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/ShadowingTTS
ExecStart=CONDA_PYTHON_PATH -m tts_arena.telegram_bot
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

示例（miniconda）：

```ini
ExecStart=/home/mac/miniconda3/envs/shadowingtts/bin/python -m tts_arena.telegram_bot
```

### 启用并启动

```bash
sudo systemctl daemon-reload
sudo systemctl enable shadowingtts    # 开机自启
sudo systemctl start shadowingtts     # 立即启动
sudo systemctl status shadowingtts    # 确认运行状态
```

### 查看实时日志

```bash
journalctl -u shadowingtts -f
```

---

## 8. 日常更新（Mac 推送后 Ubuntu 同步）

Mac 端推送：

```bash
git push
```

Ubuntu 端拉取并重启：

```bash
cd ~/ShadowingTTS
git pull
sudo systemctl restart shadowingtts
sudo systemctl status shadowingtts
```

如果 `requirements.txt` 有变动，先重装依赖：

```bash
conda activate shadowingtts
pip install -r requirements.txt
sudo systemctl restart shadowingtts
```

---

## 9. 常用运维命令

| 操作 | 命令 |
| ------ | ------ |
| 查看状态 | `sudo systemctl status shadowingtts` |
| 启动 | `sudo systemctl start shadowingtts` |
| 停止 | `sudo systemctl stop shadowingtts` |
| 重启 | `sudo systemctl restart shadowingtts` |
| 实时日志 | `journalctl -u shadowingtts -f` |
| 最近 100 行日志 | `journalctl -u shadowingtts -n 100` |
| 取消自启 | `sudo systemctl disable shadowingtts` |
