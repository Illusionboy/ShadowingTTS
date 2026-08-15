from __future__ import annotations

import logging
from pathlib import Path

from ..config import env

logger = logging.getLogger(__name__)


def default_chat_id() -> int | None:
    raw = env("DAILY_PUSH_CHAT_ID") or ""
    if raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            logger.warning("Invalid DAILY_PUSH_CHAT_ID=%s", raw)
    allowed = env("TELEGRAM_ALLOWED_USER_IDS", "") or ""
    for item in allowed.split(","):
        item = item.strip()
        if item:
            try:
                return int(item)
            except ValueError:
                continue
    return None


def _bot():
    from telegram import Bot

    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    return Bot(token=token)


async def send_text(text: str, chat_id: int | None = None) -> None:
    chat_id = chat_id or default_chat_id()
    bot = _bot()
    if not bot or not chat_id:
        logger.info("Telegram push skipped (no token or chat id): %s", text)
        return
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text)


async def send_files(
    caption: str,
    audio_files: list[Path],
    document_files: list[Path],
    chat_id: int | None = None,
) -> None:
    chat_id = chat_id or default_chat_id()
    bot = _bot()
    if not bot or not chat_id:
        logger.info("Telegram push skipped (no token or chat id): %s", caption)
        return
    async with bot:
        await bot.send_message(chat_id=chat_id, text=caption)
        for path in audio_files:
            with path.open("rb") as handle:
                await bot.send_audio(chat_id=chat_id, audio=handle, filename=path.name)
        for path in document_files:
            with path.open("rb") as handle:
                await bot.send_document(chat_id=chat_id, document=handle, filename=path.name)
