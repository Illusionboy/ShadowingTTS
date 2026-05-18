from __future__ import annotations

import mimetypes
from pathlib import Path

import httpx

from ..audio import ensure_reference_wav
from ..base import TTSAdapter, TTSRequest, TTSResult


ALLOWED_COST_CONTROL_MODELS = {"eleven_flash_v2_5", "eleven_turbo_v2_5"}


class ElevenLabsAdapter(TTSAdapter):
    name = "ElevenLabs"

    def __init__(
        self,
        api_key: str,
        model_id: str = "eleven_turbo_v2_5",
        voice_id: str | None = None,
        enable_cloning: bool = False,
        clone_name: str = "ja-ref-arena",
    ) -> None:
        if model_id not in ALLOWED_COST_CONTROL_MODELS:
            allowed = ", ".join(sorted(ALLOWED_COST_CONTROL_MODELS))
            raise ValueError(f"ElevenLabs model_id must be one of: {allowed}")
        self.api_key = api_key.strip()
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is empty")
        self.model_id = model_id
        self.voice_id = voice_id
        self.enable_cloning = enable_cloning
        self.clone_name = clone_name

    def _headers(self, accept: str | None = None) -> dict[str, str]:
        headers = {"xi-api-key": self.api_key}
        if accept:
            headers["Accept"] = accept
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if len(detail) > 1000:
                detail = f"{detail[:1000]}..."
            raise RuntimeError(
                f"ElevenLabs API error {response.status_code}: {detail}"
            ) from exc

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        voice_id = request.voice or self.voice_id
        if not voice_id and self.enable_cloning:
            if not request.reference_video:
                raise RuntimeError("ElevenLabs cloning requires reference_video")
            voice_id = await self._create_instant_clone(request)
        if not voice_id:
            voice_id = await self._first_available_voice_id()

        output_path = self.output_path(request)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = self._headers("audio/mpeg" if request.output_format == "mp3" else "audio/wav")
        settings = request.voice_settings or {
            "stability": 0.35,
            "similarity_boost": 0.75,
            "style": 0.45,
            "use_speaker_boost": True,
        }
        body = {
            "text": request.text,
            "model_id": self.model_id,
            "voice_settings": settings,
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(url, headers=headers, json=body)
            self._raise_for_status(response)
        output_path.write_bytes(response.content)
        return TTSResult(self.name, output_path, True)

    async def _first_available_voice_id(self) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers=self._headers(),
            )
            self._raise_for_status(response)
        voices = response.json().get("voices", [])
        if not voices:
            raise RuntimeError("No ElevenLabs voices are available for this account")
        return voices[0]["voice_id"]

    async def _create_instant_clone(self, request: TTSRequest) -> str:
        assert request.reference_video is not None
        reference_wav = await ensure_reference_wav(
            request.reference_video, request.output_dir / "_reference_audio"
        )
        mime_type = mimetypes.guess_type(reference_wav)[0] or "audio/wav"
        headers = self._headers()
        data = {"name": self.clone_name, "description": "Japanese arena reference clone"}
        with Path(reference_wav).open("rb") as audio_file:
            files = {"files": (reference_wav.name, audio_file, mime_type)}
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    "https://api.elevenlabs.io/v1/voices/add",
                    headers=headers,
                    data=data,
                    files=files,
                )
                self._raise_for_status(response)
        return response.json()["voice_id"]
