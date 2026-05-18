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
    If the destination already exists a counter suffix (_2, _3 …) is appended
    to avoid overwriting a file that is still being processed.
    """
    watch_dir.mkdir(parents=True, exist_ok=True)
    base_stem = f"{audio_path.stem}.{lang}"
    dest = watch_dir / f"{base_stem}{audio_path.suffix}"
    counter = 2
    while await asyncio.to_thread(dest.exists):
        dest = watch_dir / f"{base_stem}_{counter}{audio_path.suffix}"
        counter += 1
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
    dest = await submit_to_watch_dir(audio_path, watch_dir, lang)
    # dest stem is "{original_stem}.{lang}" or "{original_stem}.{lang}_{n}".
    # VideoSRT strips the last ".{lang}" segment to form the SRT stem,
    # so we poll using the part before that suffix.
    srt_stem = dest.stem.rsplit(".", 1)[0]
    return await wait_for_subtitle(
        audio_stem=srt_stem,
        out_dir=out_dir,
        bilingual=bilingual,
        timeout=timeout,
    )
