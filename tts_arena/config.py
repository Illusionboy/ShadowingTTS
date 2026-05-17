from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .base import AudioFormat


def load_environment() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    load_dotenv()


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_path(name: str, default: str | None = None) -> Path | None:
    value = env(name, default)
    return Path(value).expanduser() if value else None


def output_format_from_env(default: AudioFormat = "mp3") -> AudioFormat:
    value = env("TTS_OUTPUT_FORMAT", default) or default
    if value not in ("mp3", "wav"):
        raise ValueError("TTS_OUTPUT_FORMAT must be mp3 or wav")
    return value  # type: ignore[return-value]
