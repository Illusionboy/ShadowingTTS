from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from ..dialogue import normalize_adapter_name
from .generator import DailyLesson, lesson_turns

logger = logging.getLogger(__name__)


class SegmentTimingError(RuntimeError):
    """Raised when the synthesized segments cannot be matched to the script."""


def segment_dir(output_dir: Path, adapter_name: str) -> Path:
    """Where run_dialogue() left the per-turn audio for this adapter."""
    return output_dir / "_dialogue_segments" / normalize_adapter_name(adapter_name)


def find_segments(output_dir: Path, adapter_name: str, output_format: str) -> list[Path]:
    directory = segment_dir(output_dir, adapter_name)
    return sorted(directory.glob(f"[0-9][0-9][0-9]_*.{output_format}"))


async def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SegmentTimingError("ffprobe is required to build subtitles from the script")
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise SegmentTimingError(stderr.decode("utf-8", errors="replace"))
    try:
        return float(stdout.decode().strip())
    except ValueError as exc:
        raise SegmentTimingError(f"Unreadable duration for {path}: {stdout!r}") from exc


def _timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(lines: list[tuple[float, float, list[str]]]) -> str:
    blocks = []
    for index, (start, end, texts) in enumerate(lines, start=1):
        body = "\n".join(text for text in texts if text)
        blocks.append(f"{index}\n{_timestamp(start)} --> {_timestamp(end)}\n{body}\n")
    return "\n".join(blocks)


async def script_srt(
    lesson: DailyLesson,
    lang: str,
    output_dir: Path,
    adapter_name: str,
    output_format: str,
    pause_ms: int,
    merged_audio: Path | None = None,
    bilingual: bool = True,
) -> str:
    """Build an SRT from the script we synthesized, not from ASR.

    Each turn was synthesized as its own file and concatenated with a fixed
    silence, so the timeline is known exactly. The only unknown is the few
    milliseconds the mp3 encoder adds, which is absorbed by scaling the timeline
    to the merged file's real duration.
    """
    turns = lesson_turns(lesson, lang)
    segments = find_segments(output_dir, adapter_name, output_format)
    if len(segments) != len(turns):
        raise SegmentTimingError(
            f"{len(segments)} segments for {len(turns)} turns in {output_dir}"
        )

    durations = [await probe_duration(path) for path in segments]
    pause = pause_ms / 1000
    expected_total = sum(durations) + pause * max(0, len(durations) - 1)

    scale = 1.0
    if merged_audio and merged_audio.exists() and expected_total > 0:
        actual_total = await probe_duration(merged_audio)
        ratio = actual_total / expected_total
        if 0.9 <= ratio <= 1.1:
            scale = ratio
        else:
            logger.warning(
                "Merged duration %.2fs differs from expected %.2fs; not scaling",
                actual_total,
                expected_total,
            )

    lines: list[tuple[float, float, list[str]]] = []
    cursor = 0.0
    for turn, duration in zip(turns, durations):
        start = cursor * scale
        end = (cursor + duration) * scale
        texts = [turn.text]
        if bilingual and turn.text_zh:
            texts.append(turn.text_zh)
        lines.append((start, end, texts))
        cursor += duration + pause
    return build_srt(lines)
