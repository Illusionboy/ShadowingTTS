from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


AudioFormat = Literal["mp3", "wav"]


@dataclass(frozen=True)
class TTSRequest:
    text: str
    output_dir: Path
    output_format: AudioFormat = "mp3"
    reference_video: Path | None = None
    voice: str | None = None
    speaker: str | None = None
    output_stem: str | None = None
    voice_settings: dict[str, Any] | None = None
    language: str | None = None


@dataclass(frozen=True)
class TTSResult:
    model_name: str
    output_path: Path | None
    ok: bool
    error: str | None = None


class TTSAdapter:
    """Common adapter interface for every TTS provider."""

    name: str

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        raise NotImplementedError

    def output_path(self, request: TTSRequest) -> Path:
        safe_name = request.output_stem or self.name.lower().replace(" ", "_").replace("-", "_")
        return request.output_dir / f"{safe_name}.{request.output_format}"
