from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .generator import DailyLesson, lesson_turns
from .scenarios import Scenario

logger = logging.getLogger(__name__)


def publish_file(src: Path, dest_dir: Path, dest_name: str) -> Path:
    """Copy src into dest_dir as dest_name, atomically.

    ShadowReader scans this directory, so a half-written file must never carry
    the final name: copy to a temp name in the same directory, then rename.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    tmp = dest_dir / f".{dest_name}.part"
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)
    logger.info("Published: %s", dest)
    return dest


def write_text_file(content: str, dest_dir: Path, dest_name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    tmp = dest_dir / f".{dest_name}.part"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def script_markdown(scenario: Scenario, lesson: DailyLesson, stem: str) -> str:
    ja = lesson_turns(lesson, "ja")
    en = lesson_turns(lesson, "en")
    lines = [
        f"# {lesson.title_ja}",
        "",
        f"- 英文标题：{lesson.title_en}",
        f"- 场景：{scenario.title}（{scenario.category} / {scenario.register}）",
        f"- 角色：A = {scenario.role_a}／B = {scenario.role_b}",
        f"- 目标：{scenario.goal}",
        f"- 摘要：{lesson.summary_zh}",
        f"- 文件前缀：`{stem}`",
        "",
        "## 日本語",
        "",
    ]
    lines += [f"**{turn.speaker}**: {turn.text}" for turn in ja]
    lines += ["", "## English", ""]
    lines += [f"**{turn.speaker}**: {turn.text}" for turn in en]

    if len(ja) == len(en):
        lines += ["", "## 対訳 / Side by side", "", "| # | 日本語 | English |", "| --- | --- | --- |"]
        for index, (ja_turn, en_turn) in enumerate(zip(ja, en), start=1):
            lines.append(
                f"| {index} | {ja_turn.speaker}: {ja_turn.text} | {en_turn.speaker}: {en_turn.text} |"
            )

    if lesson.glossary:
        lines += [
            "",
            "## 用語 / Glossary",
            "",
            "| 日本語 | 読み | English | 中文 | 备注 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in lesson.glossary:
            lines.append(
                f"| {item.term_ja} | {item.reading} | {item.term_en} | {item.term_zh} | {item.note} |"
            )
    return "\n".join(lines) + "\n"
