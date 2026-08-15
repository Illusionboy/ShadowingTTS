from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ..config import load_environment
from .generator import GeminiLessonGenerator
from .job import LessonBusy, LessonSkipped, run_lesson
from .scenarios import find_scenario, load_categories, load_scenarios


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tts_arena.daily")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily 3PL/SCM bilingual shadowing lesson.")
    parser.add_argument("--date", help="YYYYMMDD, defaults to today.")
    parser.add_argument("--scenario", help="Scenario id from the library.")
    parser.add_argument("--scene-text", help="Free-form scene description; Gemini drafts the setup.")
    parser.add_argument("--provider", help="TTS provider alias, defaults to DEFAULT_TTS_PROVIDER.")
    parser.add_argument("--langs", default="ja,en", help="Comma-separated languages.")
    parser.add_argument("--stem-suffix", help="Extra stem suffix for ad-hoc runs.")
    parser.add_argument("--force", action="store_true", help="Run even if today is published.")
    parser.add_argument("--dry-run", action="store_true", help="Generate the script only.")
    parser.add_argument("--skip-subtitles", action="store_true", help="Do not submit to VideoSRT.")
    parser.add_argument("--no-push", action="store_true", help="Do not push to Telegram.")
    parser.add_argument("--list-scenarios", action="store_true", help="Print the scenario library.")
    return parser.parse_args()


def print_scenarios() -> None:
    categories = load_categories()
    scenarios = load_scenarios()
    for key, label in categories.items():
        print(f"\n[{key}] {label}")
        for scenario in scenarios:
            if scenario.category == key:
                print(f"  {scenario.id:34s} {scenario.title}")


async def main_async() -> int:
    load_environment()
    args = parse_args()

    if args.list_scenarios:
        print_scenarios()
        return 0

    scenario = None
    if args.scenario:
        scenario = find_scenario(args.scenario)
        if not scenario:
            print(f"Unknown scenario id: {args.scenario}", file=sys.stderr)
            return 2
    elif args.scene_text:
        scenario = await GeminiLessonGenerator().draft_scenario(args.scene_text)

    langs = tuple(item.strip() for item in args.langs.split(",") if item.strip())
    try:
        result = await run_lesson(
            scenario=scenario,
            langs=langs,
            provider=args.provider,
            stem_suffix=args.stem_suffix,
            wait_subtitles=not args.skip_subtitles,
            date=args.date,
            dry_run=args.dry_run,
            force=args.force,
            # "adhoc" is reserved for Telegram-triggered runs, which are the ones
            # DAILY_ADHOC_LIMIT is meant to cap.
            trigger="manual" if (args.scenario or args.scene_text) else "scheduled",
            push=not args.no_push,
        )
    except LessonSkipped as exc:
        logger.info("Skipped: %s", exc)
        return 0
    except LessonBusy as exc:
        logger.warning("Busy: %s", exc)
        return 75

    print(f"\n{result.lesson.title_ja} / {result.lesson.title_en}")
    print(f"stem: {result.stem}")
    for artifact in result.artifacts:
        status = artifact.error or (str(artifact.published_audio) if artifact.published_audio else "-")
        srt = str(artifact.published_subtitle) if artifact.published_subtitle else "pending"
        print(f"  {artifact.lang}: {status} | srt: {srt}")
    if result.script_path:
        print(f"script: {result.script_path}")
    return 0 if result.ok else 1


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
