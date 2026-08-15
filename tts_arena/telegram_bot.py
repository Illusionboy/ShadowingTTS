from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import env, env_path, load_environment, required_env
from .daily.generator import GeminiLessonGenerator
from .daily.job import LessonBusy, LessonSkipped, run_lesson
from .daily.scenarios import (
    Scenario,
    adhoc_limit,
    adhoc_runs_today,
    find_scenario,
    load_categories,
    load_scenarios,
)
from .gemini_normalizer import dialogue_to_json
from .pipeline import synthesize_user_dialogue
from .subtitle import submit_and_wait


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


HELP_TEXT = (
    "シャドーイング素材にしたい文章を送ってください。\n"
    "その後、言語と形式をボタンで選べます。\n\n"
    "例:\n"
    "A: すみません、この電車は新宿まで行きますか。\n"
    "B: はい、行きます。\n\n"
    "物流／SCM 教材（日英セット、字幕付きで NAS 保存）:\n"
    "/daily 今すぐ1本生成\n"
    "/scene <場面の説明> 自分で場面を書いて生成\n"
    "/scenes シナリオ一覧　/pick <id> 指定して生成"
)

LESSON_LANG_SETS = {
    "both": ("ja", "en"),
    "ja": ("ja",),
    "en": ("en",),
}

LANGUAGES = {
    "ja": "日本語",
    "en": "English",
    "zh": "中文",
    "ko": "한국어",
}

MODES = {
    "dialogue": "对话",
    "monologue": "独白",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not await ensure_authorized(update):
        return
    if update.message:
        await update.message.reply_text(HELP_TEXT)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return
    if not update.message or not update.message.text:
        return

    max_length = telegram_max_text_length()
    if len(update.message.text) > max_length:
        await update.message.reply_text(f"文本太长了。请控制在 {max_length} 字以内。")
        return

    if context.user_data.pop("pending_action", None) == "scene":
        await draft_scene_and_prompt(update, context, update.message.text)
        return

    context.user_data["pending_text"] = update.message.text
    context.user_data.pop("language", None)
    context.user_data.pop("mode", None)
    await update.message.reply_text(
        "请选择语言 / 言語を選んでください",
        reply_markup=language_keyboard(),
    )


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    action, value = query.data.split(":", 1)
    if action == "lang":
        context.user_data["language"] = value
        await query.edit_message_text(
            f"语言：{LANGUAGES.get(value, value)}\n请选择形式",
            reply_markup=mode_keyboard(),
        )
        return

    if action == "mode":
        context.user_data["mode"] = value
        await query.edit_message_text(
            f"已选择：{LANGUAGES.get(context.user_data.get('language', 'ja'), '日本語')} / {MODES.get(value, value)}"
        )
        await process_pending_request(update, context)
        return

    if action == "lesson":
        request = context.user_data.pop("pending_lesson", None)
        if request is None:
            await query.edit_message_text("请求已过期，请重新发送 /daily 或 /scene。")
            return
        langs = LESSON_LANG_SETS.get(value, ("ja", "en"))
        label = request.get("label", "教材")
        await query.edit_message_text(f"{label}\n语言：{' + '.join(langs)}\n开始生成…")
        chat_id = query.message.chat_id if query.message else None
        asyncio.create_task(
            run_lesson_task(query.message, request.get("scenario"), langs, chat_id)
        )


async def process_pending_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    message = query.message if query else update.message
    if not message:
        return

    user_text = context.user_data.get("pending_text")
    if not user_text:
        await message.reply_text("没有找到待处理文本，请重新发送。")
        return

    language = context.user_data.get("language", "ja")
    mode = context.user_data.get("mode", "dialogue")
    status = await message.reply_text("正在整理文本并生成音频...")
    try:
        script, result = await synthesize_user_dialogue(
            user_text,
            language=language,
            mode=mode,
        )
        if not result.ok or not result.output_path:
            logger.error("TTS generation failed: %s", result.error)
            await status.edit_text("TTS 生成失败，请稍后重试或联系管理员。")
            return

        await status.edit_text("生成完成，正在发送音频。")
        if telegram_debug_reply_json():
            await message.reply_text(
                f"结构化JSON:\n```json\n{dialogue_to_json(script)}\n```",
                parse_mode="Markdown",
            )
        audio_filename = f"{result.output_path.stem}.{language}{result.output_path.suffix}"
        with result.output_path.open("rb") as audio:
            await message.reply_audio(audio=audio, filename=audio_filename)
        context.user_data.pop("pending_text", None)

        if _videosrt_configured():
            asyncio.create_task(
                _send_subtitle_when_ready(message, result.output_path, language)
            )
    except Exception as exc:  # noqa: BLE001 - keep bot alive and report user-facing failure.
        logger.exception("Telegram TTS request failed")
        await status.edit_text("处理失败，请稍后重试或联系管理员。")


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return
    await prompt_lesson_langs(update, context, scenario=None, label="今日のローテーションから1本")


async def pick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return
    if not update.message:
        return
    scenario_id = context.args[0] if context.args else ""
    scenario = find_scenario(scenario_id) if scenario_id else None
    if not scenario:
        await update.message.reply_text("用法：/pick <场景id>。可用 /scenes 查看列表。")
        return
    await prompt_lesson_langs(update, context, scenario=scenario, label=scenario.title)


async def scenes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not await ensure_authorized(update):
        return
    if not update.message:
        return
    categories = load_categories()
    scenarios = load_scenarios()
    lines: list[str] = []
    for key, label in categories.items():
        lines.append(f"\n【{label}】")
        lines += [f"{item.id} — {item.title}" for item in scenarios if item.category == key]
    lines.append("\n/pick <id> で指定生成、/daily でローテーション生成。")
    await update.message.reply_text("\n".join(lines).strip())


async def scene_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return
    if not update.message:
        return
    scene_text = " ".join(context.args).strip() if context.args else ""
    if not scene_text:
        context.user_data["pending_action"] = "scene"
        await update.message.reply_text(
            "请把场景描述发过来，例如：\n"
            "客户投诉上周那批货托盘破损，要求赔偿和再发"
        )
        return
    await draft_scene_and_prompt(update, context, scene_text)


async def draft_scene_and_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, scene_text: str
) -> None:
    message = update.message
    if not message:
        return
    status = await message.reply_text("正在整理场景设定…")
    try:
        scenario = await GeminiLessonGenerator().draft_scenario(scene_text)
    except Exception:  # noqa: BLE001 - keep the bot alive, report to the user.
        logger.exception("Scene drafting failed")
        await status.edit_text("场景整理失败，请稍后重试或换个说法。")
        return

    detail = (
        f"场景：{scenario.title}\n"
        f"A：{scenario.role_a}\n"
        f"B：{scenario.role_b}\n"
        f"目标：{scenario.goal}\n"
        f"用语：{'、'.join(scenario.terms) or '-'}"
    )
    if scenario.off_domain:
        detail += "\n（注：这个场景与物流/SCM 关系不大，仍会生成）"
    await status.edit_text(detail)
    await prompt_lesson_langs(update, context, scenario=scenario, label=scenario.title)


async def prompt_lesson_langs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    scenario: Scenario | None,
    label: str,
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return
    context.user_data["pending_lesson"] = {"scenario": scenario, "label": label}
    await message.reply_text("生成する言語を選んでください", reply_markup=lesson_keyboard())


async def run_lesson_task(message, scenario: Scenario | None, langs: tuple[str, ...], chat_id) -> None:
    status = await message.reply_text("准备中…")

    async def progress(text: str) -> None:
        try:
            await status.edit_text(text)
        except Exception:  # noqa: BLE001 - a failed status edit must not abort the run.
            logger.debug("Status edit failed", exc_info=True)

    limit = adhoc_limit()
    today = datetime.now().strftime("%Y%m%d")
    if limit and adhoc_runs_today(today) >= limit:
        await status.edit_text(f"今天的手动生成已达上限（{limit} 次）。明天再来，或调大 DAILY_ADHOC_LIMIT。")
        return

    try:
        await run_lesson(
            scenario=scenario,
            langs=langs,
            stem_suffix=datetime.now().strftime("%H%M"),
            progress=progress,
            trigger="adhoc",
            notify_chat_id=chat_id,
            force=True,
        )
    except LessonBusy:
        await status.edit_text("现在有另一个生成任务在跑，稍等一会儿再试。")
    except LessonSkipped as exc:
        await status.edit_text(f"已跳过：{exc}")
    except Exception:  # noqa: BLE001 - keep bot alive and report user-facing failure.
        logger.exception("Ad-hoc lesson failed")
        await status.edit_text("生成失败，请查看服务器日志（journalctl -u shadowingtts）。")


def lesson_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("日英セット", callback_data="lesson:both"),
                InlineKeyboardButton("日本語のみ", callback_data="lesson:ja"),
                InlineKeyboardButton("English only", callback_data="lesson:en"),
            ]
        ]
    )


def _videosrt_configured() -> bool:
    return bool(env_path("VIDEOSRT_WATCH_DIR") and env_path("VIDEOSRT_OUT_DIR"))


async def _send_subtitle_when_ready(message, audio_path, language: str) -> None:
    watch_dir = env_path("VIDEOSRT_WATCH_DIR")
    out_dir = env_path("VIDEOSRT_OUT_DIR")
    if not watch_dir or not out_dir:
        return
    timeout = int(env("VIDEOSRT_TIMEOUT", "600") or "600")
    try:
        srt_path = await submit_and_wait(
            audio_path=audio_path,
            watch_dir=watch_dir,
            out_dir=out_dir,
            lang=language,
            bilingual=True,
            timeout=timeout,
        )
        if srt_path:
            with srt_path.open("rb") as f:
                await message.reply_document(document=f, filename=srt_path.name, caption="双语字幕")
        else:
            logger.warning("VideoSRT timed out for %s", audio_path.name)
    except Exception:
        logger.exception("VideoSRT background task failed for %s", audio_path.name)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("日本語", callback_data="lang:ja"),
                InlineKeyboardButton("English", callback_data="lang:en"),
            ],
            [
                InlineKeyboardButton("中文", callback_data="lang:zh"),
                InlineKeyboardButton("한국어", callback_data="lang:ko"),
            ],
        ]
    )


def mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("对话", callback_data="mode:dialogue"),
                InlineKeyboardButton("独白", callback_data="mode:monologue"),
            ]
        ]
    )


async def ensure_authorized(update: Update) -> bool:
    allowed_user_ids = telegram_allowed_user_ids()
    if not allowed_user_ids:
        logger.warning("TELEGRAM_ALLOWED_USER_IDS is empty; allowing request")
        return True

    user = update.effective_user
    if user and user.id in allowed_user_ids:
        return True

    logger.warning("Unauthorized Telegram access from user_id=%s", user.id if user else None)
    if update.callback_query:
        await update.callback_query.answer("Unauthorized.", show_alert=True)
    elif update.message:
        await update.message.reply_text("Unauthorized.")
    return False


def telegram_allowed_user_ids() -> set[int]:
    raw = env("TELEGRAM_ALLOWED_USER_IDS", "") or ""
    user_ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            user_ids.add(int(item))
        except ValueError:
            logger.warning("Ignoring invalid TELEGRAM_ALLOWED_USER_IDS item: %s", item)
    return user_ids


def telegram_max_text_length() -> int:
    raw = env("TELEGRAM_MAX_TEXT_LENGTH", "2000") or "2000"
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid TELEGRAM_MAX_TEXT_LENGTH=%s; using 2000", raw)
        return 2000


def telegram_debug_reply_json() -> bool:
    value = env("TELEGRAM_DEBUG_REPLY_JSON", "false") or "false"
    return value.lower() in {"1", "true", "yes", "on"}


def main() -> None:
    load_environment()
    token = required_env("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("scene", scene_command))
    app.add_handler(CommandHandler("scenes", scenes_command))
    app.add_handler(CommandHandler("pick", pick_command))
    app.add_handler(CallbackQueryHandler(handle_choice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
