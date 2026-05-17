from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


async def ensure_reference_wav(reference_video: Path, work_dir: Path) -> Path:
    """Extract a mono 44.1 kHz WAV reference for cloning providers."""
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"{reference_video.stem}.wav"
    if target.exists() and target.stat().st_mtime >= reference_video.stat().st_mtime:
        return target

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract audio from ref_japanese.mp4")

    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(reference_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "44100",
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
    return target
