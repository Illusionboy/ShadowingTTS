# Deployment (3060Ti host)

Both services run from `/home/neox/svr` on the GPU host (`ssh 3060ti`):

| Unit | What it runs |
| --- | --- |
| `shadowingtts.service` | Telegram bot (`python -m tts_arena.telegram_bot`), always on |
| `dtv_bot.service` | JaVideoSrtGenAgent, owns the VideoSRT watch dir and Whisper |
| `shadowing-daily.timer` | Daily lesson job (`python -m tts_arena.daily`), 06:30 JST |

## Install the daily timer

```bash
sudo cp deploy/shadowing-daily.service deploy/shadowing-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now shadowing-daily.timer
systemctl list-timers | grep shadowing
```

Run it once by hand (does not disturb the timer schedule):

```bash
sudo systemctl start shadowing-daily.service
journalctl -u shadowing-daily -f
```

## After changing bot code

```bash
sudo systemctl restart shadowingtts
journalctl -u shadowingtts -f
```

The timer job and the bot share `outputs/daily/.lock`, so only one lesson is
generated at a time; the loser reports "another lesson run is in progress".

## Subtitle round trip

`VIDEOSRT_WATCH_DIR` must point at the directory `dtv_bot` actually watches —
on this host `config.json` uses the relative path `watch_input`, so the value in
`.env` is `../JaVideoSrtGenAgent/watch_input`. Outputs land in
`VIDEOSRT_OUT_DIR` (`/mnt/nas/videos/`) as `{stem}.{lang}_bi.srt` and the daily
job copies them next to the audio in `DAILY_NAS_DIR`.
