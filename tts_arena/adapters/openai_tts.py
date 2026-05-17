from __future__ import annotations

import httpx

from ..base import TTSAdapter, TTSRequest, TTSResult


class OpenAITTSAdapter(TTSAdapter):
    name = "OpenAI TTS"

    def __init__(
        self,
        api_key: str,
        model: str = "tts-1-hd",
        voice: str = "alloy",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        output_path = self.output_path(request)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "voice": request.voice or self.voice,
                    "input": request.text,
                    "response_format": request.output_format,
                },
            )
            response.raise_for_status()
        output_path.write_bytes(response.content)
        return TTSResult(self.name, output_path, True)
