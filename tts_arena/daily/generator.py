from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, Field

from ..config import env, required_env
from ..dialogue import DialogueScript, DialogueTurn
from ..gemini_normalizer import _sanitize_slug
from .scenarios import Scenario, glossary_for, load_categories


LANGUAGE_LABELS = {"ja": "日本語", "en": "英語"}


class LessonTurn(BaseModel):
    speaker: Literal["A", "B"] = Field(description="Speaker label, alternating A and B.")
    text: str = Field(description="One utterance to synthesize, no annotations.")


class GlossaryEntry(BaseModel):
    term_ja: str = Field(description="Japanese term as used in the dialogue.")
    reading: str = Field(description="Kana reading of the Japanese term.")
    term_en: str = Field(description="English equivalent as used in the English dialogue.")
    term_zh: str = Field(description="Chinese equivalent for the learner.")
    note: str = Field(description="One short usage note in Chinese.")


class DailyLesson(BaseModel):
    topic_slug: str = Field(
        description=(
            "2-3 word English snake_case label, max 30 chars, describing the scenario. "
            "Examples: 'mis_shipment_claim', 'annual_rate_review'."
        )
    )
    title_ja: str = Field(description="Japanese title of the scene.")
    title_en: str = Field(description="English title of the scene.")
    summary_zh: str = Field(description="One-sentence Chinese summary of what happens.")
    ja_turns: list[LessonTurn] = Field(description="Japanese dialogue turns.")
    en_turns: list[LessonTurn] = Field(description="English dialogue turns for the same situation.")
    glossary: list[GlossaryEntry] = Field(description="Key logistics terms used in the dialogue.")


class ScenarioDraft(BaseModel):
    title: str = Field(description="Japanese title of the scene.")
    category: str = Field(
        description=(
            "One of: daily_ops, reporting, customer, supplier, incident, negotiation."
        )
    )
    speech_register: Literal["formal", "casual"] = Field(
        description="formal for business/keigo settings, casual for warehouse floor talk."
    )
    role_a: str = Field(description="Who speaker A is.")
    role_b: str = Field(description="Who speaker B is.")
    goal: str = Field(description="What the conversation must accomplish, in Chinese.")
    terms: list[str] = Field(description="3-6 Japanese domain terms the dialogue should use.")
    off_domain: bool = Field(
        description="True if the request is unrelated to logistics / SCM / warehouse work."
    )


def turn_count() -> int:
    raw = env("DAILY_TURNS", "10") or "10"
    try:
        return max(4, min(20, int(raw)))
    except ValueError:
        return 10


def _glossary_block(scenario: Scenario) -> str:
    entries = glossary_for(scenario.category)
    lines = [f"- {item['ja']}（{item['reading']}）= {item['en']} / {item['zh']}" for item in entries]
    if scenario.terms:
        lines.append("必ず使う語: " + "、".join(scenario.terms))
    return "\n".join(lines)


class GeminiLessonGenerator:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or required_env("GEMINI_API_KEY")
        self.model = model or env("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"

    async def generate(self, scenario: Scenario, turns: int | None = None) -> DailyLesson:
        return await asyncio.to_thread(self._sync_generate, scenario, turns or turn_count())

    async def draft_scenario(self, user_text: str) -> Scenario:
        return await asyncio.to_thread(self._sync_draft_scenario, user_text)

    def _client(self):
        from google import genai

        return genai.Client(api_key=self.api_key)

    def _sync_generate(self, scenario: Scenario, turns: int) -> DailyLesson:
        register_ja = (
            "商談・報告にふさわしい丁寧な敬語（です・ます、謙譲語・尊敬語）"
            if scenario.register == "formal"
            else "現場で実際に使うくだけた口調（丁寧すぎない、短く速い）"
        )
        prompt = (
            "あなたは第三者物流（3PL）／SCM／倉庫管理の現場を熟知した語学教材の編集者です。\n"
            "以下のシーンについて、日本語版と英語版の会話教材を作ってください。\n\n"
            "【シーン】\n"
            f"タイトル: {scenario.title}\n"
            f"カテゴリ: {scenario.category}\n"
            f"A の役割: {scenario.role_a}\n"
            f"B の役割: {scenario.role_b}\n"
            f"会話のゴール: {scenario.goal}\n\n"
            "【使ってほしい業務用語】\n"
            f"{_glossary_block(scenario)}\n\n"
            "【厳守ルール】\n"
            f"1. ja_turns は{turns}前後のターン、A と B が交互に話す。en_turns も同じ人数・同じ流れ。\n"
            "2. en_turns は ja_turns の逐語訳ではなく、同じ状況で英語話者が実際に言う自然な言い方にする。"
            "ただし扱う事実・数字・結論・合意事項は日英で完全に一致させる。\n"
            f"3. 日本語の語調は{register_ja}。英語も同じ丁寧さのレベルに合わせる。\n"
            "4. text フィールドには解説・注釈・括弧書き・話者名を入れない。発話そのものだけ。\n"
            "5. 一発話は音読しやすい長さ（日本語は40〜70字程度）に収める。\n"
            "6. 数字・日付・便名などは具体的に入れて、実務の会話らしくする。"
            "「〇月」「××社」のようなプレースホルダーは禁止。実在しそうな値を書く。\n"
            "7. 日本語のターンでは英字コードをそのまま書かない。音声合成が正しく読めるよう、"
            "型番・便名はカタカナ＋数字で書く（例: AS987便 →「エーエス987便」、SKU P001 →「品番ピー001」）。"
            "英語のターンでは AS987 / SKU P001 のように通常表記でよい。\n"
            "8. 日本語は音読して意味が取れる標準的な言い回しにし、難読漢字や紛らわしい同音語は避ける。\n"
            "9. glossary は実際に会話で使った用語から5〜8件選ぶ。\n"
        )
        client = self._client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": DailyLesson,
            },
        )
        parsed = response.parsed
        if parsed is None:
            parsed = DailyLesson.model_validate_json(response.text)
        return parsed.model_copy(update={"topic_slug": _sanitize_slug(parsed.topic_slug)})

    def _sync_draft_scenario(self, user_text: str) -> Scenario:
        categories = load_categories()
        category_lines = "\n".join(f"- {key}: {label}" for key, label in categories.items())
        prompt = (
            "あなたは第三者物流（3PL）／SCM／倉庫管理の実務に詳しい教材設計者です。\n"
            "ユーザーが書いた場面のメモを、会話教材を作るための構造化された設定に整えてください。\n\n"
            "【カテゴリ候補】\n"
            f"{category_lines}\n\n"
            "【ルール】\n"
            "1. role_a / role_b は誰と誰の会話かを具体的に書く（例: 顧客側購買担当 / 3PL specialist）。\n"
            "2. goal は中国語で1文。この会話で何を達成するかを書く。\n"
            "3. terms は会話で使うべき日本語の業務用語を3〜6語。\n"
            "4. メモが物流・SCM・倉庫と無関係なら off_domain を true にし、それでも設定は作る。\n"
            "5. メモが曖昧なら実務で最もありがちな状況として具体化する。\n\n"
            f"ユーザーのメモ:\n{user_text}"
        )
        client = self._client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": ScenarioDraft,
            },
        )
        parsed = response.parsed
        if parsed is None:
            parsed = ScenarioDraft.model_validate_json(response.text)
        category = parsed.category if parsed.category in categories else "customer"
        return Scenario(
            id=f"custom_{_sanitize_slug(parsed.title) or category}",
            category=category,
            register=parsed.speech_register,
            title=parsed.title,
            roles={"A": parsed.role_a, "B": parsed.role_b},
            goal=parsed.goal,
            terms=list(parsed.terms),
            source="custom",
            off_domain=parsed.off_domain,
        )


def lesson_turns(lesson: DailyLesson, lang: str) -> list[LessonTurn]:
    return lesson.ja_turns if lang == "ja" else lesson.en_turns


def lesson_to_script(
    lesson: DailyLesson,
    lang: str,
    voices: dict[str, dict[str, str]],
    pause_ms: int = 450,
) -> DialogueScript:
    return DialogueScript(
        turns=[DialogueTurn(speaker=item.speaker, text=item.text) for item in lesson_turns(lesson, lang)],
        voices=voices,
        pause_ms=pause_ms,
        topic_slug=lesson.topic_slug,
    )


def lesson_to_json(scenario: Scenario, lesson: DailyLesson, extra: dict | None = None) -> str:
    payload = {
        "scenario": {
            "id": scenario.id,
            "category": scenario.category,
            "register": scenario.register,
            "title": scenario.title,
            "roles": scenario.roles,
            "goal": scenario.goal,
            "terms": scenario.terms,
            "source": scenario.source,
            "off_domain": scenario.off_domain,
        },
        "lesson": lesson.model_dump(),
        **(extra or {}),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
