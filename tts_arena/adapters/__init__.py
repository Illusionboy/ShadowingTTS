from .azure import AzureTTSAdapter
from .edge import EdgeTTSAdapter
from .elevenlabs import ElevenLabsAdapter
from .google_chirp import GoogleChirpAdapter
from .gpt_sovits import GPTSoVITSAdapter
from .openai_tts import OpenAITTSAdapter

__all__ = [
    "AzureTTSAdapter",
    "EdgeTTSAdapter",
    "ElevenLabsAdapter",
    "GoogleChirpAdapter",
    "GPTSoVITSAdapter",
    "OpenAITTSAdapter",
]
