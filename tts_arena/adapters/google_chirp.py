from __future__ import annotations

import asyncio

from ..base import TTSAdapter, TTSRequest, TTSResult


class GoogleChirpAdapter(TTSAdapter):
    name = "Google Chirp 3"

    def __init__(self, voice_name: str = "ja-JP-Chirp3-HD-Aoede") -> None:
        self.voice_name = voice_name

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        return await asyncio.to_thread(self._sync_synthesize, request)

    def _sync_synthesize(self, request: TTSRequest) -> TTSResult:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        audio_encoding = (
            texttospeech.AudioEncoding.MP3
            if request.output_format == "mp3"
            else texttospeech.AudioEncoding.LINEAR16
        )
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=request.text),
            voice=texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                name=request.voice or self.voice_name,
            ),
            audio_config=texttospeech.AudioConfig(audio_encoding=audio_encoding),
        )

        output_path = self.output_path(request)
        output_path.write_bytes(response.audio_content)
        return TTSResult(self.name, output_path, True)
