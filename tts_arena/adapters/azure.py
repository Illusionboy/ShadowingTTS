from __future__ import annotations

import html

import httpx

from ..base import TTSAdapter, TTSRequest, TTSResult


class AzureTTSAdapter(TTSAdapter):
    name = "Azure TTS"

    def __init__(self, key: str, region: str, voice: str = "ja-JP-NanamiNeural") -> None:
        self.key = key
        self.region = region
        self.voice = voice

    LOCALES = {"ja": "ja-JP", "en": "en-US", "zh": "zh-CN", "ko": "ko-KR"}

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        output_path = self.output_path(request)
        voice = request.voice or self.voice
        # The SSML locale has to follow the request, not the Japanese default,
        # or English text is voiced with Japanese phonetics.
        locale = self.LOCALES.get(request.language or "ja", "ja-JP")
        output_format = (
            "audio-24khz-160kbitrate-mono-mp3"
            if request.output_format == "mp3"
            else "riff-24khz-16bit-mono-pcm"
        )
        ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale}'>"
            f"<voice name='{html.escape(voice)}'>"
            f"{html.escape(request.text)}"
            "</voice></speak>"
        )
        url = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "shadowing-tts-arena",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
            response.raise_for_status()
        output_path.write_bytes(response.content)
        return TTSResult(self.name, output_path, True)
