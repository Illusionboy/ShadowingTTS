from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .arena import TTSArena, read_failed_model_names, result_table, write_results_manifest
from .base import TTSRequest
from .config import env, env_path, load_environment, output_format_from_env, required_env
from .dialogue import load_dialogue_script, run_dialogue
from .adapters import (
    AzureTTSAdapter,
    EdgeTTSAdapter,
    ElevenLabsAdapter,
    GoogleChirpAdapter,
    GPTSoVITSAdapter,
    OpenAITTSAdapter,
)


DEFAULT_JAPANESE_TEXT = (
    "彼は、昨日まで降り続いていた雨がようやく上がったにもかかわらず、"
    "濡れた石畳に映る朝焼けの色を眺めながら、"
    "これから自分が下さなければならない決断の重さを、"
    "誰にも悟られないよう静かに噛みしめていた。"
)


MODEL_ALIASES = {
    "edge": "Edge TTS",
    "google": "Google Chirp 3",
    "azure": "Azure TTS",
    "elevenlabs": "ElevenLabs",
    "openai": "OpenAI TTS",
    "gpt-sovits": "GPT-SoVITS",
}

MODEL_NAMES_TO_ALIASES = {value: key for key, value in MODEL_ALIASES.items()}


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def build_adapters(selected: set[str] | None = None):
    selected = selected or set(MODEL_ALIASES)
    adapters = []
    if "edge" in selected:
        adapters.append(EdgeTTSAdapter())
    if "google" in selected:
        adapters.append(GoogleChirpAdapter(env("GOOGLE_TTS_VOICE", "ja-JP-Chirp3-HD-Aoede") or ""))
    if "azure" in selected:
        adapters.append(
            AzureTTSAdapter(
                key=required_env("AZURE_SPEECH_KEY"),
                region=env("AZURE_SPEECH_REGION", "japaneast") or "japaneast",
                voice=env("AZURE_TTS_VOICE", "ja-JP-KeitaNeural") or "ja-JP-KeitaNeural",
            )
        )
    if "elevenlabs" in selected:
        adapters.append(
            ElevenLabsAdapter(
                api_key=required_env("ELEVENLABS_API_KEY"),
                model_id=env("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5") or "eleven_turbo_v2_5",
                voice_id=env("ELEVENLABS_VOICE_ID"),
                enable_cloning=env_bool("ELEVENLABS_ENABLE_CLONING"),
                clone_name=env("ELEVENLABS_CLONE_NAME", "ja-ref-arena") or "ja-ref-arena",
            )
        )
    if "openai" in selected:
        adapters.append(
            OpenAITTSAdapter(
                api_key=required_env("OPENAI_API_KEY"),
                model=env("OPENAI_TTS_MODEL", "tts-1-hd") or "tts-1-hd",
                voice=env("OPENAI_TTS_VOICE", "alloy") or "alloy",
            )
        )
    if "gpt-sovits" in selected:
        adapters.append(
            GPTSoVITSAdapter(
                base_url=env("GPT_SOVITS_BASE_URL", "http://localhost:9880") or "http://localhost:9880",
                ckpt_path=env("GPT_SOVITS_CKPT_PATH"),
                ref_audio_path=env("GPT_SOVITS_REF_AUDIO_PATH"),
                model_endpoint=env("GPT_SOVITS_MODEL_ENDPOINT", "/set_model") or "/set_model",
                tts_endpoint=env("GPT_SOVITS_TTS_ENDPOINT", "/tts") or "/tts",
            )
        )
    return adapters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a multi-model Japanese TTS arena.")
    parser.add_argument("--text", default=DEFAULT_JAPANESE_TEXT)
    parser.add_argument("--text-file", type=Path)
    parser.add_argument("--dialogue-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--format", choices=["mp3", "wav"], default=None)
    parser.add_argument("--reference-video", type=Path, default=None)
    parser.add_argument(
        "--models",
        default="edge,google,azure,elevenlabs,openai,gpt-sovits",
        help="Comma-separated: edge,google,azure,elevenlabs,openai,gpt-sovits",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="Only run models that failed in OUTPUT_DIR/results.json.",
    )
    return parser.parse_args()


async def main_async() -> None:
    load_environment()
    args = parse_args()
    text = args.text_file.read_text(encoding="utf-8") if args.text_file else args.text
    selected = {item.strip() for item in args.models.split(",") if item.strip()}
    if args.rerun_failed:
        failed_names = read_failed_model_names(args.output_dir)
        selected = {
            MODEL_NAMES_TO_ALIASES[name]
            for name in failed_names
            if name in MODEL_NAMES_TO_ALIASES
        }
        if not selected:
            print(f"No failed models found in {args.output_dir / 'results.json'}")
            return
        print(f"Rerunning failed models: {', '.join(sorted(selected))}")
    reference_video = args.reference_video or env_path("TTS_REFERENCE_VIDEO", "ref_japanese.mp4")
    output_format = args.format or output_format_from_env()
    adapters = build_adapters(selected)
    if args.dialogue_file:
        script = load_dialogue_script(args.dialogue_file)
        results = await run_dialogue(
            adapters=adapters,
            script=script,
            output_dir=args.output_dir,
            output_format=output_format,
            reference_video=reference_video,
        )
    else:
        request = TTSRequest(
            text=text,
            output_dir=args.output_dir,
            output_format=output_format,
            reference_video=reference_video,
        )
        arena = TTSArena(adapters)
        results = await arena.run(request)
    print(result_table(results))
    manifest_path = write_results_manifest(results, args.output_dir)
    print(f"\nSaved result manifest: {manifest_path}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
