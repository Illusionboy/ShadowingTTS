from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .base import AudioFormat, TTSAdapter, TTSRequest, TTSResult


@dataclass(frozen=True)
class DialogueTurn:
    speaker: str
    text: str


@dataclass(frozen=True)
class DialogueScript:
    turns: list[DialogueTurn]
    voices: dict[str, dict[str, str]]
    pause_ms: int = 450
    topic_slug: str = "dialogue"


def normalize_adapter_name(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def adapter_key(adapter: TTSAdapter) -> str:
    return normalize_adapter_name(adapter.name)


def load_dialogue_script(path: Path) -> DialogueScript:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        turns_payload = payload
        voices: dict[str, dict[str, str]] = {}
        pause_ms = 450
    else:
        turns_payload = payload["turns"]
        voices = payload.get("voices", {})
        pause_ms = int(payload.get("pause_ms", 450))

    turns = [
        DialogueTurn(speaker=str(item["speaker"]), text=str(item["text"]))
        for item in turns_payload
    ]
    return DialogueScript(turns=turns, voices=voices, pause_ms=pause_ms)


async def run_dialogue(
    adapters: list[TTSAdapter],
    script: DialogueScript,
    output_dir: Path,
    output_format: AudioFormat,
    reference_video: Path | None,
    output_stem: str | None = None,
    voice_settings_override: dict | None = None,
    language: str | None = None,
) -> list[TTSResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = [
        _run_adapter_dialogue(
            adapter, script, output_dir, output_format,
            reference_video, output_stem, voice_settings_override, language,
        )
        for adapter in adapters
    ]
    return await asyncio.gather(*tasks)


async def _run_adapter_dialogue(
    adapter: TTSAdapter,
    script: DialogueScript,
    output_dir: Path,
    output_format: AudioFormat,
    reference_video: Path | None,
    output_stem: str | None = None,
    voice_settings_override: dict | None = None,
    language: str | None = None,
) -> TTSResult:
    key = adapter_key(adapter)
    segment_dir = output_dir / "_dialogue_segments" / key
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []

    try:
        for index, turn in enumerate(script.turns, start=1):
            request = TTSRequest(
                text=turn.text,
                output_dir=segment_dir,
                output_format=output_format,
                reference_video=reference_video,
                voice=_voice_for(script.voices, turn.speaker, key),
                speaker=turn.speaker,
                output_stem=f"{index:03d}_{_safe_name(turn.speaker)}",
                voice_settings=voice_settings_override,
                language=language,
            )
            result = await adapter.synthesize(request)
            if not result.ok or not result.output_path:
                raise RuntimeError(result.error or "segment synthesis failed")
            segment_paths.append(result.output_path)

        stem = output_stem or f"{key}_dialogue"
        output_path = output_dir / f"{stem}.{output_format}"
        await concat_audio(segment_paths, output_path, script.pause_ms)
        return TTSResult(adapter.name, output_path, True)
    except Exception as exc:  # noqa: BLE001 - keep one provider failure local.
        return TTSResult(adapter.name, None, False, f"{type(exc).__name__}: {exc}")


def _voice_for(voices: dict[str, dict[str, str]], speaker: str, provider_key: str) -> str | None:
    speaker_voices = voices.get(speaker, {})
    return speaker_voices.get(provider_key) or speaker_voices.get("default")


def _safe_name(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "speaker"


async def concat_audio(segment_paths: list[Path], output_path: Path, pause_ms: int) -> None:
    if not segment_paths:
        raise RuntimeError("Dialogue has no generated audio segments")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to concatenate dialogue audio")

    work_dir = output_path.parent / "_dialogue_concat" / output_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    silence_path = work_dir / "silence.wav"
    if pause_ms > 0:
        await _run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=mono:sample_rate=44100",
                "-t",
                f"{pause_ms / 1000:.3f}",
                str(silence_path),
            ]
        )

    normalized_paths: list[Path] = []
    for index, segment_path in enumerate(segment_paths, start=1):
        normalized = work_dir / f"{index:03d}.wav"
        await _run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(segment_path),
                "-ac",
                "1",
                "-ar",
                "44100",
                str(normalized),
            ]
        )
        normalized_paths.append(normalized)

    concat_list = work_dir / "concat.txt"
    concat_items = _interleave_silence(normalized_paths, silence_path if pause_ms > 0 else None)
    concat_list.write_text(
        "".join(f"file '{_escape_concat_path(item)}'\n" for item in concat_items),
        encoding="utf-8",
    )

    codec_args = ["-c:a", "libmp3lame", "-b:a", "192k"] if output_path.suffix == ".mp3" else ["-c:a", "pcm_s16le"]
    await _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            *codec_args,
            str(output_path),
        ]
    )


def _interleave_silence(paths: list[Path], silence_path: Path | None) -> list[Path]:
    if not silence_path:
        return paths
    items: list[Path] = []
    for index, path in enumerate(paths):
        if index:
            items.append(silence_path)
        items.append(path)
    return items


def _escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


async def _run_ffmpeg(command: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
