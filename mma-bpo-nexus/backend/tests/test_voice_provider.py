"""Deepgram HTTP contract tests with no real network or credentials."""

import asyncio
import json

import httpx
import pytest

from app.providers import DeepgramVoiceProvider, VoiceProviderError


def test_nova_stt_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/listen"
        assert request.url.params["model"] == "nova-2"
        assert request.url.params["smart_format"] == "true"
        assert request.headers["Authorization"] == "Token test-only-key"
        assert request.headers["Content-Type"] == "audio/webm"
        assert request.content == b"audio-bytes"
        return httpx.Response(200, json={
            "results": {"channels": [{"alternatives": [{"transcript": " yes, I am the account holder "}]}]}
        })

    provider = DeepgramVoiceProvider("test-only-key", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.transcribe(b"audio-bytes", "audio/webm", "nova-2"))
    assert result.text == "yes, I am the account holder"
    assert result.provider == "deepgram"
    assert result.model == "nova-2"
    assert result.latency_ms >= 0


def test_aura_tts_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speak"
        assert request.url.params["model"] == "aura-asteria-en"
        assert request.headers["Authorization"] == "Token test-only-key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"text": "Hello from MMA"}
        return httpx.Response(200, content=b"ID3-audio", headers={"Content-Type": "audio/mpeg"})

    provider = DeepgramVoiceProvider("test-only-key", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.synthesize("Hello from MMA", "aura-asteria-en"))
    assert result.audio == b"ID3-audio"
    assert result.content_type == "audio/mpeg"
    assert result.voice == "aura-asteria-en"
    assert result.latency_ms >= 0


def test_provider_errors_do_not_include_credentials_or_upstream_body():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "upstream sensitive detail"})

    provider = DeepgramVoiceProvider("test-only-key", transport=httpx.MockTransport(handler))
    with pytest.raises(VoiceProviderError) as caught:
        asyncio.run(provider.synthesize("Hello", "aura-asteria-en"))
    assert "HTTP 401" in str(caught.value)
    assert "test-only-key" not in str(caught.value)
    assert "sensitive detail" not in str(caught.value)


def test_flux_and_aura_voices_use_their_respective_endpoints():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, content=b"ID3-audio", headers={"Content-Type": "audio/mpeg"})

    provider = DeepgramVoiceProvider("test-only-key", transport=httpx.MockTransport(handler))
    asyncio.run(provider.synthesize("Flux preview", "flux-hannah-en"))
    asyncio.run(provider.synthesize("Aura preview", "aura-luna-en"))
    assert paths == ["/v2/speak", "/v1/speak"]


def test_provider_rejects_unsupported_stage_models():
    provider = DeepgramVoiceProvider("test-only-key", transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(VoiceProviderError) as caught:
        asyncio.run(provider.transcribe(b"audio", "audio/webm", "unknown-model"))
    assert caught.value.status_code == 400
