"""Deepgram Nova-2 STT and Aura TTS implementation."""

from __future__ import annotations

import os
import time

import httpx

from .base import SpeechResult, TranscriptionResult, VoiceProvider, VoiceProviderError
from .catalog import TTS_VOICE_IDS


class DeepgramVoiceProvider(VoiceProvider):
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key.strip():
            raise ValueError("A Deepgram API key is required")
        self._api_key = api_key.strip()
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Token {self._api_key}"},
        )

    async def transcribe(self, audio: bytes, content_type: str, model: str) -> TranscriptionResult:
        if model not in {"nova-2", "nova-3"}:
            raise VoiceProviderError("Buffered Deepgram STT supports nova-2 or nova-3", 400)
        started = time.perf_counter()
        try:
            async with self._client(30) as client:
                response = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params={"model": model, "smart_format": "true", "punctuate": "true"},
                    content=audio,
                    headers={"Content-Type": content_type},
                )
                response.raise_for_status()
                payload = response.json()
            transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
            if not transcript:
                raise VoiceProviderError("Deepgram returned an empty transcript", 502)
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            return TranscriptionResult(transcript, "deepgram", model, elapsed)
        except VoiceProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            raise VoiceProviderError(
                f"Deepgram STT returned HTTP {exc.response.status_code}", 502, elapsed
            ) from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            raise VoiceProviderError("Deepgram STT could not be reached or returned an invalid response", 502, elapsed) from exc

    async def synthesize(self, text: str, voice: str) -> SpeechResult:
        if voice not in TTS_VOICE_IDS:
            raise VoiceProviderError("Unsupported Deepgram TTS voice", 400)
        speak_path = "/v2/speak" if voice.startswith("flux-") else "/v1/speak"
        started = time.perf_counter()
        try:
            async with self._client(30) as client:
                response = await client.post(
                    f"https://api.deepgram.com{speak_path}",
                    params={"model": voice},
                    json={"text": text},
                )
                response.raise_for_status()
            if not response.content:
                raise VoiceProviderError("Deepgram returned empty audio", 502)
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            return SpeechResult(
                audio=response.content,
                content_type=response.headers.get("Content-Type", "audio/mpeg").split(";")[0],
                provider="deepgram",
                voice=voice,
                latency_ms=elapsed,
            )
        except VoiceProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            raise VoiceProviderError(
                f"Deepgram TTS returned HTTP {exc.response.status_code}", 502, elapsed
            ) from exc
        except httpx.HTTPError as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            raise VoiceProviderError("Deepgram TTS could not be reached", 502, elapsed) from exc


def build_voice_provider() -> DeepgramVoiceProvider | None:
    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    return DeepgramVoiceProvider(api_key) if api_key else None
