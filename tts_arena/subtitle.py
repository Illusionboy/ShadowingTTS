from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


async def submit_to_watch_dir(audio_path: Path, watch_dir: Path) -> Path:
    """Copy audio file to VideoSRT watch_dir. Returns destination path."""
    watch_dir.mkdir(parents=True, exist_ok=True)
    dest = watch_dir / audio_path.name
    await asyncio.to_thread(shutil.copy2, str(audio_path), str(dest))
    logger.info("Submitted to VideoSRT watch_dir: %s", dest)
    return dest


async def wait_for_subtitle(
    audio_stem: str,
    out_dir: Path,
    bilingual: bool = True,
    timeout: int = 600,
    poll_interval: float = 3.0,
) -> Path | None:
    """Poll out_dir for {audio_stem}_bi.srt (or {audio_stem}.srt). Returns None on timeout."""
    suffix = "_bi" if bilingual else ""
    srt_path = out_dir / f"{audio_stem}{suffix}.srt"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await asyncio.to_thread(srt_path.exists):
            logger.info("Subtitle ready: %s", srt_path)
            return srt_path
        await asyncio.sleep(poll_interval)
    logger.warning("Subtitle timed out after %ds: %s", timeout, srt_path)
    return None


async def submit_and_wait(
    audio_path: Path,
    watch_dir: Path,
    out_dir: Path,
    lang: str = "ja",
    bilingual: bool = True,
    timeout: int = 600,
) -> Path | None:
    """Submit audio to VideoSRT and wait for SRT. Returns SRT path or None."""
    del lang  # consumed by VideoSRT config; kept as param for future use
    await submit_to_watch_dir(audio_path, watch_dir)
    return await wait_for_subtitle(
        audio_stem=audio_path.stem,
        out_dir=out_dir,
        bilingual=bilingual,
        timeout=timeout,
    )
