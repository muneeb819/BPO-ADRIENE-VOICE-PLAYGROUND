"""Validated API input contracts."""

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .providers.catalog import PERSONA_BY_ID, TONES, TTS_VOICE_IDS


class AgentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=80)
    campaign: str = Field(default="Inbound intake", max_length=100)
    greeting: str = Field(min_length=10, max_length=500)
    personaPreset: str = "intake"
    purpose: str = Field(default="Inbound service qualification", min_length=5, max_length=160)
    tone: str = "professional"
    transfersEnabled: bool = True
    requireConsent: bool = True
    sttProvider: Literal["browser", "deepgram", "deepgram-flux"] = "browser"
    sttModel: Literal["browser", "nova-2", "nova-3", "flux-general-en"] = "browser"
    ttsProvider: Literal["browser", "deepgram"] = "browser"
    ttsVoice: str = "aura-asteria-en"

    @model_validator(mode="after")
    def validate_stt_route(self):
        expected = {
            "browser": {"browser"},
            "deepgram": {"nova-2", "nova-3"},
            "deepgram-flux": {"flux-general-en"},
        }
        if self.sttModel not in expected[self.sttProvider]:
            raise ValueError(f"{self.sttModel} is not valid for {self.sttProvider}")
        if self.personaPreset not in PERSONA_BY_ID:
            raise ValueError("Unknown persona preset")
        if self.tone not in TONES:
            raise ValueError("Unknown response tone")
        if self.ttsVoice not in TTS_VOICE_IDS:
            raise ValueError("Unknown Deepgram TTS voice")
        return self


class SessionCreate(BaseModel):
    agentId: str = Field(min_length=1, max_length=80)


class TurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    inputMethod: Literal["text", "browser-stt", "deepgram-stt", "deepgram-flux-stt"] = "text"
    sttLatencyMs: float | None = Field(default=None, ge=0, le=120000)

    @field_validator("content")
    @classmethod
    def content_must_have_visible_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must contain visible text")
        return value

    @model_validator(mode="after")
    def validate_stt_measurement(self):
        if self.inputMethod == "text" and self.sttLatencyMs is not None:
            raise ValueError("sttLatencyMs is only valid for voice input")
        if self.inputMethod != "text" and self.sttLatencyMs is None:
            raise ValueError("sttLatencyMs is required for voice input")
        return self


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def text_must_have_visible_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must contain visible text")
        return value


class BrowserVoiceMetric(BaseModel):
    operation: Literal["stt", "tts"]
    status: Literal["success", "error"] = "success"
    latencyMs: float = Field(ge=0, le=120000)
    message: str | None = Field(default=None, max_length=200)


class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("password must include letters and numbers")
        return value


class SetupRequest(PasswordInput):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    displayName: str = Field(min_length=2, max_length=80)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class UserCreateRequest(SetupRequest):
    role: Literal["admin", "viewer"] = "viewer"


class UserAccessUpdate(BaseModel):
    role: Literal["admin", "viewer"]
    active: bool


class RetentionUpdate(BaseModel):
    transcriptDays: int = Field(ge=1, le=365)
    autoDelete: bool


class LiveKitRoomCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class LiveKitRoomAction(BaseModel):
    room: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    agentName: str | None = Field(default=None, max_length=120)


class VoicePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    voice: str

    @field_validator("text")
    @classmethod
    def text_must_have_visible_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must contain visible text")
        return value

    @field_validator("voice")
    @classmethod
    def validate_voice(cls, value: str) -> str:
        if value not in TTS_VOICE_IDS:
            raise ValueError("Unknown Deepgram TTS voice")
        return value
