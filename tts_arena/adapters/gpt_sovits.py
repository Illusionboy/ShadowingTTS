from __future__ import annotations

from pathlib import Path

import httpx

from ..audio import ensure_reference_wav
from ..base import TTSAdapter, TTSRequest, TTSResult


class GPTSoVITSAdapter(TTSAdapter):
    name = "GPT-SoVITS"

    def __init__(
        self,
        base_url: str,
        ckpt_path: str | None = None,
        ref_audio_path: str | None = None,
        model_endpoint: str = "/set_model",
        tts_endpoint: str = "/tts",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ckpt_path = ckpt_path
        self.ref_audio_path = ref_audio_path
        self.model_endpoint = model_endpoint
        self.tts_endpoint = tts_endpoint

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        if not request.reference_video and not self.ref_audio_path:
            raise RuntimeError("GPT-SoVITS requires reference_video for deep cloning")
        reference_wav = (
            Path(self.ref_audio_path)
            if self.ref_audio_path
            else await ensure_reference_wav(
                request.reference_video, request.output_dir / "_reference_audio"
            )
        )
        async with httpx.AsyncClient(timeout=300) as client:
            if self.ckpt_path:
                model_response = await client.post(
                    f"{self.base_url}{self.model_endpoint}",
                    json={"ckpt_path": self.ckpt_path},
                )
                model_response.raise_for_status()

            tts_response = await client.post(
                f"{self.base_url}{self.tts_endpoint}",
                json={
                    "text": request.text,
                    "text_lang": "ja",
                    "ref_audio_path": str(reference_wav),
                    "prompt_lang": "ja",
                    "prompt_text": "",
                    "output_format": request.output_format,
                },
            )
            tts_response.raise_for_status()

        output_path = self.output_path(request)
        output_path.write_bytes(tts_response.content)
        return TTSResult(self.name, output_path, True)
