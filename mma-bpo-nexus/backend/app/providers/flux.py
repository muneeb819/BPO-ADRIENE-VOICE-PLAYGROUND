"""Authenticated Deepgram Flux streaming connection.

The connection is deliberately small: the API route owns browser/session policy,
while this adapter owns only the upstream transport and credential header.
"""

from __future__ import annotations

import os

import websockets

from .base import VoiceProviderError

FLUX_URL = (
    "wss://api.deepgram.com/v2/listen"
    "?eager_eot_threshold=0.3&eot_threshold=0.7&eot_timeout_ms=5000"
    "&language_hint=en&model=flux-general-en&encoding=linear16&sample_rate=16000"
)


class FluxConnection:
    def __init__(self, factory, api_key: str):
        self._factory = factory
        self._api_key = api_key
        self._socket = None

    async def __aenter__(self):
        try:
            self._socket = await self._factory(
                FLUX_URL,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
            )
            return self
        except Exception as exc:
            raise VoiceProviderError("Unable to connect to Deepgram Flux", 502) from exc

    async def __aexit__(self, *_):
        await self.close()

    async def send_audio(self, audio: bytes) -> None:
        if self._socket is None:
            raise VoiceProviderError("Flux stream is not connected", 502)
        try:
            await self._socket.send(audio)
        except Exception as exc:
            raise VoiceProviderError("Deepgram Flux audio stream failed", 502) from exc

    async def receive(self) -> str:
        if self._socket is None:
            raise VoiceProviderError("Flux stream is not connected", 502)
        try:
            message = await self._socket.recv()
            return message.decode("utf-8") if isinstance(message, bytes) else message
        except Exception as exc:
            raise VoiceProviderError("Deepgram Flux response stream failed", 502) from exc

    async def close(self) -> None:
        if self._socket is not None:
            try:
                await self._socket.close()
            except Exception:
                pass
            self._socket = None


class DeepgramFluxStreamProvider:
    def __init__(self, api_key: str, connect_factory=websockets.connect):
        if not api_key.strip():
            raise ValueError("A Deepgram API key is required")
        self._api_key = api_key.strip()
        self._connect_factory = connect_factory

    def connect(self) -> FluxConnection:
        return FluxConnection(self._connect_factory, self._api_key)


def build_flux_provider() -> DeepgramFluxStreamProvider | None:
    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    return DeepgramFluxStreamProvider(api_key) if api_key else None
