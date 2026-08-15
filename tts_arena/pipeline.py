from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .base import AudioFormat, TTSResult
from .cli import build_adapters, env_bool
from .config import env, env_path, output_format_from_env, required_env
from .dialogue import DialogueScript, run_dialogue
from .gemini_normalizer import (
    GeminiDialogueNormalizer,
    dialogue_to_json,
    normalize_without_llm,
)


_FORMAL_TOPICS = {
    "interview", "business", "formal", "meeting", "presentation",
    "negotiat", "professional", "office", "work", "client", "proposal",
    "contract", "report", "conference", "seminar",
}
_CASUAL_TOPICS = {
    "casual", "chat", "friend", "daily", "restaurant", "shopping",
    "travel", "hobby", "weekend", "family", "date", "party",
}


def voice_settings_for_register(register: str) -> dict:
    """ElevenLabs voice_settings per speaking register.

    Callers that know the register (the daily lesson pipeline) pass it directly;
    the Telegram path infers it from the topic slug below.
    """
    # Style above ~0.3 combined with low stability measurably degraded Japanese
    # articulation in A/B tests (part numbers and counters came out slurred), so
    # these presets stay on the calm side — shadowing needs clarity over drama.
    if register == "formal":
        # Business / interview: composed, clearly articulated
        return {"stability": 0.45, "similarity_boost": 0.75, "style": 0.30, "use_speaker_boost": True}
    if register == "casual":
        # Casual conversation: a bit more movement, still steady
        return {"stability": 0.40, "similarity_boost": 0.75, "style": 0.35, "use_speaker_boost": True}
    # General default
    return {"stability": 0.45, "similarity_boost": 0.75, "style": 0.30, "use_speaker_boost": True}


def _voice_settings_for_topic(topic_slug: str) -> dict:
    slug = topic_slug.lower()
    if any(k in slug for k in _FORMAL_TOPICS):
        return voice_settings_for_register("formal")
    if any(k in slug for k in _CASUAL_TOPICS):
        return voice_settings_for_register("casual")
    return voice_settings_for_register("general")


def default_dialogue_voices(provider: str) -> dict[str, dict[str, str]]:
    voices: dict[str, dict[str, str]] = {
        "A": {},
        "B": {},
    }
    if provider == "elevenlabs":
        voice_a = env("ELEVENLABS_VOICE_ID")
        voice_b = env("ELEVENLABS_VOICE_ID2") or voice_a
        if voice_a:
            voices["A"]["elevenlabs"] = voice_a
        if voice_b:
            voices["B"]["elevenlabs"] = voice_b
    elif provider == "edge":
        voices["A"]["edge_tts"] = env("EDGE_TTS_VOICE_A", "ja-JP-NanamiNeural") or "ja-JP-NanamiNeural"
        voices["B"]["edge_tts"] = env("EDGE_TTS_VOICE_B", "ja-JP-KeitaNeural") or "ja-JP-KeitaNeural"
    elif provider == "azure":
        voices["A"]["azure_tts"] = env("AZURE_TTS_VOICE_A", "ja-JP-NanamiNeural") or "ja-JP-NanamiNeural"
        voices["B"]["azure_tts"] = env("AZURE_TTS_VOICE_B", "ja-JP-KeitaNeural") or "ja-JP-KeitaNeural"
    elif provider == "openai":
        voices["A"]["openai_tts"] = env("OPENAI_TTS_VOICE_A", "alloy") or "alloy"
        voices["B"]["openai_tts"] = env("OPENAI_TTS_VOICE_B", "onyx") or "onyx"
    return voices


async def normalize_user_dialogue(
    user_text: str,
    language: str = "ja",
    mode: str = "dialogue",
) -> DialogueScript:
    if env_bool("ENABLE_GEMINI_DIALOGUE_PARSER", True):
        api_key = required_env("GEMINI_API_KEY")
        normalizer = GeminiDialogueNormalizer(
            api_key=api_key,
            model=env("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash",
        )
        return await normalizer.normalize(user_text, language=language, mode=mode)
    return normalize_without_llm(user_text, mode=mode)


async def synthesize_user_dialogue(
    user_text: str,
    output_root: Path | None = None,
    provider: str | None = None,
    output_format: AudioFormat | None = None,
    language: str = "ja",
    mode: str = "dialogue",
) -> tuple[DialogueScript, TTSResult]:
    provider = provider or env("DEFAULT_TTS_PROVIDER", "elevenlabs") or "elevenlabs"
    output_format = output_format or output_format_from_env()
    output_root = output_root or env_path("SERVICE_OUTPUT_DIR", "outputs/service") or Path("outputs/service")

    script = await normalize_user_dialogue(user_text, language=language, mode=mode)
    script = replace(script, voices=default_dialogue_voices(provider))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_stem = f"{script.topic_slug}_{ts}"
    output_dir = output_root / ts
    results = await run_dialogue(
        adapters=build_adapters({provider}),
        script=script,
        output_dir=output_dir,
        output_format=output_format,
        reference_video=env_path("TTS_REFERENCE_VIDEO", "ref_japanese.mp4"),
        output_stem=output_stem,
        voice_settings_override=_voice_settings_for_topic(script.topic_slug),
    )
    result = results[0]
    (output_dir / "dialogue.json").write_text(dialogue_to_json(script), encoding="utf-8")
    return script, result
