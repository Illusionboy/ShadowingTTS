from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from ..base import AudioFormat
from ..cli import build_adapters
from ..config import env, env_path, output_format_from_env
from ..dialogue import run_dialogue
from ..pipeline import default_dialogue_voices, voice_settings_for_register
from ..subtitle import srt_candidates, submit_to_watch_dir, wait_for_subtitle
from . import notify
from .generator import DailyLesson, GeminiLessonGenerator, lesson_to_json, lesson_to_script
from .publish import publish_file, script_markdown, write_text_file
from .srtgen import SegmentTimingError, script_srt
from .scenarios import (
    Scenario,
    append_history,
    load_state,
    mark_used,
    nas_dir,
    next_scenario,
    save_state,
    work_dir,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], Awaitable[None]]

EN_VOICE_DEFAULTS = {
    "edge_tts": ("en-US-JennyNeural", "en-US-GuyNeural"),
    "azure_tts": ("en-US-JennyNeural", "en-US-GuyNeural"),
}


class LessonBusy(RuntimeError):
    """Raised when another lesson run already holds the single-flight lock."""


class LessonSkipped(RuntimeError):
    """Raised when today's lesson is already published and --force was not given."""


@dataclass
class LangArtifact:
    lang: str
    audio: Path | None = None
    published_audio: Path | None = None
    subtitle: Path | None = None
    published_subtitle: Path | None = None
    adapter_name: str | None = None
    error: str | None = None


@dataclass
class LessonResult:
    stem: str
    scenario: Scenario
    lesson: DailyLesson
    artifacts: list[LangArtifact] = field(default_factory=list)
    script_path: Path | None = None
    meta_path: Path | None = None
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.dry_run or any(item.published_audio for item in self.artifacts)

    @property
    def audio_files(self) -> list[Path]:
        return [item.published_audio for item in self.artifacts if item.published_audio]

    @property
    def subtitle_files(self) -> list[Path]:
        return [item.published_subtitle for item in self.artifacts if item.published_subtitle]


def lock_path() -> Path:
    return work_dir() / ".lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_lock() -> Path:
    """Single-flight guard shared by the timer job and the Telegram bot process."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        if holder.isdigit() and _pid_alive(int(holder)):
            raise LessonBusy(f"another lesson run is in progress (pid {holder})")
        logger.warning("Removing stale lesson lock from pid %s", holder or "?")
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return path


def release_lock() -> None:
    lock_path().unlink(missing_ok=True)


def subtitle_timeout() -> int:
    raw = env("DAILY_SUBTITLE_TIMEOUT", "1800") or "1800"
    try:
        return max(60, int(raw))
    except ValueError:
        return 1800


def videosrt_dirs() -> tuple[Path, Path] | None:
    watch_dir = env_path("VIDEOSRT_WATCH_DIR")
    out_dir = env_path("VIDEOSRT_OUT_DIR")
    if not watch_dir or not out_dir:
        return None
    return watch_dir, out_dir


def cleanup_enabled() -> bool:
    value = env("DAILY_CLEANUP", "true") or "true"
    return value.lower() in {"1", "true", "yes", "on"}


def cleanup_intermediates(submitted_name: str, srt_source: Path) -> None:
    """Remove the copies VideoSRT leaves behind once ours are published.

    VideoSRT moves the processed media into out_dir and writes the SRT there, and
    our submitted copy stays in the watch dir. The canonical set now lives in
    DAILY_NAS_DIR, so drop the duplicates — but only the exact filenames this run
    created.
    """
    if not cleanup_enabled():
        return
    dirs = videosrt_dirs()
    if not dirs:
        return
    watch_dir, out_dir = dirs
    for path in (srt_source, out_dir / submitted_name, watch_dir / submitted_name):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove intermediate file: %s", path)


def pending_path() -> Path:
    return work_dir() / "pending_srt.json"


def _load_pending() -> list[dict]:
    path = pending_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _save_pending(entries: list[dict]) -> None:
    path = pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _remember_pending(stem: str, lang: str, submitted_stem: str, submitted_name: str) -> None:
    entries = [
        item
        for item in _load_pending()
        if not (item.get("stem") == stem and item.get("lang") == lang)
    ]
    entries.append(
        {
            "stem": stem,
            "lang": lang,
            "submitted_stem": submitted_stem,
            "submitted_name": submitted_name,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_pending(entries)


async def reconcile_pending(chat_id: int | None = None) -> list[Path]:
    """Publish subtitles that showed up after a previous run gave up waiting."""
    entries = _load_pending()
    dirs = videosrt_dirs()
    if not entries or not dirs:
        return []
    _, out_dir = dirs

    published: list[Path] = []
    remaining: list[dict] = []
    for entry in entries:
        stem = str(entry.get("stem", ""))
        lang = str(entry.get("lang", "ja"))
        submitted = str(entry.get("submitted_stem") or f"{stem}.{lang}")
        found = None
        for name in srt_candidates([submitted, stem], bilingual=True):
            candidate = out_dir / name
            if await asyncio.to_thread(candidate.exists):
                found = candidate
                break
        if found:
            dest = publish_file(found, nas_dir(), f"{stem}.{lang}_bi.srt")
            published.append(dest)
            submitted_name = str(entry.get("submitted_name") or f"{submitted}.mp3")
            cleanup_intermediates(submitted_name, found)
            continue
        created = str(entry.get("created", ""))
        if created and (datetime.now() - datetime.fromisoformat(created)).days >= 7:
            logger.warning("Dropping stale pending subtitle: %s (%s)", stem, lang)
            continue
        remaining.append(entry)

    _save_pending(remaining)
    if published:
        names = ", ".join(path.name for path in published)
        await notify.send_files(
            caption=f"补齐了之前超时的字幕：{names}",
            audio_files=[],
            document_files=published,
            chat_id=chat_id,
        )
    return published


def _voices_for(provider: str, lang: str) -> dict[str, dict[str, str]]:
    voices = default_dialogue_voices(provider)
    if lang == "ja":
        return voices
    if provider == "elevenlabs":
        # ElevenLabs turbo/flash v2.5 are multilingual, so the Japanese voices work
        # for English too unless a dedicated pair is configured.
        voice_a = env(f"ELEVENLABS_VOICE_ID_{lang.upper()}")
        voice_b = env(f"ELEVENLABS_VOICE_ID_{lang.upper()}2") or voice_a
        if voice_a:
            voices["A"]["elevenlabs"] = voice_a
        if voice_b:
            voices["B"]["elevenlabs"] = voice_b
        return voices
    for adapter_key, (default_a, default_b) in EN_VOICE_DEFAULTS.items():
        if adapter_key in voices["A"] or adapter_key in voices["B"]:
            prefix = adapter_key.split("_")[0].upper()
            voices["A"][adapter_key] = env(f"{prefix}_TTS_VOICE_{lang.upper()}_A", default_a) or default_a
            voices["B"][adapter_key] = env(f"{prefix}_TTS_VOICE_{lang.upper()}_B", default_b) or default_b
    return voices


def already_published(date_str: str, langs: tuple[str, ...]) -> bool:
    """True when every language for this date already has audio on the NAS."""
    target = nas_dir()
    if not target.exists():
        return False
    return all(any(target.glob(f"{date_str}_*.{lang}.*")) for lang in langs)


async def _emit(progress: ProgressFn | None, message: str) -> None:
    logger.info(message)
    if progress:
        try:
            await progress(message)
        except Exception:  # noqa: BLE001 - progress reporting must never break the run.
            logger.exception("Progress callback failed")


def pause_ms() -> int:
    """Silence between turns. The script-built SRT timeline depends on this."""
    raw = env("DAILY_PAUSE_MS", "450") or "450"
    try:
        return max(0, int(raw))
    except ValueError:
        return 450


def subtitle_source() -> str:
    """`script` builds SRTs from the text we synthesized; `whisper` uses VideoSRT."""
    value = (env("DAILY_SUBTITLE_SOURCE", "script") or "script").lower()
    return value if value in {"script", "whisper", "none"} else "script"


async def _synthesize(
    lesson: DailyLesson,
    scenario: Scenario,
    lang: str,
    provider: str,
    stem: str,
    day_dir: Path,
    output_format: AudioFormat,
) -> tuple[Path, str]:
    script = lesson_to_script(lesson, lang, _voices_for(provider, lang), pause_ms=pause_ms())
    if not script.turns:
        raise RuntimeError(f"no turns generated for {lang}")
    adapters = build_adapters({provider})
    results = await run_dialogue(
        adapters=adapters,
        script=script,
        output_dir=day_dir / lang,
        output_format=output_format,
        reference_video=env_path("TTS_REFERENCE_VIDEO", "ref_japanese.mp4"),
        output_stem=stem,
        voice_settings_override=voice_settings_for_register(scenario.register),
        language=lang,
    )
    result = results[0]
    if not result.ok or not result.output_path:
        raise RuntimeError(result.error or "dialogue synthesis failed")
    return result.output_path, adapters[0].name


async def _build_script_subtitles(
    lesson: DailyLesson,
    artifacts: list[LangArtifact],
    stem: str,
    day_dir: Path,
    output_format: AudioFormat,
    pause_ms: int,
) -> None:
    for artifact in artifacts:
        if not artifact.audio or not artifact.adapter_name:
            continue
        try:
            content = await script_srt(
                lesson=lesson,
                lang=artifact.lang,
                output_dir=day_dir / artifact.lang,
                adapter_name=artifact.adapter_name,
                output_format=output_format,
                pause_ms=pause_ms,
                merged_audio=artifact.audio,
            )
        except SegmentTimingError as exc:
            logger.warning("Script subtitle failed for %s (%s): %s", stem, artifact.lang, exc)
            continue
        local = day_dir / artifact.lang / f"{stem}.{artifact.lang}_bi.srt"
        local.write_text(content, encoding="utf-8")
        artifact.subtitle = local
        artifact.published_subtitle = publish_file(
            local, nas_dir(), f"{stem}.{artifact.lang}_bi.srt"
        )


async def run_lesson(
    scenario: Scenario | None = None,
    langs: tuple[str, ...] = ("ja", "en"),
    provider: str | None = None,
    stem_suffix: str | None = None,
    wait_subtitles: bool = True,
    progress: ProgressFn | None = None,
    date: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    trigger: str = "scheduled",
    notify_chat_id: int | None = None,
    push: bool = True,
) -> LessonResult:
    """Generate one bilingual lesson end to end. Shared by the CLI and the bot."""
    provider = provider or env("DEFAULT_TTS_PROVIDER", "elevenlabs") or "elevenlabs"
    output_format = output_format_from_env()
    date_str = date or datetime.now().strftime("%Y%m%d")

    if not force and not dry_run and stem_suffix is None and already_published(date_str, langs):
        raise LessonSkipped(f"{date_str} already published in {nas_dir()}")

    acquire_lock()
    try:
        await reconcile_pending(chat_id=notify_chat_id)

        state = load_state()
        from_library = scenario is None
        if scenario is None:
            scenario = next_scenario(state)
        await _emit(progress, f"已选场景：{scenario.title}（{scenario.category}）")

        generator = GeminiLessonGenerator()
        lesson = await generator.generate(scenario)
        stem = f"{date_str}_{lesson.topic_slug}"
        if stem_suffix:
            stem = f"{stem}_{stem_suffix}"
        await _emit(progress, f"文稿生成完成：{lesson.title_ja}（{stem}）")

        day_dir = work_dir() / date_str
        day_dir.mkdir(parents=True, exist_ok=True)
        result = LessonResult(stem=stem, scenario=scenario, lesson=lesson, dry_run=dry_run)

        script_md = script_markdown(scenario, lesson, stem)
        meta_json = lesson_to_json(
            scenario,
            lesson,
            {
                "stem": stem,
                "date": date_str,
                "provider": provider,
                "langs": list(langs),
                "trigger": trigger,
            },
        )
        if dry_run:
            result.script_path = write_text_file(script_md, day_dir, f"{stem}.md")
            result.meta_path = write_text_file(meta_json, day_dir, f"{stem}.json")
            await _emit(progress, "dry-run：仅生成文稿，未调用 TTS")
            return result

        artifacts = [LangArtifact(lang=lang) for lang in langs]
        for artifact in artifacts:
            try:
                artifact.audio, artifact.adapter_name = await _synthesize(
                    lesson, scenario, artifact.lang, provider, stem, day_dir, output_format
                )
                artifact.published_audio = publish_file(
                    artifact.audio, nas_dir(), f"{stem}.{artifact.lang}{artifact.audio.suffix}"
                )
            except Exception as exc:  # noqa: BLE001 - one language must not kill the other.
                artifact.error = f"{type(exc).__name__}: {exc}"
                logger.exception("Synthesis failed for %s (%s)", stem, artifact.lang)
        result.artifacts = artifacts
        done = [item.lang for item in artifacts if item.published_audio]
        await _emit(progress, f"音频合成完成：{'、'.join(done) or '无'}")

        result.script_path = write_text_file(script_md, nas_dir(), f"{stem}.md")
        result.meta_path = write_text_file(meta_json, nas_dir(), f"{stem}.json")

        source = subtitle_source() if wait_subtitles else "none"
        if source == "script":
            await _build_script_subtitles(
                lesson, artifacts, stem, day_dir, output_format, pause_ms()
            )
            ready = [item.lang for item in artifacts if item.published_subtitle]
            await _emit(progress, f"字幕生成完成（原文タイムライン）：{'、'.join(ready) or '失败'}")

        dirs = videosrt_dirs()
        if dirs and source == "whisper":
            watch_dir, out_dir = dirs
            submitted: list[tuple[LangArtifact, Path]] = []
            for artifact in artifacts:
                if not artifact.audio:
                    continue
                dest = await submit_to_watch_dir(artifact.audio, watch_dir, artifact.lang)
                submitted.append((artifact, dest))
            if submitted:
                await _emit(progress, "已投递字幕，等待 VideoSRT 处理…")
                waits = [
                    wait_for_subtitle(
                        audio_stem=[dest.stem, stem],
                        out_dir=out_dir,
                        timeout=subtitle_timeout(),
                    )
                    for _, dest in submitted
                ]
                found = await asyncio.gather(*waits)
                for (artifact, dest), srt in zip(submitted, found):
                    if srt:
                        artifact.subtitle = srt
                        artifact.published_subtitle = publish_file(
                            srt, nas_dir(), f"{stem}.{artifact.lang}_bi.srt"
                        )
                        cleanup_intermediates(dest.name, srt)
                    else:
                        _remember_pending(stem, artifact.lang, dest.stem, dest.name)
                ready = [item.lang for item in artifacts if item.published_subtitle]
                await _emit(progress, f"字幕完成：{'、'.join(ready) or '暂无（已登记待补）'}")

        if from_library and scenario.source == "library":
            save_state(mark_used(state, scenario, date_str, stem))
        append_history(
            {
                "date": date_str,
                "stem": stem,
                "scenario_id": scenario.id,
                "trigger": trigger,
                "provider": provider,
                "langs": list(langs),
                "ok": result.ok,
            }
        )

        if push:
            errors = [f"{item.lang}: {item.error}" for item in artifacts if item.error]
            caption = (
                f"📦 {lesson.title_ja}\n"
                f"🏷 {scenario.title}（{scenario.category}）\n"
                f"📝 {lesson.summary_zh}\n"
                f"🗂 {stem}"
            )
            if errors:
                caption += "\n⚠️ " + "；".join(errors)
            documents = list(result.subtitle_files)
            if result.script_path:
                documents.append(result.script_path)
            await notify.send_files(
                caption=caption,
                audio_files=result.audio_files,
                document_files=documents,
                chat_id=notify_chat_id,
            )
        await _emit(progress, "完成")
        return result
    finally:
        release_lock()
