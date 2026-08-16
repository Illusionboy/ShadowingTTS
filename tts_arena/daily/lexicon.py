from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from ..config import env_path
from .scenarios import CONTENT_DIR

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_readings() -> dict[str, str]:
    """Kanji → kana map applied to TTS input only.

    ElevenLabs' Japanese G2P misreads logistics compounds — 進捗 comes out as
    シンポ, 棚卸 as パズバ, 荷役 as ゴイチ. Turbo v2.5 only supports alias-style
    pronunciation rules (phonemes need flash_v2 / v3), and an alias is just "send
    different text", so we do the substitution locally: it works for every
    provider and leaves the subtitles showing the original kanji.
    """
    payload = json.loads((CONTENT_DIR / "readings.json").read_text(encoding="utf-8"))
    readings: dict[str, str] = {
        key: value
        for key, value in payload.get("readings", {}).items()
        if not key.startswith("_")
    }

    extra_path = env_path("DAILY_READINGS_FILE")
    if extra_path and extra_path.exists():
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
        readings.update(extra.get("readings", extra))
    return readings


def apply_readings(text: str, readings: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Replace known-misread words with their kana. Longest match wins."""
    readings = readings if readings is not None else load_readings()
    applied: list[str] = []
    for word in sorted(readings, key=len, reverse=True):
        if word in text:
            text = text.replace(word, readings[word])
            applied.append(word)
    return text, applied


def spoken_text(text: str) -> str:
    """The text to synthesize for a Japanese line."""
    result, applied = apply_readings(text)
    if applied:
        logger.debug("Applied readings: %s", ", ".join(applied))
    return result
