from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


async def submit_to_watch_dir(audio_path: Path, watch_dir: Path, lang: str = "ja") -> Path:
    """Copy audio to watch_dir with language suffix: {stem}.{lang}{ext}.

    VideoSRT reads the lang code from the filename (e.g. dialogue.ja.mp3) and
    keeps that name for its own outputs, so the SRT comes back as
    dialogue.ja_bi.srt.
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


def srt_candidates(stems: Sequence[str], bilingual: bool = True) -> list[str]:
    """Build the SRT filenames to poll for, in priority order."""
    suffix = "_bi" if bilingual else ""
    names: list[str] = []
    for stem in stems:
        name = f"{stem}{suffix}.srt"
        if name not in names:
            names.append(name)
    return names


async def wait_for_subtitle(
    audio_stem: str | Sequence[str],
    out_dir: Path,
    bilingual: bool = True,
    timeout: int = 600,
    poll_interval: float = 3.0,
    lang: str | None = None,
) -> Path | None:
    """Poll out_dir for the subtitle of audio_stem. Returns None on timeout.

    Current VideoSRT keeps the lang suffix on its outputs ({stem}.{lang}_bi.srt);
    older builds stripped it ({stem}_bi.srt). Both are polled, newest convention
    first, so either side can be upgraded independently.
    """
    stems = [audio_stem] if isinstance(audio_stem, str) else list(audio_stem)
    if lang:
        stems = [f"{stems[0]}.{lang}", *stems]
    candidates = [out_dir / name for name in srt_candidates(stems, bilingual)]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for candidate in candidates:
            if await asyncio.to_thread(candidate.exists):
                logger.info("Subtitle ready: %s", candidate)
                return candidate
        await asyncio.sleep(poll_interval)
    logger.warning(
        "Subtitle timed out after %ds: %s",
        timeout,
        ", ".join(str(item) for item in candidates),
    )
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

    The file is renamed to {stem}.{lang}{ext} on submission and VideoSRT keeps
    that name, so the submitted stem is polled first and the original stem is
    kept as a fallback for builds that strip the lang code.
    """
    dest = await submit_to_watch_dir(audio_path, watch_dir, lang)
    return await wait_for_subtitle(
        audio_stem=[dest.stem, audio_path.stem],
        out_dir=out_dir,
        bilingual=bilingual,
        timeout=timeout,
    )
