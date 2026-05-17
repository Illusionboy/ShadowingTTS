from __future__ import annotations

from ..base import TTSAdapter, TTSRequest, TTSResult


class EdgeTTSAdapter(TTSAdapter):
    name = "Edge TTS"

    def __init__(self, voice: str = "ja-JP-NanamiNeural") -> None:
        self.voice = voice

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        import edge_tts

        output_path = self.output_path(request)
        communicate = edge_tts.Communicate(request.text, request.voice or self.voice)
        await communicate.save(str(output_path))
        return TTSResult(self.name, output_path, True)
