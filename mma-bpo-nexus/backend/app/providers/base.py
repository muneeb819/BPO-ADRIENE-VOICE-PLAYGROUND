"""Provider-neutral voice contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    latency_ms: float


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    content_type: str
    provider: str
    voice: str
    latency_ms: float


class VoiceProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502, latency_ms: float = 0):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.latency_ms = latency_ms


class VoiceProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, content_type: str, model: str) -> TranscriptionResult:
        """Transcribe one audio clip without persisting the audio."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> SpeechResult:
        """Synthesize text without persisting the generated audio."""
