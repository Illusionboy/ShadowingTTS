from __future__ import annotations

import asyncio
import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from .dialogue import DialogueScript, DialogueTurn


class NormalizedTurn(BaseModel):
    speaker: Literal["A", "B"] = Field(description="Speaker label, alternating A and B.")
    text: str = Field(description="Natural Japanese utterance to synthesize.")


class NormalizedDialogue(BaseModel):
    turns: list[NormalizedTurn] = Field(description="Two-person dialogue turns.")


class GeminiDialogueNormalizer:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model = model

    async def normalize(
        self,
        user_text: str,
        language: str = "ja",
        mode: str = "dialogue",
    ) -> DialogueScript:
        return await asyncio.to_thread(self._sync_normalize, user_text, language, mode)

    def _sync_normalize(
        self,
        user_text: str,
        language: str = "ja",
        mode: str = "dialogue",
    ) -> DialogueScript:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        language_name = language_label(language)
        task = (
            "自然な二人会話に整形してください。出力はA/Bのturnsにしてください。"
            if mode == "dialogue"
            else "自然な一人の独白・読み上げ教材に整形してください。出力はspeaker Aのみのturnsにしてください。"
        )
        form = "会話" if mode == "dialogue" else "読み上げ"
        prompt = (
            f"あなたは{language_name}シャドーイング教材の編集者です。\n"
            f"ユーザー入力を{language_name}の自然な{form}教材に変換してください。\n\n"
            "【厳守ルール】\n"
            f"1. 出力の text フィールドは{language_name}のみ。中国語・日本語解説・注釈・括弧書きは一切含めない。\n"
            "2. ユーザーが話題やシナリオを中国語等で提示した場合、そのテーマで新しい自然な文を生成する。\n"
            "3. 既に A:/B: 形式の場合は意味を変えずに整える。\n"
            "4. 一文が長い場合は音声練習しやすい短めの発話に分ける。\n"
            "5. 学習者向けなので自然な表現にする（不自然な直訳禁止）。\n\n"
            f"形式: {task}\n\n"
            f"ユーザー入力:\n{user_text}"
        )
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": NormalizedDialogue,
            },
        )
        parsed = response.parsed
        if parsed is None:
            parsed = NormalizedDialogue.model_validate_json(response.text)
        return DialogueScript(
            turns=[DialogueTurn(speaker=item.speaker, text=item.text) for item in parsed.turns],
            voices={},
        )


def language_label(language: str) -> str:
    labels = {
        "ja": "日本語",
        "en": "英語",
        "zh": "中国語",
        "ko": "韓国語",
    }
    return labels.get(language, language)


def normalize_without_llm(user_text: str, mode: str = "dialogue") -> DialogueScript:
    """Small fallback parser for A:/B: scripts and plain text."""
    turns: list[DialogueTurn] = []
    for raw_line in user_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([ABab])[:：]\s*(.+)$", line)
        if match:
            turns.append(DialogueTurn(speaker=match.group(1).upper(), text=match.group(2).strip()))
        else:
            speaker = "A" if mode == "monologue" else ("A" if len(turns) % 2 == 0 else "B")
            turns.append(DialogueTurn(speaker=speaker, text=line))

    if not turns:
        turns = [DialogueTurn(speaker="A", text=user_text.strip())]
    return DialogueScript(turns=turns, voices={})


def dialogue_to_json(script: DialogueScript) -> str:
    payload = {
        "pause_ms": script.pause_ms,
        "turns": [
            {"speaker": turn.speaker, "text": turn.text}
            for turn in script.turns
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
