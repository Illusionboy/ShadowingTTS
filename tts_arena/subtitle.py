from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


async def submit_to_watch_dir(audio_path: Path, watch_dir: Path, lang: str = "ja") -> Path:
    """Copy audio to watch_dir with language suffix: {stem}.{lang}{ext}.

    VideoSRT reads the lang code from the filename (e.g. dialogue.ja.mp3)
    and strips it when naming the output SRT (dialogue_bi.srt).
    """
    watch_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{audio_path.stem}.{lang}{audio_path.suffix}"
    dest = watch_dir / dest_name
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
    """Submit audio to VideoSRT watch_dir and wait for the SRT.

    The file is renamed to {stem}.{lang}{ext} on submission. VideoSRT strips
    the lang code when naming the output, so we poll using the original stem.
    """
    await submit_to_watch_dir(audio_path, watch_dir, lang)
    return await wait_for_subtitle(
        audio_stem=audio_path.stem,
        out_dir=out_dir,
        bilingual=bilingual,
        timeout=timeout,
    )
