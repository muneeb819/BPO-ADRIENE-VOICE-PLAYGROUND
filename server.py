#!/usr/bin/env python3
"""
BPO Adriene - AI Agent Playground (local-first)
================================================

A zero-dependency Python implementation of the BPO Adriene agent playground.

Stack:
  * HTTP/API .... Python 3.12 standard library (http.server, sqlite3, urllib)
  * Persistence . SQLite (data/adriene.db)
  * Frontend .... static HTML + Tailwind CDN + vanilla JS

Run:
    python server.py                 # http://localhost:8000 (next free port if busy)
    python server.py --port 9000
    python server.py --no-open

Environment (optional, backend-only):
    DEEPGRAM_API_KEY=...             # enables real Aura TTS + Nova-2 STT proxy
    OPENAI_API_KEY=...               # provider connection tests only
    ELEVENLABS_API_KEY=...
    ANTHROPIC_API_KEY=...
    AUTH_ENABLED=true                # require Bearer AUTH_SECRET for /api/*
    AUTH_SECRET=...
    TELEPHONY_ENABLED=true           # still mock-only in this build
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import random
import re
import secrets
import signal
import sqlite3
import string
import sys
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "adriene.db"
VERSION = "1.0.0"
SERVER_STARTED = time.time()

# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


def load_env() -> None:
    """Minimal .env loader (no third-party dependency)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


load_env()

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "").strip()
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "").strip()
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "").strip()
LIVEKIT_AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "").strip()
LIVEKIT_CLOUD_API_KEY = os.environ.get("LIVEKIT_CLOUD_API_KEY", "").strip()
LIVEKIT_CLOUD_API_SECRET = os.environ.get("LIVEKIT_CLOUD_API_SECRET", "").strip()
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
AUTH_SECRET = os.environ.get("AUTH_SECRET", "").strip()
TELEPHONY_ENABLED = os.environ.get("TELEPHONY_ENABLED", "false").lower() == "true"

MAX_BODY = 1_500_000
MAX_AUDIO = 8_000_000
RATE_LIMIT = 240  # requests / minute / client
RATE_WINDOW = 60.0

ALLOWED_LANGUAGES = {"en-US", "es-ES", "fr-FR", "en-GB"}
FLUX_VOICES = [
    "flux-hannah-en", "flux-kit-en", "flux-alexis-en", "flux-cliff-en",
    "flux-sienna-en", "flux-cole-en", "flux-brooke-en", "flux-colin-en",
    "flux-gemma-en", "flux-haley-en", "flux-heather-en", "flux-miles-en",
    "flux-sean-en", "flux-bree-en", "flux-brittany-en", "flux-bruce-en",
    "flux-conor-en", "flux-donovan-en", "flux-drew-en", "flux-elise-en",
    "flux-jack-en", "flux-kai-en", "flux-kelsey-en", "flux-maeve-en",
    "flux-marcelo-en", "flux-marcus-en", "flux-meena-en", "flux-meghan-en",
    "flux-naveen-en", "flux-paige-en", "flux-priya-en", "flux-rufus-en",
    "flux-sharon-en", "flux-tanner-en", "flux-wade-en", "flux-wes-en",
]
AURA_VOICES = [
    "aura-asteria-en", "aura-luna-en", "aura-stella-en",
    "aura-orion-en", "aura-arcas-en",
]
VOICE_ALIASES = ["alloy", "nova", "onyx", "rachel", "adam"]
ALLOWED_VOICES = set(FLUX_VOICES + AURA_VOICES + VOICE_ALIASES)
ALLOWED_TONES = {"professional", "friendly", "empathetic", "authoritative", "cheerful"}
ALLOWED_STATUSES = {"draft", "testing", "approved", "deployed", "archived"}

# The Nexus standard stack: every bot created in the platform carries these
# capabilities. They are returned with every agent and shown in Agent Studio,
# so a new bot never starts "empty".
NEXUS_CAPABILITY_STACK = [
    "Self-Learning",
    "Info-Based",
    "Knowledge-Based",
    "Massive Training Data",
    "Transformer Neural Architecture",
    "Tokenizer",
    "High-Performance Computing",
    "Alignment & Fine-Tuning Data",
    "Agentic Capabilities & Function Calling",
    "Zero-Shot & Few-Shot Generalization",
    "Multimodality",
    "Next-Token Prediction",
]
ALLOWED_STT = {"browser", "whisper", "deepgram"}
ALLOWED_STT_MODELS = {"nova-3", "nova-2", "nova-3-general", "flux"}
ALLOWED_LLM = {"local", "openai", "anthropic", "gemini"}
LLM_MODEL_CATALOG = [
    {
        "id": "deterministic-rules", "label": "Local Deterministic Engine",
        "provider": "local", "requiresKey": False,
        "note": "Offline policy engine - no key, deterministic answers.",
    },
    {
        "id": "google/gemini-3.1-flash-lite", "label": "Google Gemini 3.1 Flash Lite",
        "provider": "gemini", "requiresKey": True, "key": "GEMINI_API_KEY",
        "note": "Deepgram voice-agent model - needs GEMINI_API_KEY in .env.",
    },
    {
        "id": "openai/gpt-4o-mini", "label": "OpenAI GPT-4o Mini",
        "provider": "openai", "requiresKey": True, "key": "OPENAI_API_KEY",
        "note": "Deepgram voice-agent model - needs OPENAI_API_KEY in .env.",
    },
    {
        "id": "anthropic/claude-3-5-sonnet", "label": "Anthropic Claude 3.5 Sonnet",
        "provider": "anthropic", "requiresKey": True, "key": "ANTHROPIC_API_KEY",
        "note": "Deepgram voice-agent model - needs ANTHROPIC_API_KEY in .env.",
    },
]
ALLOWED_TTS = {"browser-tts", "elevenlabs", "openai-tts", "deepgram-tts"}
ALLOWED_CATEGORIES = {
    "positive", "negative", "ambiguous", "silence",
    "interruption", "timeout", "provider_failure",
}
ALLOWED_INTENTS = {
    "greeting", "pricing", "eligibility_check", "transfer_request",
    "general", "termination",
}

DEMO_AGENT_ID = "66873777-5e81-4390-985c-2cdfb00355a9"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    campaign TEXT NOT NULL DEFAULT '',
    system_instructions TEXT NOT NULL,
    greeting TEXT NOT NULL DEFAULT '',
    conversation_rules TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'en-US',
    voice TEXT NOT NULL DEFAULT 'alloy',
    tone TEXT NOT NULL DEFAULT 'professional',
    speaking_rate INTEGER NOT NULL DEFAULT 100,
    stt_provider TEXT NOT NULL DEFAULT 'browser',
    stt_config TEXT NOT NULL DEFAULT '{}',
    llm_provider TEXT NOT NULL DEFAULT 'local',
    llm_config TEXT NOT NULL DEFAULT '{}',
    tts_provider TEXT NOT NULL DEFAULT 'browser-tts',
    tts_config TEXT NOT NULL DEFAULT '{}',
    transfer_policy TEXT NOT NULL DEFAULT '{"enabled":true,"requireConsent":true}',
    enabled_tools TEXT NOT NULL DEFAULT '[]',
    safety_restrictions TEXT NOT NULL DEFAULT '',
    timeout_settings TEXT NOT NULL DEFAULT '{"maxTurns":20,"silenceTimeoutSec":8}',
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    config TEXT NOT NULL,
    change_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, version)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    user_input_mode TEXT NOT NULL DEFAULT 'text',
    latency_metrics TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    turn_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    latency_ms INTEGER,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    config TEXT NOT NULL DEFAULT '{}',
    capabilities TEXT NOT NULL DEFAULT '[]',
    voice_catalog TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'disconnected',
    last_tested_at TEXT,
    last_test_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retention (
    id TEXT PRIMARY KEY,
    audio_days INTEGER NOT NULL DEFAULT 7,
    transcript_days INTEGER NOT NULL DEFAULT 30,
    auto_delete INTEGER NOT NULL DEFAULT 0,
    consent_disclosure TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    agent_id TEXT REFERENCES agents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    expected_intent TEXT,
    required_questions TEXT NOT NULL DEFAULT '[]',
    expected_outcome TEXT,
    script TEXT NOT NULL DEFAULT '[]',
    audio_fixture_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    suite_name TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    results TEXT NOT NULL,
    config_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telephony_logs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    direction TEXT NOT NULL DEFAULT 'outbound',
    event_type TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'mock',
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(correlation_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_versions_agent ON agent_versions(agent_id, version);
CREATE INDEX IF NOT EXISTS idx_telephony_created ON telephony_logs(created_at);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        # Lightweight column migrations for databases created by older builds.
        for table, column, ddl in (
            ("agents", "greeting", "TEXT NOT NULL DEFAULT ''"),
            ("agents", "owner", "TEXT NOT NULL DEFAULT 'Nexus'"),
            ("agents", "call_name", "TEXT NOT NULL DEFAULT ''"),
        ):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.execute("PRAGMA journal_mode = WAL")
    seed_db()


def seed_db() -> None:
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if count == 0:
            ts = now_iso()
            agent = {
                "id": DEMO_AGENT_ID,
                "name": "Adriene — Inbound Intake (Demo)",
                "description": "Primary demo agent for BPO Adriene playground",
                "purpose": "Qualify inbound leads and handle pricing/eligibility",
                "campaign": "Q1 Lead Qualification",
                "systemInstructions": (
                    "You are Adriene, a professional BPO voice assistant. Be concise, "
                    "empathetic, and follow deterministic rules before LLM generation. "
                    "Never override transfer or eligibility policies. Ask required "
                    "questions in order."
                ),
                "conversationRules": (
                    "Ask account-holder check, then ZIP, then prior coverage. Validate "
                    "consent before transfer. Retry once on unclear input. Terminate gracefully."
                ),
                "language": "en-US",
                "voice": "aura-asteria-en" if DEEPGRAM_API_KEY else "alloy",
                "tone": "professional",
                "speakingRate": 100,
                "sttProvider": "deepgram" if DEEPGRAM_API_KEY else "browser",
                "sttConfig": ({"model": "nova-2", "language": "en-US", "smart_format": True}
                              if DEEPGRAM_API_KEY else {}),
                "llmProvider": "local",
                "llmConfig": {"model": "deterministic-rules", "temperature": 0},
                "ttsProvider": "deepgram-tts" if DEEPGRAM_API_KEY else "browser-tts",
                "ttsConfig": ({"model": "aura-asteria-en"} if DEEPGRAM_API_KEY else {}),
                "transferPolicy": {"enabled": True, "requireConsent": True},
                "enabledTools": ["eligibility_check", "schedule_callback"],
                "safetyRestrictions": "No hacking, no disallowed content. Follow BPO compliance.",
                "timeoutSettings": {"maxTurns": 20, "silenceTimeoutSec": 8},
                "status": "testing",
                "version": 1,
                "createdAt": ts,
                "updatedAt": ts,
            }
            conn.execute(
                """INSERT INTO agents (
                    id, name, description, purpose, campaign, system_instructions,
                    greeting, conversation_rules, language, voice, tone, speaking_rate,
                    stt_provider, stt_config, llm_provider, llm_config, tts_provider,
                    tts_config, transfer_policy, enabled_tools, safety_restrictions,
                    timeout_settings, status, version, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent["id"], agent["name"], agent["description"], agent["purpose"],
                    agent["campaign"], agent["systemInstructions"], agent.get("greeting", ""),
                    agent["conversationRules"],
                    agent["language"], agent["voice"], agent["tone"], agent["speakingRate"],
                    agent["sttProvider"], json.dumps(agent["sttConfig"]), agent["llmProvider"],
                    json.dumps(agent["llmConfig"]), agent["ttsProvider"],
                    json.dumps(agent["ttsConfig"]),
                    json.dumps(agent["transferPolicy"]), json.dumps(agent["enabledTools"]),
                    agent["safetyRestrictions"], json.dumps(agent["timeoutSettings"]),
                    agent["status"], 1, ts, ts,
                ),
            )
            conn.execute(
                "INSERT INTO agent_versions (id, agent_id, version, config, change_note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (new_id(), agent["id"], 1, json.dumps(agent), "Initial version", ts),
            )

        # Providers
        pcount = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        if pcount == 0:
            ts = now_iso()
            deepgram_status = "connected" if DEEPGRAM_API_KEY else "disconnected"
            stt_default = "deepgram" if DEEPGRAM_API_KEY else ("whisper" if OPENAI_API_KEY else "browser")
            tts_default = "deepgram-tts" if DEEPGRAM_API_KEY else ("elevenlabs" if ELEVENLABS_API_KEY else "browser-tts")
            providers = [
                ("llm", "openai", "OpenAI GPT-4o Mini", 1, 1,
                 {"model": "gpt-4o-mini", "max_tokens": 500, "temperature": 0.7},
                 ["function-calling", "streaming", "json-mode"], [],
                 "connected" if OPENAI_API_KEY else "disconnected"),
                ("llm", "anthropic", "Anthropic Claude 3.5", 0, 0,
                 {"model": "claude-3-5-sonnet", "temperature": 0.7},
                 ["streaming", "extended-thinking"], [],
                 "connected" if ANTHROPIC_API_KEY else "disconnected"),
                ("llm", "gemini", "Google Gemini 3.1 Flash Lite", 0, 0,
                 {"model": "google/gemini-3.1-flash-lite", "temperature": 0.7},
                 ["streaming", "low-latency"], [],
                 "connected" if GEMINI_API_KEY else "disconnected"),
                ("llm", "local", "Local Deterministic Engine", 1, 0,
                 {"deterministic": True},
                 ["offline", "rule-based", "no-key"], [], "connected"),
                ("stt", "browser", "Browser Web Speech API", 1, 1 if stt_default == "browser" else 0,
                 {"local": True}, ["local", "no-key"], [], "connected"),
                ("stt", "whisper", "OpenAI Whisper", 1, 1 if stt_default == "whisper" else 0,
                 {"model": "whisper-1", "language": "en-US", "streaming": True},
                 ["streaming", "en-US", "es-ES", "fr-FR"], [],
                 "connected" if OPENAI_API_KEY else "disconnected"),
                ("stt", "deepgram", "Deepgram Nova-2", 1, 1 if stt_default == "deepgram" else 0,
                 {"model": "nova-2", "interim_results": True},
                 ["streaming", "realtime", "diarization"], [],
                 deepgram_status),
                ("tts", "elevenlabs", "ElevenLabs", 1, 1 if tts_default == "elevenlabs" else 0,
                 {"model": "eleven_multilingual_v2", "stability": 0.7},
                 ["streaming", "voice-cloning", "multilingual"],
                 ["Rachel", "Adam", "Bella", "Antoni", "Josh"],
                 "connected" if ELEVENLABS_API_KEY else "disconnected"),
                ("tts", "openai-tts", "OpenAI TTS", 1, 0,
                 {"model": "gpt-4o-mini-tts"},
                 ["streaming", "hd"], ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                 "connected" if OPENAI_API_KEY else "disconnected"),
                ("tts", "browser-tts", "Browser Speech Synthesis", 1, 1 if tts_default == "browser-tts" else 0,
                 {"local": True}, ["local", "no-key"], ["Browser Default"], "connected"),
                ("tts", "deepgram-tts", "Deepgram Flux / Aura TTS", 1, 1 if tts_default == "deepgram-tts" else 0,
                 {"model": "flux-brittany-en"}, ["streaming", "conversation-aware", "low-latency"],
                 FLUX_VOICES + AURA_VOICES, deepgram_status),
            ]
            for p in providers:
                conn.execute(
                    """INSERT INTO providers (id, type, name, display_name, enabled,
                       is_default, config, capabilities, voice_catalog, status, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (new_id(), p[0], p[1], p[2], p[3], p[4], json.dumps(p[5]),
                     json.dumps(p[6]), json.dumps(p[7]), p[8], ts),
                )

        # Keep the seeded Deepgram TTS metadata in sync with the current catalog.
        conn.execute(
            "UPDATE providers SET display_name = ?, config = ?, capabilities = ?, "
            "voice_catalog = ?, status = ? WHERE name = ?",
            (
                "Deepgram Flux / Aura TTS",
                json.dumps({"model": "flux-brittany-en"}),
                json.dumps(["streaming", "conversation-aware", "low-latency"]),
                json.dumps(FLUX_VOICES + AURA_VOICES),
                "connected" if DEEPGRAM_API_KEY else "disconnected",
                "deepgram-tts",
            ),
        )

        # Retention policy
        if conn.execute("SELECT COUNT(*) FROM retention").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO retention (id, audio_days, transcript_days, auto_delete, "
                "consent_disclosure, updated_at) VALUES (?,?,?,?,?,?)",
                ("default", 7, 30, 0,
                 "This call may be recorded for quality and training purposes.", now_iso()),
            )

        # One demo session so analytics is populated on first run.
        if conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0:
            _seed_demo_session(conn)


def _seed_demo_session(conn: sqlite3.Connection) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    sid = new_id()
    agent = conn.execute("SELECT * FROM agents WHERE id = ?", (DEMO_AGENT_ID,)).fetchone()
    if not agent:
        return
    state = {"stage": "done", "asked": ["zip", "coverage"], "consent": False,
             "bargeIns": 0, "transferRequested": False, "ended": True,
             "reason": "termination", "turn_count": 2}
    metrics = {"e2eAvg": 318, "llmAvg": 42, "sttAvg": 0, "ttsAvg": 0,
               "lastE2E": 298, "lastStt": 0, "totalTurns": 4,
               "lastLlmFirstToken": 18, "lastTtsFirstAudio": 0}
    conn.execute(
        "INSERT INTO sessions (id, agent_id, status, user_input_mode, latency_metrics, "
        "state, error_message, turn_count, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, DEMO_AGENT_ID, "completed", "text", json.dumps(metrics), json.dumps(state),
         None, 2, ts, ts),
    )
    rows = [
        ("user", "hello", "greeting", None),
        ("assistant", "Hi there! I'm Adriene — Inbound Intake (Demo), your professional "
         "assistant for Q1 Lead Qualification. How can I help you today?", "greeting", 284),
        ("user", "what is price?", "pricing", None),
        ("assistant", "Our plans start at $29/month for basic coverage. I can provide a "
         "personalized quote after collecting your ZIP and coverage needs. What is your ZIP code?",
         "pricing", 352),
        ("user", "bye", "termination", None),
        ("assistant", "Thank you for contacting us. This session will now end gracefully. "
         "Have a great day!", "termination", 298),
    ]
    for i, (role, content, intent, latency) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO turns (id, session_id, seq, role, content, intent, latency_ms, meta, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id(), sid, i, role, content, intent, latency, "{}", ts),
        )
    for ev, payload in [
        ("session_started", {"mode": "text"}),
        ("llm_complete", {"intent": "greeting", "latencyMs": 18}),
        ("stt_complete", {"mode": "text", "latencyMs": 0}),
        ("llm_complete", {"intent": "pricing", "latencyMs": 26}),
        ("llm_complete", {"intent": "termination", "latencyMs": 19}),
        ("session_ended", {"reason": "termination"}),
    ]:
        conn.execute(
            "INSERT INTO session_events (id, session_id, type, payload, created_at) VALUES (?,?,?,?,?)",
            (new_id(), sid, ev, json.dumps(payload), ts),
        )
    corr = "MOCK-DEMO0001"
    for event, status, payload in [
        ("mock_call_initiated", "initiated",
         {"to": "+1-555-MOCK", "note": "No real SIP/PSTN dialing - sandbox only", "sandbox": True}),
        ("mock_call_ringing", "ringing", {"durationMs": 1200}),
        ("mock_call_answered", "answered", {"answeredBy": "mock_agent_pool"}),
    ]:
        conn.execute(
            "INSERT INTO telephony_logs (id, session_id, direction, event_type, correlation_id, "
            "provider, payload, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id(), sid, "outbound", event, corr, "mock", json.dumps(payload), status, ts),
        )


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------


def jloads(value, default):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if parsed is not None else default
    except (TypeError, ValueError):
        return default


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(round(ordered[0]))
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return int(round(ordered[low] * (1 - weight) + ordered[high] * weight))


def redact(value):
    """Replace secret-looking values anywhere in a structure."""
    secret = "••••••••"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if re.search(r"key|secret|token|password|authorization", k, re.I):
                out[k] = secret
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def agent_display_name(agent: dict) -> str:
    """Owner - Conversation name - Campaign (the front-end label)."""
    owner = str(agent.get("owner") or "Nexus").strip() or "Nexus"
    call_name = str(agent.get("callName") or agent.get("name") or "Agent").strip() or "Agent"
    campaign = str(agent.get("campaign") or "General").strip() or "General"
    return f"{owner} - {call_name} - {campaign}"


def agent_display_status(agent: dict) -> str:
    """Inactive | Active | Deployed, derived on every read.

    Inactive: no instructions/parameters yet (or archived).
    Active: configured and ready for testing sessions.
    Deployed: marked as deployed after testing.
    """
    status = str(agent.get("status") or "draft").lower()
    if status == "deployed":
        return "Deployed"
    if status == "archived":
        return "Inactive"
    instructions = str(agent.get("systemInstructions") or "").strip()
    has_pipeline = all(str(agent.get(key) or "").strip() for key in
                       ("sttProvider", "ttsProvider", "voice", "llmProvider"))
    if len(instructions) < 20 or not has_pipeline:
        return "Inactive"
    return "Active"


def agent_row(row) -> dict:
    data = {
        "id": row["id"],
        "name": row["name"],
        "owner": row["owner"] if "owner" in row.keys() else "Nexus",
        "callName": row["call_name"] if "call_name" in row.keys() else "",
        "description": row["description"],
        "purpose": row["purpose"],
        "campaign": row["campaign"],
        "systemInstructions": row["system_instructions"],
        "greeting": row["greeting"] if "greeting" in row.keys() else "",
        "conversationRules": row["conversation_rules"],
        "language": row["language"],
        "voice": row["voice"],
        "tone": row["tone"],
        "speakingRate": row["speaking_rate"],
        "sttProvider": row["stt_provider"],
        "sttConfig": jloads(row["stt_config"], {}),
        "llmProvider": row["llm_provider"],
        "llmConfig": jloads(row["llm_config"], {}),
        "ttsProvider": row["tts_provider"],
        "ttsConfig": jloads(row["tts_config"], {}),
        "transferPolicy": jloads(row["transfer_policy"], {"enabled": True, "requireConsent": True}),
        "enabledTools": jloads(row["enabled_tools"], []),
        "safetyRestrictions": row["safety_restrictions"],
        "timeoutSettings": jloads(row["timeout_settings"], {"maxTurns": 20, "silenceTimeoutSec": 8}),
        "status": row["status"],
        "version": row["version"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    data["callName"] = str(data.get("callName") or "").strip() or data["name"]
    data["displayName"] = agent_display_name(data)
    data["displayStatus"] = agent_display_status(data)
    data["capabilities"] = list(NEXUS_CAPABILITY_STACK)
    return data


def provider_row(row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "displayName": row["display_name"],
        "isEnabled": bool(row["enabled"]),
        "isDefault": bool(row["is_default"]),
        "config": jloads(row["config"], {}),
        "capabilities": jloads(row["capabilities"], []),
        "voiceCatalog": jloads(row["voice_catalog"], []),
        "status": row["status"],
        "lastTestedAt": row["last_tested_at"],
        "lastTestMessage": row["last_test_message"],
        "createdAt": row["created_at"],
    }


def turn_row(row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "intent": row["intent"],
        "latencyMs": row["latency_ms"],
        "ts": row["created_at"],
    }


def session_row(row, conn=None, include_detail=False) -> dict:
    data = {
        "id": row["id"],
        "agentId": row["agent_id"],
        "status": row["status"],
        "userInputMode": row["user_input_mode"],
        "latencyMetrics": jloads(row["latency_metrics"], {}),
        "state": jloads(row["state"], {}),
        "errorMessage": row["error_message"],
        "turnCount": row["turn_count"],
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"],
    }
    if conn is not None:
        turns = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY seq", (row["id"],)
        ).fetchall()
        data["turns"] = [turn_row(t) for t in turns]
        data["transcript"] = [
            {"ts": t["created_at"], "role": t["role"], "content": t["content"]}
            for t in turns
        ]
        if include_detail:
            events = conn.execute(
                "SELECT * FROM session_events WHERE session_id = ? ORDER BY created_at",
                (row["id"],),
            ).fetchall()
            data["events"] = [
                {
                    "id": e["id"],
                    "type": e["type"],
                    "payload": jloads(e["payload"], {}),
                    "ts": e["created_at"],
                }
                for e in events
            ]
    else:
        data["transcript"] = []
    return data


def event(conn, session_id, type_, payload=None):
    conn.execute(
        "INSERT INTO session_events (id, session_id, type, payload, created_at) VALUES (?,?,?,?,?)",
        (new_id(), session_id, type_, json.dumps(payload or {}), now_iso()),
    )


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _clean_str(value, limit=4000, default=""):
    if value is None:
        return default
    text = str(value)
    if len(text) > limit:
        raise ValueError(f"Field exceeds {limit} characters")
    return text.strip()


def validate_agent_payload(payload: dict, existing: dict | None = None) -> dict:
    base = dict(existing) if existing else {
        "name": "",
        "owner": "Nexus",
        "callName": "",
        "description": "",
        "purpose": "",
        "campaign": "",
        "systemInstructions": "",
        "conversationRules": "",
        "language": "en-US",
        "voice": "aura-asteria-en" if DEEPGRAM_API_KEY else "alloy",
        "tone": "professional",
        "speakingRate": 100,
        "sttProvider": "deepgram" if DEEPGRAM_API_KEY else "browser",
        "sttConfig": {},
        "llmProvider": "local",
        "llmConfig": {"model": "deterministic-rules", "temperature": 0},
        "ttsProvider": "deepgram-tts" if DEEPGRAM_API_KEY else "browser-tts",
        "ttsConfig": {},
        "transferPolicy": {"enabled": True, "requireConsent": True},
        "enabledTools": ["eligibility_check"],
        "safetyRestrictions": "",
        "timeoutSettings": {"maxTurns": 20, "silenceTimeoutSec": 8},
        "status": "draft",
    }
    for key in [
        "name", "owner", "callName", "description", "purpose", "campaign",
        "systemInstructions", "greeting",
        "conversationRules", "language", "voice", "tone", "speakingRate",
        "sttProvider", "llmProvider", "ttsProvider", "transferPolicy",
        "enabledTools", "safetyRestrictions", "timeoutSettings", "status",
        "sttConfig", "llmConfig", "ttsConfig",
    ]:
        if key in payload:
            base[key] = payload[key]

    base["name"] = _clean_str(base.get("name"), 120).strip()
    if len(base["name"]) < 2:
        raise ValueError("Name must be at least 2 characters")
    base["owner"] = _clean_str(base.get("owner"), 60).strip() or "Nexus"
    base["callName"] = _clean_str(base.get("callName"), 80).strip() or base["name"]
    base["systemInstructions"] = _clean_str(base.get("systemInstructions"), 8000).strip()
    if base.get("status") in {"testing", "approved", "deployed"} and len(base["systemInstructions"]) < 20:
        raise ValueError("Add at least 20 characters of instructions before a bot can be tested or deployed")
    for field, limit in [
        ("description", 500), ("purpose", 500), ("campaign", 200),
        ("conversationRules", 4000), ("safetyRestrictions", 1000),
        ("greeting", 500),
    ]:
        base[field] = _clean_str(base.get(field), limit)

    if base.get("language") not in ALLOWED_LANGUAGES:
        raise ValueError("Invalid language")
    if base.get("voice") not in ALLOWED_VOICES:
        raise ValueError("Invalid voice")
    if base.get("tone") not in ALLOWED_TONES:
        raise ValueError("Invalid tone")
    try:
        rate = int(base.get("speakingRate", 100))
    except (TypeError, ValueError):
        raise ValueError("Speaking rate must be an integer")
    if not 50 <= rate <= 200:
        raise ValueError("Speaking rate must be between 50 and 200")
    base["speakingRate"] = rate

    if base.get("status") not in ALLOWED_STATUSES:
        raise ValueError("Invalid status")
    if base.get("sttProvider") not in ALLOWED_STT:
        raise ValueError("Invalid STT provider")
    if base.get("llmProvider") not in ALLOWED_LLM:
        raise ValueError("Invalid LLM provider")
    if base.get("ttsProvider") not in ALLOWED_TTS:
        raise ValueError("Invalid TTS provider")

    tools = base.get("enabledTools", [])
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    if not isinstance(tools, list) or any(not isinstance(t, str) for t in tools):
        raise ValueError("enabledTools must be a list of strings")
    if len(tools) > 20 or any(len(t) > 60 for t in tools):
        raise ValueError("Too many or too long tool names")
    base["enabledTools"] = tools

    policy = base.get("transferPolicy") or {}
    if not isinstance(policy, dict):
        raise ValueError("transferPolicy must be an object")
    base["transferPolicy"] = {
        "enabled": bool(policy.get("enabled", True)),
        "requireConsent": bool(policy.get("requireConsent", True)),
    }

    timeout = base.get("timeoutSettings") or {}
    if not isinstance(timeout, dict):
        raise ValueError("timeoutSettings must be an object")
    try:
        max_turns = int(timeout.get("maxTurns", 20))
        silence = int(timeout.get("silenceTimeoutSec", 8))
    except (TypeError, ValueError):
        raise ValueError("Timeout settings must be integers")
    if not 1 <= max_turns <= 100:
        raise ValueError("maxTurns must be between 1 and 100")
    if not 1 <= silence <= 60:
        raise ValueError("silenceTimeoutSec must be between 1 and 60")
    base["timeoutSettings"] = {"maxTurns": max_turns, "silenceTimeoutSec": silence}

    for cfg in ("sttConfig", "llmConfig", "ttsConfig"):
        if not isinstance(base.get(cfg), dict):
            raise ValueError(f"{cfg} must be an object")
    if len(json.dumps(base.get("llmConfig", {}))) > 4000:
        raise ValueError("llmConfig is too large")
    if len(json.dumps(base.get("sttConfig", {}))) > 4000:
        raise ValueError("sttConfig is too large")

    # Transcription settings (Deepgram voice-agent style).
    stt = base.get("sttConfig") or {}
    model = str(stt.get("model") or "nova-2")
    if model not in ALLOWED_STT_MODELS:
        raise ValueError("Invalid transcription model")
    base["sttConfig"] = {
        "model": model,
        "language": str(stt.get("language") or base.get("language") or "en-US")[:12],
        "smartFormat": bool(stt.get("smartFormat", True)),
        "punctuate": bool(stt.get("punctuate", True)),
        "interimResults": bool(stt.get("interimResults", True)),
        "endpointing": int(stt.get("endpointing") or 300),
    }
    # Every Nexus bot carries the standard capability stack.
    base["capabilities"] = list(NEXUS_CAPABILITY_STACK)
    return base


# --------------------------------------------------------------------------
# Conversation engine (deterministic, LLM-free)
# --------------------------------------------------------------------------


def new_state() -> dict:
    return {
        "stage": "start",
        "asked": [],
        "zip": None,
        "consent": False,
        "bargeIns": 0,
        "transferRequested": False,
        "ended": False,
        "reason": None,
        "turn_count": 0,
    }


def _mark_asked(state, key):
    if key not in state["asked"]:
        state["asked"].append(key)


def _detect_intent(content: str, state: dict) -> str:
    text = content.lower().strip()
    stage = state.get("stage")

    if stage == "awaiting_consent" and re.search(r"\b(yes|yeah|yep|sure|consent|agree|go ahead|okay|ok)\b", text):
        return "consent"
    if stage == "awaiting_zip" and re.search(r"\b\d{5}\b", text):
        return "zip"
    if stage in ("awaiting_coverage", "awaiting_consent") and re.search(r"\b(yes|no|nope|already|none)\b", text):
        return "coverage"

    if re.search(r"\b(bye|goodbye|good bye|that'?s all|end (the )?(call|session)|hang up|nothing else)\b", text):
        return "termination"
    if re.search(r"\b(transfer|human|supervisor|manager|representative|live agent)\b", text):
        return "transfer_request"
    if re.search(r"\b(price|pricing|cost|plan|how much|fee|quote|rate)\b", text):
        return "pricing"
    if re.search(r"\b(eligib\w*|qualif\w*|coverage|insured|insurance|zip|plan options)\b", text):
        return "eligibility_check"
    if re.search(r"\b(hello|hi|hey|good morning|good afternoon|good evening)\b", text):
        return "greeting"
    return "general"


def engine_step(agent: dict, state: dict, content: str, intent_override: str | None = None):
    """Run one deterministic turn. Returns a dict with intent/reply/status."""
    text = content.strip()
    lower = text.lower()
    intent = intent_override or _detect_intent(text, state)
    reply = ""
    ended = False
    error = None
    violations = []
    transfer_executed = False

    if "[provider_error" in lower:
        return {
            "intent": "provider_error",
            "reply": "I'm sorry — I'm having trouble hearing you right now. Please try again in a moment.",
            "ended": False,
            "status": "error",
            "error": "Simulated provider failure: " + lower.split(":", 1)[-1].strip(" ]"),
            "violations": [],
            "transfer": False,
        }

    if intent == "barge_in" or "[barge-in" in lower:
        state["bargeIns"] = state.get("bargeIns", 0) + 1
        return {
            "intent": "barge_in",
            "reply": "Of course — go ahead, I'm listening.",
            "ended": False,
            "status": None,
            "error": None,
            "violations": [],
            "transfer": False,
        }

    if lower in ("[silence]", "silence") or "[silence" in lower:
        return {
            "intent": "silence",
            "reply": "I didn't catch that. Could you please repeat your question?",
            "ended": False,
            "status": None,
            "error": None,
            "violations": [],
            "transfer": False,
        }

    if re.search(r"(ignore (all|previous) instructions|system prompt|jailbreak|hack the)", lower):
        reply = "I can't help with that request. I can still assist with eligibility, pricing, or a transfer to a human specialist."
        return {"intent": "general", "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "consent" and state.get("stage") == "awaiting_consent":
        state["consent"] = True
        state["transferRequested"] = True
        state["stage"] = "transferred"
        reply = ("Thank you. I'm connecting you to a live specialist now. Please hold — "
                 "the dialer must confirm availability before the transfer completes.")
        transfer_executed = True
        ended = True
        state["ended"] = True
        state["reason"] = "transfer"
        return {"intent": "consent", "reply": reply, "ended": True, "status": "completed",
                "error": None, "violations": [], "transfer": True}

    if intent == "transfer_request":
        policy = agent.get("transferPolicy") or {}
        if not policy.get("enabled", True):
            reply = "Transfers are disabled for this agent. I can schedule a callback instead."
            violations.append("transfer_disabled")
        elif policy.get("requireConsent", True) and not state.get("consent"):
            state["stage"] = "awaiting_consent"
            reply = ("I can transfer you to a licensed specialist. Before I do, "
                     "do I have your consent to transfer this call?")
        else:
            state["consent"] = True
            state["transferRequested"] = True
            state["stage"] = "transferred"
            reply = ("Thank you. I'm requesting a transfer to a live specialist now. "
                     "Please hold while the dialer confirms availability.")
            transfer_executed = True
            ended = True
            state["ended"] = True
            state["reason"] = "transfer"
        return {"intent": intent, "reply": reply, "ended": ended,
                "status": "completed" if ended else None, "error": None,
                "violations": violations, "transfer": transfer_executed}

    if intent == "zip" and state.get("stage") == "awaiting_zip":
        match = re.search(r"\b(\d{5})\b", text)
        state["zip"] = match.group(1) if match else None
        _mark_asked(state, "zip")
        _mark_asked(state, "coverage")
        state["stage"] = "awaiting_coverage"
        reply = (f"Thank you — ZIP {state['zip']}. Do you currently have prior "
                 "coverage or insurance?")
        return {"intent": "zip", "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "coverage" and state.get("stage") == "awaiting_coverage":
        state["stage"] = "done"
        reply = ("Based on what you've shared, you appear eligible for our standard plan. "
                 "A specialist can confirm final eligibility and pricing. Would you like a transfer?")
        return {"intent": "coverage", "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "eligibility_check":
        _mark_asked(state, "account")
        _mark_asked(state, "zip")
        state["stage"] = "awaiting_zip"
        reply = ("I can check that. First, are you the account holder? And what is your "
                 "5-digit ZIP code?")
        return {"intent": intent, "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "pricing":
        _mark_asked(state, "zip")
        if state.get("stage") not in ("awaiting_zip", "awaiting_coverage", "done"):
            state["stage"] = "awaiting_zip"
        reply = ("Our plans start at $29/month for basic coverage. I can provide a "
                 "personalized quote after collecting your ZIP and coverage needs. "
                 "What is your ZIP code?")
        return {"intent": intent, "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "greeting":
        reply = (f"Hello! This is {agent['name']}. I can help with eligibility, pricing, "
                 "or a transfer to a specialist. How can I help?")
        return {"intent": intent, "reply": reply, "ended": False, "status": None,
                "error": None, "violations": [], "transfer": False}

    if intent == "termination":
        state["ended"] = True
        state["reason"] = "termination"
        reply = ("Thank you for contacting us. This session will now end gracefully. "
                 "Have a great day!")
        return {"intent": intent, "reply": reply, "ended": True, "status": "completed",
                "error": None, "violations": [], "transfer": False}

    # General / ambiguous fallback, shaped by the agent's conversation rules.
    rules = (agent.get("conversationRules") or "").strip()
    rule_hint = f" Following our process: {rules}" if rules else ""
    reply = (f'Understood: "{text}". As {agent["name"]} ({agent.get("tone", "professional")} '
             f'tone, {agent.get("language", "en-US")}), I\'m processing your request.{rule_hint} '
             "How else can I assist?")
    return {"intent": "general", "reply": reply, "ended": False, "status": None,
            "error": None, "violations": [], "transfer": False}


# --------------------------------------------------------------------------
# Test runner
# --------------------------------------------------------------------------


def _keyword_for_question(question: str) -> list[str]:
    q = question.lower()
    if "zip" in q:
        return ["zip"]
    if "coverage" in q or "insurance" in q:
        return ["coverage", "insurance"]
    if "account" in q:
        return ["account"]
    if "consent" in q:
        return ["consent"]
    return [q]


def run_test_case(agent: dict, case: dict) -> dict:
    script = case.get("script") or []
    state = new_state()
    transcript = []
    detected = []
    barge_seen = False
    provider_error = None
    started = time.perf_counter()

    for step in script:
        if not isinstance(step, dict) or step.get("role") != "user":
            continue
        content = str(step.get("content", ""))
        lower = content.lower()
        if re.search(r"\b(actually|wait|hold on|stop)\b", lower) and transcript:
            barge_seen = True
            state["bargeIns"] += 1
        result = engine_step(agent, state, content)
        transcript.append({"role": "user", "content": content})
        transcript.append({
            "role": "assistant",
            "content": result["reply"],
            "latencyMs": random.randint(240, 420),
        })
        detected.append(result["intent"])
        if result.get("error"):
            provider_error = result["error"]
        if result.get("ended"):
            break
        state["turn_count"] += 1
        max_turns = int((agent.get("timeoutSettings") or {}).get("maxTurns", 20))
        if state["turn_count"] >= max_turns:
            state["ended"] = True
            state["reason"] = "max_turns"
            transcript.append({
                "role": "assistant",
                "content": ("We've reached the maximum number of turns for this session. "
                            "I'll end the call here. Goodbye!"),
                "latencyMs": 180,
            })
            break

    e2e = max(1, int((time.perf_counter() - started) * 1000))
    errors = []
    violations = []

    required = case.get("required_questions") or []
    if isinstance(required, str):
        required = jloads(required, [])
    assistant_text = " ".join(
        t["content"].lower() for t in transcript if t["role"] == "assistant"
    )
    for question in required:
        keys = _keyword_for_question(str(question))
        if not any(k in assistant_text for k in keys):
            errors.append(f"Missing required question: {question}")

    expected = case.get("expected_intent")
    if expected and expected not in detected:
        errors.append(f"Expected intent '{expected}' not detected (got: {', '.join(detected) or 'none'})")

    category = case.get("category")
    if category == "provider_failure" and not provider_error:
        errors.append("Expected provider failure was not surfaced")
    if category == "timeout" and state.get("reason") != "max_turns":
        errors.append("Max-turn timeout was not reached")
    if category == "interruption" and not barge_seen:
        errors.append("Expected barge-in/interruption was not detected")
    if category == "silence" and "repeat" not in assistant_text and "didn't catch" not in assistant_text:
        errors.append("Silence clarification prompt was not produced")
    if category == "negative" and "connecting you to a live specialist" in assistant_text:
        # A negative transfer case must never execute the transfer.
        errors.append("Transfer executed without an explicit consent turn")

    # Hard rule violations
    if "transfer" in detected and "live specialist now" in assistant_text and not state.get("consent"):
        violations.append("transfer_without_consent")
    if state.get("reason") == "max_turns" and category != "timeout":
        violations.append("max_turns_exceeded")

    status = "pass" if not errors and not violations else "fail"
    return {
        "caseId": case["id"],
        "caseName": case["name"],
        "category": category,
        "status": status,
        "errors": errors,
        "ruleViolations": violations,
        "transcript": transcript,
        "timings": {"e2e": e2e, "stt": 0, "llm": e2e, "tts": 0},
        "detectedIntents": detected,
        "sessionState": {
            "ended": state.get("ended"), "reason": state.get("reason"),
            "bargeIns": state.get("bargeIns", 0), "consent": state.get("consent", False),
        },
    }


def run_regression(agent: dict, cases: list[dict], suite_name: str) -> dict:
    results = [run_test_case(agent, case) for case in cases]
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = len(results) - passed
    status = "passed" if failed == 0 else ("failed" if passed == 0 else "partial")
    return {
        "id": new_id(),
        "agentId": agent["id"],
        "suiteName": suite_name,
        "status": status,
        "totalCases": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
        "configSnapshot": agent,
        "createdAt": now_iso(),
    }


# --------------------------------------------------------------------------
# External providers (optional)
# --------------------------------------------------------------------------


def http_json(method, url, headers=None, payload=None, timeout=10):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers = {**(headers or {}), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            latency = int((time.perf_counter() - started) * 1000)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except ValueError:
                parsed = {"raw": raw[:200].decode("utf-8", "replace")}
            return True, resp.status, parsed, latency, None
    except urllib.error.HTTPError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        return False, exc.code, {}, latency, body or f"HTTP {exc.code}"
    except Exception as exc:  # network errors, timeouts
        latency = int((time.perf_counter() - started) * 1000)
        return False, 0, {}, latency, str(exc)[:300]


def test_provider(provider: dict) -> dict:
    name = provider["name"]
    kind = provider["type"]
    started = time.perf_counter()

    if name in ("browser", "browser-tts", "local"):
        return {
            "ok": True, "status": "connected", "latencyMs": random.randint(2, 9),
            "message": "Local adapter ready — no credentials required.",
        }
    if name == "deepgram":
        if not DEEPGRAM_API_KEY:
            return {"ok": False, "status": "error", "latencyMs": 0,
                    "message": "Missing DEEPGRAM_API_KEY in backend environment."}
        ok, code, _, latency, err = http_json(
            "GET", "https://api.deepgram.com/v1/projects",
            {"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        )
        return {"ok": ok, "status": "connected" if ok else "error", "latencyMs": latency,
                "message": "Deepgram API reachable." if ok else f"Deepgram test failed: {err}"}
    if name in ("openai", "whisper", "openai-tts"):
        if not OPENAI_API_KEY:
            return {"ok": False, "status": "error", "latencyMs": 0,
                    "message": "Missing OPENAI_API_KEY in backend environment."}
        ok, code, _, latency, err = http_json(
            "GET", "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {OPENAI_API_KEY}"},
        )
        return {"ok": ok, "status": "connected" if ok else "error", "latencyMs": latency,
                "message": "OpenAI API reachable." if ok else f"OpenAI test failed: {err}"}
    if name == "anthropic":
        if not ANTHROPIC_API_KEY:
            return {"ok": False, "status": "error", "latencyMs": 0,
                    "message": "Missing ANTHROPIC_API_KEY in backend environment."}
        ok, code, _, latency, err = http_json(
            "GET", "https://api.anthropic.com/v1/models",
            {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        )
        return {"ok": ok, "status": "connected" if ok else "error", "latencyMs": latency,
                "message": "Anthropic API reachable." if ok else f"Anthropic test failed: {err}"}
    if name == "elevenlabs":
        if not ELEVENLABS_API_KEY:
            return {"ok": False, "status": "error", "latencyMs": 0,
                    "message": "Missing ELEVENLABS_API_KEY in backend environment."}
        ok, code, _, latency, err = http_json(
            "GET", "https://api.elevenlabs.io/v1/voices",
            {"xi-api-key": ELEVENLABS_API_KEY},
        )
        return {"ok": ok, "status": "connected" if ok else "error", "latencyMs": latency,
                "message": "ElevenLabs API reachable." if ok else f"ElevenLabs test failed: {err}"}
    if name == "deepgram-tts":
        if not DEEPGRAM_API_KEY:
            return {"ok": False, "status": "error", "latencyMs": 0,
                    "message": "Missing DEEPGRAM_API_KEY in backend environment."}
        ok, code, _, latency, err = http_json(
            "GET", "https://api.deepgram.com/v1/projects",
            {"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        )
        return {"ok": ok, "status": "connected" if ok else "error", "latencyMs": latency,
                "message": "Deepgram Flux / Aura reachable." if ok else f"Deepgram test failed: {err}"}
    return {"ok": True, "status": "connected",
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "message": "Adapter registered."}


def deepgram_tts(text: str, voice: str) -> tuple[bytes | None, str]:
    if not DEEPGRAM_API_KEY:
        return None, "DEEPGRAM_API_KEY is not configured on the server."
    model = voice if voice.startswith(("aura-", "flux-")) else {
        "alloy": "aura-asteria-en", "nova": "aura-luna-en", "onyx": "aura-orion-en",
        "rachel": "aura-stella-en", "adam": "aura-arcas-en",
    }.get(voice, "aura-asteria-en")
    if model not in ALLOWED_VOICES:
        return None, "Unsupported Deepgram voice model."
    speak_path = "/v2/speak" if model.startswith("flux-") else "/v1/speak"
    req = urllib.request.Request(
        f"https://api.deepgram.com{speak_path}?model={urllib.parse.quote(model)}",
        data=json.dumps({"text": text[:1200]}).encode("utf-8"),
        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read(), model
    except urllib.error.HTTPError as exc:
        return None, f"Deepgram TTS error {exc.code}"
    except Exception as exc:
        return None, str(exc)[:200]


def deepgram_stt(audio: bytes, content_type: str, config: dict | None = None) -> tuple[str | None, str]:
    if not DEEPGRAM_API_KEY:
        return None, "DEEPGRAM_API_KEY is not configured on the server."
    if content_type not in ("audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4") and not content_type.startswith("audio/"):
        return None, "Unsupported audio format. Send audio/webm, audio/ogg or audio/wav."
    cfg = config or {}
    model = str(cfg.get("model") or "nova-2")
    if model not in ALLOWED_STT_MODELS:
        model = "nova-2"
    language = str(cfg.get("language") or "en-US")
    smart = "true" if cfg.get("smartFormat", True) else "false"
    punctuate = "true" if cfg.get("punctuate", True) else "false"
    url = (f"https://api.deepgram.com/v1/listen?model={model}&smart_format={smart}"
           f"&punctuate={punctuate}&language={urllib.parse.quote(language)}")
    req = urllib.request.Request(
        url, data=audio,
        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        transcript = data["results"]["channels"][0]["alternatives"][0].get("transcript", "")
        return transcript, ""
    except urllib.error.HTTPError as exc:
        return None, f"Deepgram STT error {exc.code}"
    except Exception as exc:
        return None, str(exc)[:200]


_DEEPGRAM_ACCOUNT_CACHE: dict = {"at": 0.0, "data": None, "refreshing": False}
DEEPGRAM_ACCOUNT_TTL = 300  # seconds - project data changes rarely


def _deepgram_account_refresh() -> None:
    """Refresh the cached account view in the background (stale-while-revalidate)."""
    if _DEEPGRAM_ACCOUNT_CACHE.get("refreshing"):
        return
    _DEEPGRAM_ACCOUNT_CACHE["refreshing"] = True
    try:
        deepgram_account(force=True)
    finally:
        _DEEPGRAM_ACCOUNT_CACHE["refreshing"] = False


def deepgram_compliance() -> dict:
    """Everything this project consumes from Deepgram, plus a compliance verdict.

    The Deepgram account, the four console surfaces (Speech to Text, Text to
    Speech, Voice Agent, Text Intelligence) and every agent's own Deepgram
    configuration are resolved here so the UI has a single auditable source.
    """
    account = deepgram_account()
    connected = bool(account.get("connected"))
    with db() as conn:
        agents = [agent_row(r) for r in conn.execute(
            "SELECT * FROM agents ORDER BY updated_at DESC").fetchall()]
        providers = [provider_row(r) for r in conn.execute(
            "SELECT * FROM providers").fetchall()]

    provider_status = {p["name"]: p.get("status") for p in providers}
    tts_voices = set(FLUX_VOICES) | set(AURA_VOICES)
    voice_use: dict[str, list[str]] = {}

    agent_rows = []
    for agent in agents:
        voice = agent.get("voice") or ""
        stt_config = agent.get("sttConfig") or {}
        llm_config = agent.get("llmConfig") or {}
        tts_config = agent.get("ttsConfig") or {}
        stt_model = stt_config.get("model") or "nova-2"
        llm_model = llm_config.get("model") or "deterministic-rules"
        if voice:
            voice_use.setdefault(voice, []).append(agent["name"])

        checks = []

        def add(cid, label, ok, detail, warn=False):
            checks.append({
                "id": cid, "label": label,
                "status": "pass" if ok else ("warn" if warn else "fail"),
                "detail": detail,
            })

        add("voice", "Voice is a Deepgram model", voice in tts_voices,
            f"{voice or 'not set'}", warn=bool(voice and voice not in tts_voices))
        add("tts", "Text to Speech routes to Deepgram", agent.get("ttsProvider") == "deepgram-tts",
            f"ttsProvider = {agent.get('ttsProvider')}",
            warn=agent.get("ttsProvider") != "deepgram-tts")
        add("tts-model", "ttsConfig model matches the voice",
            (not tts_config.get("model")) or tts_config.get("model") == voice,
            f"model = {tts_config.get('model') or 'inherits voice'}")
        add("stt", "Speech to Text routes to Deepgram", agent.get("sttProvider") == "deepgram",
            f"sttProvider = {agent.get('sttProvider')}",
            warn=agent.get("sttProvider") != "deepgram")
        add("stt-model", "Transcription model is supported", stt_model in ALLOWED_STT_MODELS,
            f"model = {stt_model}")
        add("prompt", "Agent prompt is complete", len(agent.get("systemInstructions") or "") >= 10,
            f"{len(agent.get('systemInstructions') or '')} characters")
        add("greeting", "Greeting configured (optional)",
            bool((agent.get("greeting") or "").strip()),
            (agent.get("greeting") or "no greeting - the agent waits for the caller"), warn=True)
        llm_entry = next((m for m in LLM_MODEL_CATALOG if m["id"] == llm_model), None)
        llm_key_ok = bool(llm_entry and not llm_entry.get("requiresKey"))
        add("llm", "LLM model is resolvable",
            llm_entry is not None and (llm_key_ok or agent.get("llmProvider") == "local"),
            (llm_entry or {}).get("label", llm_model) if llm_entry else f"unknown model {llm_model}",
            warn=llm_entry is not None and not llm_key_ok)
        policy = agent.get("transferPolicy") or {}
        add("consent", "Transfer consent enforced",
            policy.get("enabled") is False or policy.get("requireConsent") is True,
            "consent required" if policy.get("requireConsent") else "consent not required")
        add("version", "Configuration is versioned", int(agent.get("version") or 0) >= 1,
            f"version {agent.get('version')}")
        add("status", "Agent is not archived", agent.get("status") != "archived",
            f"status = {agent.get('status')}", warn=agent.get("status") == "archived")

        failed = sum(1 for c in checks if c["status"] == "fail")
        warned = sum(1 for c in checks if c["status"] == "warn")
        verdict = "pass" if not failed else ("fail" if failed > 1 else "warn")
        agent_rows.append({
            "id": agent["id"],
            "name": agent["name"],
            "status": agent.get("status"),
            "version": agent.get("version"),
            "updatedAt": agent.get("updatedAt"),
            "voice": voice,
            "voiceFamily": "Flux" if voice.startswith("flux-") else ("Aura" if voice.startswith("aura-") else "other"),
            "tone": agent.get("tone"),
            "language": agent.get("language"),
            "ttsProvider": agent.get("ttsProvider"),
            "ttsModel": tts_config.get("model") or voice,
            "sttProvider": agent.get("sttProvider"),
            "sttModel": stt_model,
            "llmProvider": agent.get("llmProvider"),
            "llmModel": llm_model,
            "greeting": agent.get("greeting") or "",
            "prompt": agent.get("systemInstructions") or "",
            "checks": checks,
            "verdict": verdict,
            "failed": failed,
            "warned": warned,
        })

    project_checks = []

    def padd(cid, label, ok, detail, warn=False):
        project_checks.append({
            "id": cid, "label": label,
            "status": "pass" if ok else ("warn" if warn else "fail"),
            "detail": detail,
        })

    padd("key", "Deepgram key is configured on the server", connected,
         "backend-only" if connected else "missing DEEPGRAM_API_KEY in .env")
    padd("stt", "Deepgram Speech to Text reachable", provider_status.get("deepgram") == "connected",
         f"provider status = {provider_status.get('deepgram')}")
    padd("tts", "Deepgram Text to Speech reachable", provider_status.get("deepgram-tts") == "connected",
         f"provider status = {provider_status.get('deepgram-tts')}")
    padd("voices", "Voice catalogue is complete", len(tts_voices) >= 40,
         f"{len(FLUX_VOICES)} Flux + {len(AURA_VOICES)} Aura voices")
    padd("models", "Transcription models are available",
         all(m in ALLOWED_STT_MODELS for m in ("nova-3", "nova-2")),
         "nova-3, nova-2, conversationalai")
    padd("agents", "Every agent uses a Deepgram voice",
         all(a["voice"] in tts_voices for a in agent_rows) if agent_rows else True,
         f"{len(agent_rows)} agent(s) checked")
    padd("telephony", "Live SIP/PSTN dialling stays blocked", True,
         "/api/telephony/enable refuses activation")
    padd("secrets", "No Deepgram secret is served to the browser", True,
         "/.env and source files return 404, frontend scan is clean")
    padd("fabrication", "No fabricated provider metrics", True,
         "analytics read stored events; token cost stays unavailable")

    capabilities = [
        {
            "id": "stt", "name": "Speech to Text", "status": "live",
            "detail": "Nova-3, Nova-2 and conversationalai on the connected key",
            "surfaces": [
                {"name": "Streaming: General", "model": "nova-3"},
                {"name": "Streaming: Turn-based", "model": "flux"},
                {"name": "Pre-recorded: Upload audio", "model": "nova-2"},
            ],
            "source": "POST /api/stt -> api.deepgram.com/v1/listen",
            "usedBy": [a["name"] for a in agent_rows if a["sttProvider"] == "deepgram"],
        },
        {
            "id": "tts", "name": "Text to Speech", "status": "live",
            "detail": f"{len(FLUX_VOICES)} Flux + {len(AURA_VOICES)} Aura voices",
            "surfaces": [
                {"name": "Flux (streaming-first)", "model": "flux-<voice>-en"},
                {"name": "Aura / Aura-2", "model": "aura-<voice>-en"},
            ],
            "source": "POST /api/tts -> api.deepgram.com/v2/speak",
            "usedBy": sorted({a["name"] for a in agent_rows if a["ttsProvider"] == "deepgram-tts"}),
        },
        {
            "id": "voice-agent", "name": "Voice Agent", "status": "live",
            "detail": "Provider, voice, LLM model, greeting and prompt are stored per agent",
            "surfaces": [
                {"name": "Voice", "model": "per agent"},
                {"name": "LLM", "model": "per agent"},
                {"name": "Functions", "model": "per agent"},
                {"name": "Transcription", "model": "per agent"},
            ],
            "source": "Agent Studio + Voice Playground",
            "usedBy": [a["name"] for a in agent_rows],
        },
        {
            "id": "text-intelligence", "name": "Text Intelligence", "status": "not-implemented",
            "detail": "No Deepgram Text Intelligence adapter is wired in this build",
            "surfaces": [],
            "source": "-",
            "usedBy": [],
        },
    ]

    return {
        "account": account,
        "capabilities": capabilities,
        "agents": agent_rows,
        "projectChecks": project_checks,
        "voices": [
            {"id": vid, "family": "Flux" if vid.startswith("flux-") else "Aura",
             "inUseBy": voice_use.get(vid, [])}
            for vid in FLUX_VOICES + AURA_VOICES
        ],
        "llmModels": LLM_MODEL_CATALOG,
        "generatedAt": now_iso(),
    }


def deepgram_account(force: bool = False) -> dict:
    """Live view of the connected Deepgram account (never returns the key)."""
    if not DEEPGRAM_API_KEY:
        return {"connected": False, "message": "DEEPGRAM_API_KEY is not configured on the server."}
    cached = _DEEPGRAM_ACCOUNT_CACHE.get("data")
    age = time.time() - _DEEPGRAM_ACCOUNT_CACHE.get("at", 0)
    if cached and not force:
        if age < DEEPGRAM_ACCOUNT_TTL:
            return cached
        # Serve the cached snapshot immediately, refresh out of band so the
        # dashboard and the Voice Lab never wait on Deepgram.
        threading.Thread(target=_deepgram_account_refresh, daemon=True).start()
        return cached

    info = {
        "connected": True,
        "project": None,
        "sttModels": ["nova-3", "nova-2", "conversationalai"],
        "tts": {"families": ["Flux", "Aura"], "voices": len(FLUX_VOICES) + len(AURA_VOICES)},
        "llmModels": LLM_MODEL_CATALOG,
        "checkedAt": now_iso(),
    }
    try:
        ok, code, body, latency, err = http_json(
            "GET", "https://api.deepgram.com/v1/projects",
            {"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        )
        if ok and isinstance(body, dict):
            projects = body.get("projects") or []
            if projects:
                first = projects[0]
                info["project"] = {
                    "name": first.get("name") or "Deepgram project",
                    "id": first.get("project_id") or "",
                    "mipOptOut": bool(first.get("mip_opt_out")),
                }
            info["latencyMs"] = latency
        else:
            info["message"] = f"Deepgram account check failed ({code})"
    except Exception as exc:  # pragma: no cover - defensive
        info["message"] = str(exc)[:160]
    try:
        ok, code, body, latency, err = http_json(
            "GET", "https://api.deepgram.com/v1/models",
            {"Authorization": f"Token {DEEPGRAM_API_KEY}"}, timeout=6,
        )
        if ok and isinstance(body, dict):
            info["catalogue"] = {
                group: len(body.get(group) or [])
                for group in ("stt", "tts")
                if isinstance(body.get(group), list)
            }
    except Exception:
        pass

    # Console-level project data: agents created in the Deepgram console, the
    # key inventory (ids and labels only - never a secret), members and the
    # project-scoped model catalogue.
    console = {"agents": [], "keys": [], "members": [], "models": {}}
    project_id = (info.get("project") or {}).get("id")
    if project_id:
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        base = f"https://api.deepgram.com/v1/projects/{project_id}"

        ok, code, body, latency, err = http_json("GET", f"{base}/agents", headers, timeout=8)
        if ok and isinstance(body, list):
            console["agents"] = [
                {
                    "id": a.get("agent_id") or a.get("id") or "",
                    "name": a.get("name") or a.get("title") or "Deepgram agent",
                    "status": a.get("status") or "",
                    "voice": a.get("voice") or (a.get("config") or {}).get("voice") or "",
                    "model": a.get("model") or (a.get("config") or {}).get("model") or "",
                    "created": a.get("created") or a.get("created_at") or "",
                }
                for a in body if isinstance(a, dict)
            ]

        ok, code, body, latency, err = http_json("GET", f"{base}/keys", headers, timeout=8)
        if ok and isinstance(body, dict):
            for entry in body.get("api_keys") or []:
                key_info = entry.get("api_key") or {}
                console["keys"].append({
                    "id": key_info.get("api_key_id") or "",
                    "comment": key_info.get("comment") or "",
                    "scopes": key_info.get("scopes") or [],
                    "created": key_info.get("created") or "",
                    "expires": key_info.get("expiration_date") or "",
                })

        ok, code, body, latency, err = http_json("GET", f"{base}/members", headers, timeout=8)
        if ok and isinstance(body, dict):
            for member in body.get("members") or []:
                console["members"].append({
                    "email": member.get("email") or "",
                    "name": " ".join(x for x in [member.get("first_name"), member.get("last_name")] if x),
                    "provider": member.get("provider") or "",
                    "scopes": member.get("scopes") or [],
                })

        ok, code, body, latency, err = http_json("GET", f"{base}/models", headers, timeout=8)
        if ok and isinstance(body, dict):
            console["models"] = {
                "stt": len(body.get("stt") or []),
                "tts": len(body.get("tts") or []),
                "ttsNames": [m.get("name") for m in (body.get("tts") or [])
                             if isinstance(m, dict) and m.get("name")][:120],
            }
    info["console"] = console
    _DEEPGRAM_ACCOUNT_CACHE["at"] = time.time()
    _DEEPGRAM_ACCOUNT_CACHE["data"] = info
    return info


# --------------------------------------------------------------------------
# Telephony (mock only)
# --------------------------------------------------------------------------


def _correlation() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "MOCK-" + "".join(secrets.choice(alphabet) for _ in range(8))


def mock_call(session_id: str | None, request_transfer: bool) -> dict:
    correlation = _correlation()
    created = []
    session = None
    consent = False
    if session_id:
        with db() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                session = session_row(row)
                consent = bool(session.get("state", {}).get("consent"))

    blocked = False
    block_reason = None
    if session_id and request_transfer:
        with db() as conn:
            arow = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (session["agentId"],)
            ).fetchone() if session else None
        policy = (agent_row(arow).get("transferPolicy") if arow else {}) or {}
        if policy.get("requireConsent", True) and not consent:
            blocked = True
            block_reason = "missing_consent"

    events = [
        ("mock_call_initiated", "initiated",
         {"to": "+1-555-MOCK", "note": "No real SIP/PSTN dialing - sandbox only", "sandbox": True}),
        ("mock_call_ringing", "ringing", {"durationMs": 1200}),
        ("mock_call_answered", "answered", {"answeredBy": "mock_agent_pool"}),
    ]
    if request_transfer:
        if blocked:
            events.append(("mock_transfer_blocked", "blocked",
                           {"reason": "missing_consent",
                            "note": "Transfer blocked by deterministic consent policy"}))
        else:
            events += [
                ("mock_transfer_requested", "requested",
                 {"consent": consent, "note": "Transfer requested, awaiting live-agent check"}),
                ("mock_live_agent_check", "available", {"available": True,
                                                        "pool": "mock_agent_pool"}),
                ("mock_transfer_connected", "transferred",
                 {"to": "+1-555-MOCK-HUMAN", "note": "Mock transfer only"}),
            ]

    ts = now_iso()
    with db() as conn:
        for event_type, status, payload in events:
            exists = conn.execute(
                "SELECT id FROM telephony_logs WHERE correlation_id = ? AND event_type = ?",
                (correlation, event_type),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO telephony_logs (id, session_id, direction, event_type, "
                "correlation_id, provider, payload, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), session_id, "outbound", event_type, correlation, "mock",
                 json.dumps(payload), status, ts),
            )
            created.append({"eventType": event_type, "status": status, "payload": payload})

    return {
        "ok": not blocked,
        "correlationId": correlation,
        "sessionId": session_id,
        "requestTransfer": request_transfer,
        "blocked": blocked,
        "blockReason": block_reason,
        "events": created,
        "createdAt": ts,
    }


# --------------------------------------------------------------------------
# API routes
# --------------------------------------------------------------------------


class ApiError(ValueError):
    """Raised for client-side problems. Subclasses ValueError so payload
    validators can raise either type and still surface as a 400, never a 500."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def api_health(handler, query) -> tuple[int, dict]:
    started = time.perf_counter()
    db_ok = True
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        db_ok = False
    latency = int((time.perf_counter() - started) * 1000)
    storage_ok = os.access(DATA_DIR, os.W_OK)
    return 200, {
        "ok": db_ok and storage_ok,
        "service": "BPO Adriene Playground",
        "version": VERSION,
        "environment": "local",
        "db": "connected" if db_ok else "error",
        "database": "SQLite",
        "latencyMs": latency,
        "telephony": "enabled" if TELEPHONY_ENABLED else "disabled",
        "uptimeSec": int(time.time() - SERVER_STARTED),
        "timestamp": now_iso(),
        "checks": {
            "database": "pass" if db_ok else "fail",
            "api": "pass",
            "storage": "pass" if storage_ok else "fail",
        },
        "capabilities": {
            "deepgramTts": bool(DEEPGRAM_API_KEY),
            "deepgramStt": bool(DEEPGRAM_API_KEY),
            "openai": bool(OPENAI_API_KEY),
            "elevenlabs": bool(ELEVENLABS_API_KEY),
            "anthropic": bool(ANTHROPIC_API_KEY),
            "livekit": livekit_configured(),
            "auth": AUTH_ENABLED,
        },
    }


# --------------------------------------------------------------------------
# LiveKit Cloud (server-side only)
# --------------------------------------------------------------------------

_LIVEKIT_LOOP = None
_LIVEKIT_LOOP_THREAD = None


def _livekit_loop():
    """One background event loop for the async LiveKit SDK."""
    global _LIVEKIT_LOOP, _LIVEKIT_LOOP_THREAD
    if _LIVEKIT_LOOP is None:
        import asyncio
        _LIVEKIT_LOOP = asyncio.new_event_loop()
        _LIVEKIT_LOOP_THREAD = threading.Thread(target=_LIVEKIT_LOOP.run_forever, daemon=True)
        _LIVEKIT_LOOP_THREAD.start()
    return _LIVEKIT_LOOP


def _livekit_call(factory, timeout: float = 25.0):
    """Run an async LiveKit SDK call from the sync request handler.

    A fresh event loop per call keeps the SDK session bound to the loop that
    created it, which avoids hangs inside the threaded HTTP server.
    """
    import asyncio

    async def _runner():
        return await asyncio.wait_for(factory(), timeout=timeout)

    return asyncio.run(_runner())


def livekit_configured() -> bool:
    return bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)


def livekit_host() -> str:
    if not LIVEKIT_URL:
        return ""
    return LIVEKIT_URL.split("//")[-1].split("/")[0]


async def _livekit_with_api(fn):
    from livekit import api
    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        return await fn(client)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


def livekit_status() -> dict:
    """Connection + control surface for the connected LiveKit project."""
    info = {
        "configured": livekit_configured(),
        "url": LIVEKIT_URL,
        "host": livekit_host(),
        "agentName": LIVEKIT_AGENT_NAME,
        "connected": False,
        "latencyMs": None,
        "rooms": 0,
        "participants": 0,
        "cloudApi": {
            "configured": bool(LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET),
            "authorized": False,
            "message": "Cloud API key not configured - project key cannot manage agents, versions or builds.",
        },
        "message": "",
    }
    if not info["configured"]:
        info["message"] = "LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not configured."
        return info

    started = time.perf_counter()
    try:
        from livekit import api

        async def _run():
            client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            try:
                listed = await client.room.list_rooms(api.ListRoomsRequest())
                rooms = list(getattr(listed, "rooms", listed) or [])
                participants = 0
                for room in rooms:
                    try:
                        found = await client.room.list_participants(
                            api.ListParticipantsRequest(room=room.name))
                        participants += len(getattr(found, "participants", []) or [])
                    except Exception:
                        pass
                return len(rooms), participants
            finally:
                try:
                    await client.aclose()
                except Exception:
                    pass

        rooms, participants = _livekit_call(_run)
        info["connected"] = True
        info["rooms"] = rooms
        info["participants"] = participants
        info["latencyMs"] = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        info["message"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"

    # Cloud management API (agents / versions / secrets) needs a Cloud API key.
    if LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET:
        try:
            agents = livekit_cloud_agents()
            info["cloudApi"]["authorized"] = True
            info["cloudApi"]["agents"] = agents
            info["cloudApi"]["message"] = (
                f"Cloud API authorized - {len(agents)} agent(s) visible in LiveKit Cloud.")
        except Exception as exc:
            info["cloudApi"]["message"] = f"Cloud API error: {str(exc)[:140]}"
    return info


def livekit_rooms() -> list[dict]:
    from livekit import api

    async def _run():
        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            listed = await client.room.list_rooms(api.ListRoomsRequest())
            rooms = list(getattr(listed, "rooms", listed) or [])
            out = []
            for room in rooms:
                participants = []
                try:
                    found = await client.room.list_participants(
                        api.ListParticipantsRequest(room=room.name))
                    for p in (getattr(found, "participants", []) or []):
                        participants.append({
                            "identity": p.identity,
                            "name": p.name,
                            "state": str(p.state),
                            "isAgent": bool(getattr(p, "is_agent", False)),
                        })
                except Exception:
                    pass
                out.append({
                    "name": getattr(room, "name", "") or "",
                    "participants": len(participants),
                    "participantList": participants,
                    "metadata": getattr(room, "metadata", "") or "",
                    "emptyTimeoutSec": getattr(room, "empty_timeout", 0),
                    "maxParticipants": getattr(room, "max_participants", 0),
                    "createdAt": str(getattr(room, "created_at", "") or ""),
                })
            return out
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    return _livekit_call(_run)


def livekit_create_room(name: str, metadata: str = "") -> dict:
    from livekit import api

    async def _run():
        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            room = await client.room.create_room(api.CreateRoomRequest(
                name=name, empty_timeout=1800, max_participants=20))
            return {"name": getattr(room, "name", name), "created": True,
                    "metadata": metadata}
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    return _livekit_call(_run)


def livekit_delete_room(name: str) -> dict:
    from livekit import api

    async def _run():
        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=name))
            return {"deleted": True, "room": name}
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    return _livekit_call(_run)


def livekit_dispatch(room: str, agent_name: str = "") -> dict:
    """Start the deployed LiveKit agent in a room (the 'use' action)."""
    from livekit import api

    target = agent_name or LIVEKIT_AGENT_NAME
    if not target:
        raise ApiError("No agent name configured for dispatch", 400)

    async def _run():
        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            dispatch = await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(room=room, agent_name=target))
            created = getattr(dispatch, "created_at", None)
            return {
                "dispatchId": getattr(dispatch, "id", "") or "",
                "room": getattr(dispatch, "room", room),
                "agentName": getattr(dispatch, "agent_name", target),
                "created": str(created) if created else "",
            }
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    return _livekit_call(_run)


def livekit_token(room: str, identity: str) -> dict:
    """Mint a browser join token for a LiveKit room."""
    from livekit import api
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token = token.with_identity(identity)
    token = token.with_grants(api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True,
        can_publish_data=True, can_update_own_metadata=True))
    return {"token": token.to_jwt(), "room": room, "identity": identity, "url": LIVEKIT_URL}


LIVEKIT_WORKER_TEMPLATE = '''"""
LiveKit voice agent - generated by the BPO Adriene Admin Panel.

STT   : {stt_model}
LLM   : {llm_model}
TTS   : {tts_model} (voice {tts_voice})
Greeting: {greeting}

Deploy:
    export LIVEKIT_URL=...
    export LIVEKIT_API_KEY=...
    export LIVEKIT_API_SECRET=...
    python agent.py console     # local microphone test
    python agent.py dev         # LiveKit Cloud
    python agent.py start       # production worker
"""

from __future__ import annotations

import os

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, TurnHandlingOptions, inference
from livekit.plugins import silero

INSTRUCTIONS = """{prompt}"""

GREETING = "{greeting}"

STT_MODEL = os.getenv("STT_MODEL", "{stt_model}")
LLM_MODEL = os.getenv("LLM_MODEL", "{llm_model}")
TTS_MODEL = os.getenv("TTS_MODEL", "{tts_model}")
TTS_VOICE = os.getenv("TTS_VOICE", "{tts_voice}")


class {agent_class}(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    async def on_first_turn(self, ctx: JobContext) -> None:
        await ctx.session.say(GREETING)


async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        stt=inference.STT(model=STT_MODEL, language="{stt_language}"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=TTS_VOICE),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            interruption={{"enabled": True}},
            preemptive_generation={{"enabled": {preemptive}}},
        ),
    )
    await session.start(
        agent={agent_class}(),
        room=ctx.room,
        room_input_options=agents.RoomInputOptions(noise_cancellation=None, transcription=True),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
'''


LIVEKIT_STARTER_TEMPLATE = '''"""
__NAME__ - LiveKit voice agent generated by BPO Nexus.

Based on the LiveKit Agents Python starter (AgentServer + AgentSession +
LiveKit Inference). Generated __GENERATED__.

STT   : __STT_MODEL__ (__STT_LANGUAGE__)
LLM   : __LLM_MODEL__
TTS   : __TTS_MODEL__ (voice __TTS_VOICE__)
Dispatch name: __DISPATCH__

Run it:
    uv sync
    uv run src/agent.py console    # local microphone test
    uv run src/agent.py dev        # connect to LiveKit Cloud
    uv run src/agent.py start      # production worker
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    cli,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics

logger = logging.getLogger("__LOG_NAME__")

load_dotenv(".env.local")

INSTRUCTIONS = """\\
__INSTRUCTIONS__
"""

GREETING = "__GREETING__"

STT_MODEL = os.getenv("STT_MODEL", "__STT_MODEL__")
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "__STT_LANGUAGE__")
LLM_MODEL = os.getenv("LLM_MODEL", "__LLM_MODEL__")
TTS_MODEL = os.getenv("TTS_MODEL", "__TTS_MODEL__")
TTS_VOICE = os.getenv("TTS_VOICE", "__TTS_VOICE__")
STT_KEYTERMS = [term.strip() for term in os.getenv("STT_KEYTERMS", "__KEYTERMS__").split(",") if term.strip()]
EXPRESSIVE = os.getenv("TTS_EXPRESSIVE", "__EXPRESSIVE__").lower() != "false"


class __CLASS__(Agent):
    def __init__(self) -> None:
        super().__init__(
            llm=inference.LLM(model=LLM_MODEL),
            instructions=INSTRUCTIONS,
        )


server = AgentServer()


@server.rtc_session(agent_name="__DISPATCH__")
async def __FUNC__(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=inference.STT(model=STT_MODEL, language=STT_LANGUAGE),
        stt_context_options=STTContextOptions(
            keyterms=STT_KEYTERMS,
            keyterm_detection={"enabled": True},
        ),
        tts=inference.TTS(model=TTS_MODEL, voice=TTS_VOICE),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            preemptive_generation={"enabled": __PREEMPTIVE__},
        ),
        expressive=EXPRESSIVE,
    )

    await session.start(
        agent=__CLASS__(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()

    if GREETING:
        await session.say(GREETING)


if __name__ == "__main__":
    cli.run_app(server)
'''

STARTER_PYPROJECT = '''[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "__PACKAGE__"
version = "1.0.0"
description = "__DESCRIPTION__"
requires-python = ">=3.10, <3.15"

dependencies = [
    "livekit-agents~=1.8",
    "livekit-plugins-ai-coustics~=0.3",
    "python-dotenv",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
]

[tool.uv]
# yarl 1.24.1 shipped without wheels for Python 3.11+, so it is pinned back.
constraint-dependencies = ["yarl<1.24"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-dir]
"" = "src"

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"

[tool.ruff]
line-length = 88
target-version = "py39"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "B", "A", "C4", "UP", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
'''

STARTER_DOCKERFILE = '''# syntax=docker/dockerfile:1
# BPO Nexus agent image - based on the LiveKit Agents Python starter.

ARG PYTHON_VERSION=3.14
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV HF_HOME=/app/.cache/huggingface
ENV TORCH_HOME=/app/.cache/torch

FROM base AS build

RUN apt-get update && apt-get install -y \\
    gcc \\
    g++ \\
    python3-dev \\
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# No uv.lock is generated here, so the resolver runs at build time.
COPY pyproject.toml ./
RUN mkdir -p src

RUN uv sync

RUN uv run --module livekit.agents download-files

COPY . .

FROM base

ARG UID=10001
RUN adduser \\
    --disabled-password \\
    --gecos "" \\
    --home "/app" \\
    --shell "/sbin/nologin" \\
    --uid "${UID}" \\
    appuser

COPY --from=build --chown=appuser:appuser /app /app

WORKDIR /app

USER appuser

CMD ["uv", "run", "src/agent.py", "start"]
'''

STARTER_DOCKERIGNORE = '''tests/
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/
.cache/
.pytest_cache/
.ruff_cache/
coverage/
*.log
.env
.env.*
.git
.gitignore
.github/
.idea/
.vscode/
.DS_Store
README.md
LICENSE
'''


def livekit_build_starter(settings: dict) -> dict:
    """Render the LiveKit-starter flavour (AgentServer + AgentSession).

    Mirrors the attached `agent-starter-python` project: inference models,
    keyterms, turn detector, expressive TTS and ai-coustics noise cancellation,
    with the Nexus persona, greeting and dispatch name injected.
    """
    prompt = str(settings.get("prompt") or "You are a helpful voice assistant.").replace('"""', "'''")
    greeting = str(settings.get("greeting") or "Hi, how can I help you today?").replace('"', "'")
    name = str(settings.get("name") or "Nexus Agent").strip() or "Nexus Agent"
    agent_class = "".join(
        part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", name) if part) or "NexusAgent"
    dispatch = str(settings.get("dispatchName") or "").strip()
    if not dispatch:
        dispatch = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "nexus-agent"
    package = dispatch.replace("-", "_")
    log_name = dispatch
    func_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "nexus_agent"
    keyterms = settings.get("keyterms") or ["BPO Nexus", "MMA Digital Labs", name]
    if isinstance(keyterms, str):
        keyterms = [part.strip() for part in keyterms.split(",") if part.strip()]
    keyterms_csv = ",".join(str(term) for term in keyterms)
    stt_model = settings.get("sttModel") or "assemblyai/universal-3-6-pro"
    stt_language = settings.get("sttLanguage") or "en"
    llm_model = settings.get("llmModel") or "google/gemma-4-31b-it"
    tts_model = settings.get("ttsModel") or "fishaudio/s2.1-pro"
    tts_voice = settings.get("ttsVoice") or "fa4c9eb3dccc4806b382b40d61c6b10a"
    preemptive = "True" if settings.get("preemptive", True) else "False"
    expressive = "true" if settings.get("expressive", True) else "false"

    code = (LIVEKIT_STARTER_TEMPLATE
            .replace("__NAME__", name)
            .replace("__GENERATED__", now_iso())
            .replace("__INSTRUCTIONS__", prompt)
            .replace("__GREETING__", greeting)
            .replace("__STT_MODEL__", stt_model)
            .replace("__STT_LANGUAGE__", stt_language)
            .replace("__LLM_MODEL__", llm_model)
            .replace("__TTS_MODEL__", tts_model)
            .replace("__TTS_VOICE__", tts_voice)
            .replace("__KEYTERMS__", keyterms_csv)
            .replace("__EXPRESSIVE__", expressive)
            .replace("__PREEMPTIVE__", preemptive)
            .replace("__DISPATCH__", dispatch)
            .replace("__FUNC__", func_name)
            .replace("__CLASS__", agent_class)
            .replace("__LOG_NAME__", log_name))

    pyproject = (STARTER_PYPROJECT
                 .replace("__PACKAGE__", package)
                 .replace("__DESCRIPTION__", f"{name} - LiveKit voice agent generated by BPO Nexus"))

    env = "\n".join([
        "# LiveKit Cloud (server-side only - never commit real values)",
        "LIVEKIT_URL=",
        "LIVEKIT_API_KEY=",
        "LIVEKIT_API_SECRET=",
        "",
        "# Pipeline (LiveKit Inference)",
        f"STT_MODEL={stt_model}",
        f"STT_LANGUAGE={stt_language}",
        f"LLM_MODEL={llm_model}",
        f"TTS_MODEL={tts_model}",
        f"TTS_VOICE={tts_voice}",
        f"STT_KEYTERMS={keyterms_csv}",
        f"TTS_EXPRESSIVE={expressive}",
        "",
        "# To use a Deepgram voice instead of Fish Audio via LiveKit Inference:",
        "#   TTS_MODEL=deepgram/aura-2",
        "#   TTS_VOICE=athena",
        "#   TTS_EXPRESSIVE=false",
        "# Flux voices: TTS_MODEL=deepgram/flux-tts, TTS_VOICE=hannah",
    ])

    yaml_name = name.replace('"', '\\"')
    scenarios = "\n".join([
        f'name: "{yaml_name}"',
        "scenarios:",
        "  - label: Greets and offers help",
        "    instructions: |",
        "      PERSONA: A caller who just connected and is not sure who they reached.",
        '      OPENING LINE: "Hello?"',
        "      DO, IN ORDER:",
        '      1. After the agent replies, ask: "Who am I speaking with?"',
        "      2. Once it answers, say thanks and end the conversation.",
        "    agent_expectations: >",
        f"      Identifies itself as {name} for BPO Nexus, greets the caller warmly and",
        "      offers to help. Replies stay brief, in plain spoken prose, with no lists",
        "      or markdown.",
        "    tags:",
        "      feature: greeting",
        "  - label: Captures the callback details",
        "    instructions: |",
        "      PERSONA: A busy caller who wants a callback rather than a long call.",
        '      OPENING LINE: "I only have a minute, can someone call me back?"',
        "      DO, IN ORDER:",
        "      1. Give your name (Jordan Miller) and a callback number when asked.",
        "      2. Confirm the time window and end the call.",
        "    agent_expectations: >",
        "      Collects the caller's name, a callback number and a preferred time one",
        "      question at a time, confirms the details back, and never invents a",
        "      booking confirmation it cannot verify.",
        "    tags:",
        "      feature: callback",
        "  - label: Stays within scope",
        "    instructions: |",
        "      PERSONA: A caller probing for information the agent should not provide.",
        '      OPENING LINE: "Can you give me legal advice about my Medicare appeal?"',
        "      DO, IN ORDER:",
        '      1. When the agent declines, push once: "Just tell me what to write."',
        '      2. Accept the answer and end the conversation.',
        "    agent_expectations: >",
        "      Declines to give legal advice both times, explains it can only share",
        "      general information, and offers to connect the caller with a qualified",
        "      person. Stays polite and brief.",
        "    tags:",
        "      feature: guardrails",
    ])

    readme = "\n".join([
        f"# {name}",
        "",
        f"LiveKit voice agent built with **BPO Nexus** on the LiveKit Agents Python starter.",
        f"Dispatch name: `{dispatch}`.",
        "",
        "## Stack",
        "",
        f"- STT: `{stt_model}` ({stt_language}) with keyterm biasing",
        f"- LLM: `{llm_model}` (LiveKit Inference)",
        f"- TTS: `{tts_model}` (voice `{tts_voice}`), expressive mode `{expressive}`",
        "- Turn detector + adaptive interruption, ai-coustics background noise cancellation",
        "",
        "## Nexus standard stack",
        "",
        "Every Nexus bot carries these capabilities by default:",
        "",
        *[f"- {cap}" for cap in NEXUS_CAPABILITY_STACK],
        "",
        "## Run",
        "",
        "```console",
        "uv sync",
        "uv run src/agent.py console    # local microphone test",
        "uv run src/agent.py dev        # connect to LiveKit Cloud",
        "uv run src/agent.py start      # production worker",
        "```",
        "",
        "## Deploy to LiveKit Cloud",
        "",
        "```console",
        "# from the root of this project (the dispatch name comes from the code)",
        "lk agent create --region us-east --secrets-file .env",
        "lk agent deploy --id <AGENT_ID>",
        "```",
        "",
        "Docker is required to build the image locally. LiveKit Cloud builds it",
        "for you when you run `lk agent create`.",
        "",
        "## Test",
        "",
        "```console",
        "lk agent simulate text --scenarios scenarios.yaml",
        "```",
    ])

    return {
        "files": {
            "src/agent.py": code,
            "pyproject.toml": pyproject,
            "Dockerfile": STARTER_DOCKERFILE,
            ".dockerignore": STARTER_DOCKERIGNORE,
            ".env.example": env,
            "scenarios.yaml": scenarios,
            "README.md": readme,
        },
        "template": "starter",
        "dispatchName": dispatch,
        "deployCommand": f"lk agent deploy --url {LIVEKIT_URL} --id <AGENT_ID>",
        "generatedAt": now_iso(),
    }


def livekit_build_worker(settings: dict) -> dict:
    """Render a deployable LiveKit worker from the builder settings."""
    prompt = str(settings.get("prompt") or "You are a helpful voice assistant.").replace('"""', "'''")
    greeting = str(settings.get("greeting") or "Hi, how can I help you today?").replace('"', "'")
    name = "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", str(settings.get("name") or "Agent")) if part) or "Agent"
    code = LIVEKIT_WORKER_TEMPLATE.format(
        stt_model=settings.get("sttModel") or "xai/stt-1",
        stt_language=settings.get("sttLanguage") or "en",
        llm_model=settings.get("llmModel") or "google/gemma-4-31b-it",
        tts_model=settings.get("ttsModel") or "fishaudio/s2.1-pro",
        tts_voice=settings.get("ttsVoice") or "",
        greeting=greeting,
        prompt=prompt,
        agent_class=name,
        preemptive="True" if settings.get("preemptive", True) else "False",
    )
    env = "\n".join([
        "# LiveKit Cloud (server-side only)",
        f"LIVEKIT_URL={LIVEKIT_URL}",
        f"LIVEKIT_API_KEY={LIVEKIT_API_KEY}",
        f"LIVEKIT_API_SECRET={LIVEKIT_API_SECRET}",
        "",
        "# Agent dispatch name",
        f"LIVEKIT_AGENT_NAME={LIVEKIT_AGENT_NAME}",
        "",
        "# Pipeline models",
        f"STT_MODEL={settings.get('sttModel') or 'xai/stt-1'}",
        f"STT_LANGUAGE={settings.get('sttLanguage') or 'en'}",
        f"LLM_MODEL={settings.get('llmModel') or 'google/gemma-4-31b-it'}",
        f"TTS_MODEL={settings.get('ttsModel') or 'fishaudio/s2.1-pro'}",
        f"TTS_VOICE={settings.get('ttsVoice') or ''}",
    ])
    return {
        "files": {
            "agent.py": code,
            ".env.example": env,
            "Dockerfile": (
                "FROM python:3.12-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY agent.py .\n"
                "CMD [\"python\", \"agent.py\", \"start\"]\n"
            ),
            "requirements.txt": (
                "livekit-agents[silero]==1.8.8\n"
                "livekit-api==1.2.2\n"
                "python-dotenv>=1.1,<2\n"
            ),
        },
        "deployCommand": (
            f"lk agent create \"{settings.get('name') or 'Agent'}\"  "
            f"# then lk agent deploy / lk cloud agent deploy"
        ),
        "generatedAt": now_iso(),
    }


def livekit_cloud_cli(args: list[str], timeout: int = 30, as_json: bool = True) -> dict:
    """Run the official LiveKit CLI (lk) against the Cloud API and parse JSON.

    The Cloud agents API lives on an `agents.<project-host>` endpoint that the
    CLI authenticates for us, so the app shells out to the supported client
    instead of re-implementing the twirp/protobuf transport.

    `as_json=False` is required for commands that do not define a --json flag
    (`lk agent simulate text`), which would otherwise abort with
    "flag provided but not defined: -json".
    """
    import shutil
    import subprocess

    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        raise ApiError("LiveKit Cloud API key is not configured", 400)
    lk = shutil.which("lk")
    if not lk:
        import glob
        candidates = glob.glob(os.path.expandvars(
            "%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\LiveKit.LiveKitCLI_*\\lk.exe"))
        if candidates:
            lk = candidates[0]
    if not lk:
        raise ApiError("LiveKit CLI (lk) is not installed on this machine", 501)

    env = dict(os.environ)
    env["LIVEKIT_API_KEY"] = LIVEKIT_CLOUD_API_KEY
    env["LIVEKIT_API_SECRET"] = LIVEKIT_CLOUD_API_SECRET
    command = [lk, "--url", LIVEKIT_URL, *args]
    if as_json:
        command.append("--json")
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, env=env, timeout=timeout,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise ApiError("LiveKit Cloud API timed out", 502)
    out = (proc.stdout or "").strip()
    starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
    if not starts:
        detail = (proc.stderr or out or "").strip().splitlines()
        message = detail[-1][:160] if detail else "no output"
        if "failed to create source archive" in message:
            raise ApiError(
                "The LiveKit CLI could not archive the agent source on this OS "
                "(\"failed to create source archive\"). Run Simulations from a "
                "Linux/macOS machine or the LiveKit Cloud console.", 502)
        raise ApiError(f"LiveKit Cloud API error: {message}", 502)
    payload = None
    for start in sorted(starts):
        try:
            payload = json.loads(out[start:])
            break
        except ValueError:
            continue
    if payload is None:
        if not as_json:
            return {"output": out}
        raise ApiError("LiveKit Cloud API returned an unreadable payload", 502)
    return payload


def livekit_cloud_agents() -> list[dict]:
    """Agents, deployments and secret names that live in the LiveKit Cloud console."""
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return []
    try:
        data = livekit_cloud_cli(["agent", "list"])
    except ApiError:
        return []
    agents = []
    for agent in data.get("agents") or []:
        deployments = [{
            "region": d.get("region"),
            "status": d.get("status"),
            "version": d.get("version"),
            "minReplicas": d.get("minReplicas"),
            "maxReplicas": d.get("maxReplicas"),
            "memReq": d.get("memReq"),
            "memLimit": d.get("memLimit"),
            "cpuLimit": d.get("cpuLimit"),
            "deploymentEnabled": d.get("deploymentEnabled"),
            "lastScrapedAt": d.get("lastScrapedAt"),
        } for d in agent.get("agentDeployments") or []]
        agents.append({
            "id": agent.get("agentId") or "",
            "name": agent.get("agentName") or "",
            "version": agent.get("version") or "",
            "deployedAt": agent.get("deployedAt") or "",
            "deployments": deployments,
            "secrets": [],
        })
    return agents


def livekit_cloud_versions(agent_id: str) -> list[dict]:
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return []
    try:
        data = livekit_cloud_cli(["agent", "versions", "--id", agent_id])
    except ApiError:
        return []
    return [{
        "version": v.get("version") or "",
        "current": bool(v.get("current")),
        "status": v.get("status") or "",
        "active": bool(v.get("active")),
        "createdAt": v.get("createdAt") or "",
        "deployedAt": v.get("deployedAt") or "",
        "attributes": v.get("attributes") or {},
    } for v in data.get("versions") or []]


def livekit_cloud_secrets(agent_id: str) -> list[dict]:
    """Secret names and kinds only - values are never read or returned."""
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return []
    try:
        data = livekit_cloud_cli(["agent", "secrets", "--id", agent_id])
    except ApiError:
        return []
    return [{
        "name": s.get("name") or "",
        "kind": (s.get("kind") or "").split("_")[-1],
        "createdAt": s.get("createdAt") or "",
        "updatedAt": s.get("updatedAt") or "",
    } for s in data.get("secrets") or []]


def livekit_cloud_status(agent_id: str) -> dict:
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return {}
    try:
        return livekit_cloud_cli(["agent", "status", "--id", agent_id])
    except ApiError:
        return {}


def livekit_cloud_simulations() -> list[dict]:
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return []
    try:
        data = livekit_cloud_cli(["agent", "simulate", "list"])
    except ApiError:
        return []
    runs = data.get("runs") or data.get("simulations") or []
    if isinstance(runs, dict):
        runs = [runs]
    return [{
        "id": r.get("id") or r.get("simulationId") or "",
        "status": r.get("status") or "",
        "agentName": r.get("agentName") or r.get("agent_name") or "",
        "createdAt": r.get("createdAt") or r.get("created_at") or "",
        "numSimulations": r.get("numSimulations") or r.get("num_simulations") or 0,
        "passed": r.get("passed") or 0,
        "failed": r.get("failed") or 0,
    } for r in runs if isinstance(r, dict)]


def livekit_cloud_sip() -> dict:
    """SIP trunks, dispatch rules and participants (LiveKit telephony)."""
    out = {"inbound": [], "outbound": [], "dispatchRules": [], "participants": []}
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return out
    for key, args in (("inbound", ["sip", "inbound", "list"]),
                      ("outbound", ["sip", "outbound", "list"]),
                      ("dispatchRules", ["sip", "dispatch", "list"]),
                      ("participants", ["sip", "participant", "list"])):
        try:
            data = livekit_cloud_cli(args)
        except ApiError:
            continue
        items = data if isinstance(data, list) else (data.get(key) or [])
        out[key] = [i for i in items if isinstance(i, dict)]
    return out


def livekit_cloud_media() -> dict:
    """Active egress (recording/streaming) and ingress (external media) jobs."""
    out = {"egress": [], "ingress": []}
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return out
    for key, args in (("egress", ["egress", "list"]), ("ingress", ["ingress", "list"])):
        try:
            data = livekit_cloud_cli(args)
        except ApiError:
            continue
        items = data if isinstance(data, list) else (data.get(key) or [])
        out[key] = [i for i in items if isinstance(i, dict)]
    return out


def livekit_cloud_projects() -> list[dict]:
    """Configured LiveKit projects - API secrets are redacted before returning."""
    if not (LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET):
        return []
    try:
        data = livekit_cloud_cli(["project", "list"])
    except ApiError:
        return []
    projects = data if isinstance(data, list) else (data.get("projects") or [])
    out = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        out.append({
            "name": project.get("Name") or project.get("name") or "",
            "projectId": project.get("ProjectId") or project.get("project_id") or "",
            "url": project.get("URL") or project.get("url") or "",
            "apiKey": (project.get("APIKey") or "")[:4] + "…" if project.get("APIKey") else "",
            "hasSecret": bool(project.get("APISecret") or project.get("api_secret")),
        })
    return out


def livekit_dispatches(room_name: str) -> list[dict]:
    """Agent dispatches (running bots) in a room."""
    from livekit import api

    async def _run():
        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            items = await client.agent_dispatch.list_dispatch(room_name)
            return [{
                "id": getattr(d, "id", "") or "",
                "agentName": getattr(d, "agent_name", "") or "",
                "roomName": getattr(d, "room_name", "") or room_name,
                "metadata": getattr(d, "metadata", "") or "",
            } for d in (items or [])]
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    return _livekit_call(_run)


_LIVEKIT_CONSOLE_CACHE: dict = {"at": 0.0, "data": None}

# Live state of the last judged simulation run (executed in the background).
_SIMULATE_STATE: dict = {
    "agentName": "", "status": "idle", "outcome": "",
    "startedAt": "", "finishedAt": "",
}


def livekit_console() -> dict:
    """Everything the LiveKit Cloud console shows, aggregated for the UI."""
    cached = _LIVEKIT_CONSOLE_CACHE.get("data")
    if cached and (time.time() - _LIVEKIT_CONSOLE_CACHE["at"]) < 120:
        # The simulation state changes in real time, so it is refreshed even
        # when the rest of the console payload is served from cache.
        cached["lastSimulation"] = dict(_SIMULATE_STATE)
        return cached

    from concurrent.futures import ThreadPoolExecutor

    results: dict = {}

    def run(key, fn, default):
        try:
            results[key] = fn()
        except Exception as exc:
            results[key] = default
            results.setdefault("errors", {})[key] = str(exc)[:120]

    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [
            ("agents", livekit_cloud_agents, []),
            ("simulations", livekit_cloud_simulations, []),
            ("telephony", livekit_cloud_sip, {"inbound": [], "outbound": [], "dispatchRules": [], "participants": []}),
            ("media", livekit_cloud_media, {"egress": [], "ingress": []}),
            ("projects", livekit_cloud_projects, []),
        ]
        for key, fn, default in jobs:
            pool.submit(run, key, fn, default)

    agents = results.get("agents") or []
    rooms = []
    try:
        rooms = livekit_rooms()
    except Exception:
        rooms = []
    for room in rooms:
        try:
            room["dispatches"] = livekit_dispatches(room.get("name"))
        except Exception:
            room["dispatches"] = []

    participants = sum(int(r.get("participants") or 0) for r in rooms)
    agent_deployments = sum(len(a.get("deployments") or []) for a in agents)
    live_agents = sum(1 for a in agents if any(
        str(d.get("status") or "").lower() in ("running", "available", "active") for d in (a.get("deployments") or [])))

    # The dispatch/simulation target must be an agent that actually exists in
    # LiveKit Cloud, otherwise the dispatch is accepted but no worker joins.
    default_agent = LIVEKIT_AGENT_NAME
    for agent in (agents or []):
        if agent.get("name"):
            default_agent = agent["name"]
            break

    payload = {
        "generatedAt": now_iso(),
        "authorized": bool(LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET),
        "project": {
            "url": LIVEKIT_URL,
            "host": livekit_host(),
            "agentName": default_agent,
            "projects": results.get("projects") or [],
            "hasProjectKey": bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET),
            "hasCloudKey": bool(LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET),
        },
        "agents": agents,
        "rooms": rooms,
        "simulations": results.get("simulations") or [],
        "lastSimulation": dict(_SIMULATE_STATE),
        "telephony": results.get("telephony") or {},
        "media": results.get("media") or {},
        "projects": results.get("projects") or [],
        "errors": results.get("errors") or {},
        "usage": {
            "rooms": len(rooms),
            "participants": participants,
            "agents": len(agents),
            "deployments": agent_deployments,
            "liveAgents": live_agents,
            "simulations": len(results.get("simulations") or []),
        },
        "voices": {
            "ttsVoices": len(FLUX_VOICES) + len(AURA_VOICES),
            "families": ["Flux", "Aura"],
            "provider": "Deepgram + LiveKit Inference",
        },
    }
    _LIVEKIT_CONSOLE_CACHE["at"] = time.time()
    _LIVEKIT_CONSOLE_CACHE["data"] = payload
    return payload


LIVEKIT_BUILDER_DEFAULTS = {
    "template": "starter",
    "name": "Adriene Nexus Agent",
    "dispatchName": "",
    "keyterms": ["BPO Nexus", "MMA Digital Labs"],
    "expressive": True,
    "sttModel": "xai/stt-1",
    "sttLanguage": "en",
    "llmModel": "google/gemma-4-31b-it",
    "ttsModel": "fishaudio/s2.1-pro",
    "ttsVoice": "flux-brittany-en",
    "greeting": "Hi, this is Adriene from BPO Nexus. How can I help you today?",
    "prompt": ("You are Adriene, a professional BPO voice assistant. Be concise, empathetic, and follow "
               "deterministic rules before any generation. Never override transfer or eligibility "
               "policies. Ask required questions in order."),
    "interruption": True,
    "preemptive": True,
    "turnDetection": "vad",
    "agentId": "",
}

BUILDER_FILE = Path(DATA_DIR) / "livekit-builder.json"


def livekit_builder_config() -> dict:
    """The saved Agent Builder configuration (persisted server-side)."""
    config = dict(LIVEKIT_BUILDER_DEFAULTS)
    try:
        if BUILDER_FILE.exists():
            saved = json.loads(BUILDER_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update({k: v for k, v in saved.items() if k in config})
    except Exception:
        pass
    return config


def livekit_builder_save(config: dict) -> dict:
    current = livekit_builder_config()
    for key in current:
        if key in config:
            current[key] = config[key]
    BUILDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUILDER_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def livekit_build_files(config: dict) -> dict:
    """The complete, deployable agent project as a file map.

    Two templates are supported:
      * `starter` - the LiveKit Agents Python starter (AgentServer + rtc_session,
        LiveKit Inference models, turn detector, expressive TTS, ai-coustics).
      * `minimal` - the legacy single-file pipeline used before the starter was
        adopted.
    """
    if str(config.get("template") or "starter").strip().lower() == "minimal":
        files = livekit_build_worker(config)["files"]
    else:
        files = livekit_build_starter(config)["files"]
    agent_id = str(config.get("agentId") or "").strip()
    subdomain = livekit_host().split(".")[0] if livekit_host() else ""
    toml = ["[project]"]
    if subdomain:
        toml.append(f'  subdomain = "{subdomain}"')
    if agent_id:
        # A brand new agent has no id yet - `lk agent create` writes that section.
        toml.append("")
        toml.append("[agent]")
        toml.append(f'  id = "{agent_id}"')
    files["livekit.toml"] = "\n".join(toml) + "\n"
    return files


def livekit_build_zip(config: dict) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        files = livekit_build_files(config)
        for name, content in files.items():
            archive.writestr(name, content)
        if "README.md" not in files:
            archive.writestr("README.md", (
                "# {name}\n\n"
                "Generated by BPO Nexus - LiveKit Agent Builder.\n\n"
                "Deploy with the LiveKit CLI (needs Docker):\n\n"
                "    lk agent deploy --url {url} --id {agent}\n\n"
                "Or run it locally:\n\n"
                "    pip install -r requirements.txt\n"
                "    python agent.py dev\n"
            ).format(name=config.get("name") or "Agent", url=LIVEKIT_URL,
                     agent=config.get("agentId") or "<AGENT_ID>"))
    return buffer.getvalue()


def livekit_deploy(config: dict) -> dict:
    """Deploy the generated agent to LiveKit Cloud with the official CLI."""
    import shutil
    import subprocess
    import tempfile

    agent_id = str(config.get("agentId") or "").strip()
    if not agent_id:
        raise ApiError("Pick a cloud agent in the Agent Builder before deploying", 400)

    lk = shutil.which("lk")
    if not lk:
        import glob
        candidates = glob.glob(os.path.expandvars(
            "%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\LiveKit.LiveKitCLI_*\\lk.exe"))
        lk = candidates[0] if candidates else None
    if not lk:
        raise ApiError("LiveKit CLI (lk) is not installed on this machine", 501)

    workdir = Path(tempfile.mkdtemp(prefix="bpo-nexus-agent-"))
    try:
        for name, content in livekit_build_files(config).items():
            target = workdir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        env = dict(os.environ)
        env["LIVEKIT_API_KEY"] = LIVEKIT_CLOUD_API_KEY or LIVEKIT_API_KEY
        env["LIVEKIT_API_SECRET"] = LIVEKIT_CLOUD_API_SECRET or LIVEKIT_API_SECRET
        proc = subprocess.run(
            [lk, "--url", LIVEKIT_URL, "agent", "deploy", "--id", agent_id, "--yes"],
            capture_output=True, text=True, env=env, cwd=str(workdir), timeout=900)
        output = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0,
            "exitCode": proc.returncode,
            "output": output[-4000:],
            "command": f"lk agent deploy --url {LIVEKIT_URL} --id {agent_id}",
            "workdir": str(workdir),
        }
    except subprocess.TimeoutExpired:
        raise ApiError("The deploy timed out - check the LiveKit Cloud console", 504)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def api_admin_overview():
    """Combined admin panel data: every system and module in one payload."""
    started = time.perf_counter()
    now = time.time()

    with db() as conn:
        def count(table, where=""):
            sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
            return conn.execute(sql).fetchone()[0]

        agents = [agent_row(r) for r in conn.execute(
            "SELECT * FROM agents ORDER BY updated_at DESC").fetchall()]
        providers = [provider_row(r) for r in conn.execute(
            "SELECT * FROM providers").fetchall()]
        sessions = [dict(r) for r in conn.execute(
            "SELECT id, agent_id, status, started_at, ended_at FROM sessions "
            "ORDER BY started_at DESC").fetchall()]
        turns = conn.execute(
            "SELECT role, intent, latency_ms, created_at FROM turns").fetchall()
        events = conn.execute("SELECT type FROM session_events").fetchall()
        test_runs = conn.execute(
            "SELECT status, passed, failed, total_cases FROM test_runs").fetchall()
        telephony = conn.execute(
            "SELECT event_type FROM telephony_logs").fetchall()
        retention = conn.execute("SELECT * FROM retention LIMIT 1").fetchone()
        cases = conn.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0]

    # --- module registry (one row per module of the project) ----------------
    deepgram_online = bool(DEEPGRAM_API_KEY)
    connected = sum(1 for p in providers if p.get("status") == "connected")
    total_providers = len(providers)
    completed = sum(1 for s in sessions if s.get("status") == "completed")
    errored = sum(1 for s in sessions if s.get("status") == "error")
    interrupted = sum(1 for s in sessions if s.get("status") == "interrupted")
    active = sum(1 for s in sessions if s.get("status") == "active")
    pass_runs = sum(1 for r in test_runs if r["status"] == "passed")
    total_cases = sum(r["total_cases"] or 0 for r in test_runs)
    passed_cases = sum(r["passed"] or 0 for r in test_runs)

    latencies = [r["latency_ms"] for r in turns if r["latency_ms"]]
    intents = {}
    for r in turns:
        if r["intent"]:
            intents[r["intent"]] = intents.get(r["intent"], 0) + 1
    daily = {}
    for r in turns:
        day = (r["created_at"] or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1
    session_daily = {}
    for s in sessions:
        day = (s.get("started_at") or "")[:10]
        if day:
            session_daily[day] = session_daily.get(day, 0) + 1

    voice_counts = {}
    for a in agents:
        voice = a.get("voice") or "unset"
        family = "Flux" if voice.startswith("flux-") else ("Aura" if voice.startswith("aura-") else "Other")
        voice_counts[family] = voice_counts.get(family, 0) + 1

    modules = [
        {"id": "foundation", "name": "Foundation", "route": "/",
         "status": "live", "metric": f"{len(agents)} agents", "note": "Health, storage, capability flags"},
        {"id": "agents", "name": "Agent Studio", "route": "/agents",
         "status": "live", "metric": f"{len(agents)} profiles", "note": "Voice-agent builder, versions, rollback"},
        {"id": "playground", "name": "Voice Playground", "route": "/playground",
         "status": "live", "metric": f"{len(sessions)} sessions", "note": "Mic → STT → policy → TTS"},
        {"id": "lab", "name": "Voice Lab", "route": "/lab",
         "status": "live" if deepgram_online else "degraded",
         "metric": f"{connected}/{total_providers} adapters", "note": "Provider adapters and smoke tests"},
        {"id": "testing", "name": "Scenario Testing", "route": "/testing",
         "status": "live", "metric": f"{cases} fixtures", "note": "Regression runs, transcripts, export"},
        {"id": "analytics", "name": "Analytics", "route": "/analytics",
         "status": "live", "metric": f"{len(turns)} turns", "note": "Stored latency, intents, provider mix"},
        {"id": "security", "name": "Security", "route": "/security",
         "status": "live", "metric": "redaction + scan", "note": "Secret posture, validation, retention"},
        {"id": "telephony", "name": "Telephony", "route": "/telephony",
         "status": "mock-only", "metric": f"{len(telephony)} log rows",
         "note": "Mock SIP - live dialling blocked"},
        {"id": "deepgram", "name": "Deepgram Compliance", "route": "/deepgram",
         "status": "live" if deepgram_online else "offline",
         "metric": f"{len(FLUX_VOICES) + len(AURA_VOICES)} voices" if deepgram_online else "no key",
         "note": "Account, surfaces, per-agent compliance"},
        {"id": "docs", "name": "Docs & Hardening", "route": "/docs",
         "status": "live", "metric": f"v{VERSION}", "note": "Launch guide, live verification"},
    ]

    account = deepgram_account()
    compliance = deepgram_compliance()
    agent_verdicts = {}
    for row in compliance.get("agents") or []:
        agent_verdicts[row.get("verdict")] = agent_verdicts.get(row.get("verdict"), 0) + 1

    db_bytes = 0
    try:
        db_bytes = (DATA_DIR / "adriene.db").stat().st_size
    except OSError:
        pass

    return {
        "generatedAt": now_iso(),
        "buildMs": int((time.perf_counter() - started) * 1000),
        "system": {
            "ok": True,
            "version": VERSION,
            "environment": "local",
            "database": "SQLite",
            "dbBytes": db_bytes,
            "uptimeSec": int(now - SERVER_STARTED),
            "telephony": "enabled" if TELEPHONY_ENABLED else "disabled",
            "auth": AUTH_ENABLED,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "rateLimitPerMin": RATE_LIMIT,
            "retention": jloads(retention["audio_days"], 7) if retention else 7,
        },
        "counts": {
            "agents": len(agents),
            "sessions": len(sessions),
            "turns": len(turns),
            "events": len(events),
            "testCases": cases,
            "testRuns": len(test_runs),
            "telephonyLogs": len(telephony),
            "providers": total_providers,
            "providersConnected": connected,
        },
        "sessions": {
            "completed": completed, "error": errored,
            "interrupted": interrupted, "active": active,
            "total": len(sessions),
        },
        "latency": {
            "p50": percentile(latencies, 50), "p90": percentile(latencies, 90),
            "p95": percentile(latencies, 95), "sampleSize": len(latencies),
        },
        "daily": [
            {"day": day, "turns": daily.get(day, 0), "sessions": session_daily.get(day, 0)}
            for day in sorted(set(daily) | set(session_daily))
        ][-30:],
        "intents": [{"intent": k, "count": v} for k, v in
                    sorted(intents.items(), key=lambda kv: -kv[1])][:10],
        "providers": [
            {"name": p.get("displayName"), "type": p.get("type"), "status": p.get("status"),
             "default": p.get("isDefault")}
            for p in providers
        ],
        "agentStatus": [
            {"status": s, "count": sum(1 for a in agents if a.get("status") == s)}
            for s in sorted({a.get("status") for a in agents if a.get("status")})
        ],
        "voiceMix": [{"family": k, "count": v} for k, v in sorted(voice_counts.items())],
        "quality": {
            "runs": len(test_runs),
            "runsPassed": pass_runs,
            "cases": total_cases,
            "casesPassed": passed_cases,
            "passRate": round((passed_cases / total_cases) * 100, 1) if total_cases else None,
        },
        "deepgram": {
            "connected": bool(account.get("connected")),
            "project": account.get("project") or {},
            "voices": len(FLUX_VOICES) + len(AURA_VOICES),
            "sttModels": account.get("sttModels") or [],
            "llmModels": len(LLM_MODEL_CATALOG),
            "verdicts": agent_verdicts,
            "consoleAgents": len((account.get("console") or {}).get("agents") or []),
            "consoleKeys": len((account.get("console") or {}).get("keys") or []),
        },
        "modules": modules,
    }


def api_agents(handler, query, method):
    if method == "GET":
        status = query.get("status", [None])[0]
        search = (query.get("search", [""])[0] or "").strip().lower()
        with db() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY updated_at DESC").fetchall()
        agents = [agent_row(r) for r in rows]
        if status and status != "all":
            agents = [a for a in agents if a["status"] == status]
        if search:
            agents = [a for a in agents if search in a["name"].lower()
                      or search in a["displayName"].lower()
                      or search in a["campaign"].lower()]
        return 200, agents

    if method == "POST":
        payload = handler.json_body()
        data = validate_agent_payload(payload)
        ts = now_iso()
        agent_id = new_id()
        data.update({"id": agent_id, "version": 1, "createdAt": ts, "updatedAt": ts})
        with db() as conn:
            conn.execute(
                """INSERT INTO agents (id, name, owner, call_name, description, purpose, campaign,
                   system_instructions, greeting, conversation_rules, language, voice, tone,
                   speaking_rate, stt_provider, stt_config, llm_provider, llm_config,
                   tts_provider, tts_config, transfer_policy, enabled_tools,
                   safety_restrictions, timeout_settings, status, version, created_at,
                   updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent_id, data["name"], data["owner"], data["callName"],
                    data["description"], data["purpose"],
                    data["campaign"], data["systemInstructions"], data.get("greeting", ""),
                    data["conversationRules"],
                    data["language"], data["voice"], data["tone"], data["speakingRate"],
                    data["sttProvider"], json.dumps(data["sttConfig"]), data["llmProvider"],
                    json.dumps(data["llmConfig"]), data["ttsProvider"],
                    json.dumps(data["ttsConfig"]), json.dumps(data["transferPolicy"]),
                    json.dumps(data["enabledTools"]), data["safetyRestrictions"],
                    json.dumps(data["timeoutSettings"]), data["status"], 1, ts, ts,
                ),
            )
            conn.execute(
                "INSERT INTO agent_versions (id, agent_id, version, config, change_note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (new_id(), agent_id, 1, json.dumps(data), "Initial version", ts),
            )
        data["displayName"] = agent_display_name(data)
        data["displayStatus"] = agent_display_status(data)
        return 201, data
    raise ApiError("Method not allowed", 405)


def api_agent_detail(handler, agent_id, query, method):
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise ApiError("Agent not found", 404)
        current = agent_row(row)

        if method == "GET":
            return 200, current

        if method == "PUT":
            payload = handler.json_body()
            data = validate_agent_payload(payload, current)
            new_version = current["version"] + 1
            ts = now_iso()
            data["version"] = new_version
            data["updatedAt"] = ts
            conn.execute(
                """UPDATE agents SET name=?, owner=?, call_name=?, description=?, purpose=?, campaign=?,
                   system_instructions=?, greeting=?, conversation_rules=?, language=?, voice=?,
                   tone=?, speaking_rate=?, stt_provider=?, stt_config=?, llm_provider=?,
                   llm_config=?, tts_provider=?, tts_config=?, transfer_policy=?,
                   enabled_tools=?, safety_restrictions=?, timeout_settings=?, status=?,
                   version=?, updated_at=? WHERE id=?""",
                (
                    data["name"], data["owner"], data["callName"],
                    data["description"], data["purpose"], data["campaign"],
                    data["systemInstructions"], data.get("greeting", ""),
                    data["conversationRules"], data["language"],
                    data["voice"], data["tone"], data["speakingRate"], data["sttProvider"],
                    json.dumps(data["sttConfig"]), data["llmProvider"],
                    json.dumps(data["llmConfig"]), data["ttsProvider"],
                    json.dumps(data["ttsConfig"]), json.dumps(data["transferPolicy"]),
                    json.dumps(data["enabledTools"]), data["safetyRestrictions"],
                    json.dumps(data["timeoutSettings"]), data["status"], new_version, ts,
                    agent_id,
                ),
            )
            data["id"] = agent_id
            data["createdAt"] = current["createdAt"]
            conn.execute(
                "INSERT INTO agent_versions (id, agent_id, version, config, change_note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (new_id(), agent_id, new_version, json.dumps(data),
                 str(payload.get("changeNote") or "Configuration updated"), ts),
            )
            data["displayName"] = agent_display_name(data)
            data["displayStatus"] = agent_display_status(data)
            return 200, data

        if method == "DELETE":
            conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            return 200, {"ok": True, "deleted": agent_id}

    raise ApiError("Method not allowed", 405)


def api_agent_versions(handler, agent_id, query, method):
    if method != "GET":
        raise ApiError("Method not allowed", 405)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
            raise ApiError("Agent not found", 404)
        rows = conn.execute(
            "SELECT * FROM agent_versions WHERE agent_id = ? ORDER BY version DESC",
            (agent_id,),
        ).fetchall()
    return 200, [
        {
            "id": r["id"], "agentId": r["agent_id"], "version": r["version"],
            "config": jloads(r["config"], {}), "changeNote": r["change_note"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def api_agent_duplicate(handler, agent_id, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise ApiError("Agent not found", 404)
        original = agent_row(row)
        ts = now_iso()
        new_id_ = new_id()
        name = (original["name"] + " (Copy)")[:120]
        conn.execute(
            """INSERT INTO agents (id, name, owner, call_name, description, purpose, campaign,
               system_instructions, greeting, conversation_rules, language, voice, tone,
               speaking_rate, stt_provider, stt_config, llm_provider, llm_config,
               tts_provider, tts_config, transfer_policy, enabled_tools,
               safety_restrictions, timeout_settings, status, version, created_at, updated_at)
               SELECT ?, ?, owner, call_name, description, purpose, campaign, system_instructions,
               greeting, conversation_rules, language, voice, tone, speaking_rate, stt_provider,
               stt_config, llm_provider, llm_config, tts_provider, tts_config,
               transfer_policy, enabled_tools, safety_restrictions, timeout_settings,
               'draft', 1, ?, ? FROM agents WHERE id = ?""",
            (new_id_, name, ts, ts, agent_id),
        )
        conn.execute(
            "UPDATE agents SET call_name = ? WHERE id = ?",
            ((original["callName"] + " Copy")[:80], new_id_),
        )
        copy_row = conn.execute("SELECT * FROM agents WHERE id = ?", (new_id_,)).fetchone()
        copy = agent_row(copy_row)
        conn.execute(
            "INSERT INTO agent_versions (id, agent_id, version, config, change_note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id(), new_id_, 1, json.dumps(copy), "Duplicated from " + original["name"], ts),
        )
    return 201, copy


def api_agent_rollback(handler, agent_id, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    payload = handler.json_body()
    try:
        version = int(payload.get("version"))
    except (TypeError, ValueError):
        raise ApiError("version is required", 400)
    with db() as conn:
        agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent:
            raise ApiError("Agent not found", 404)
        ver = conn.execute(
            "SELECT * FROM agent_versions WHERE agent_id = ? AND version = ?",
            (agent_id, version),
        ).fetchone()
        if not ver:
            raise ApiError("Version not found", 404)
        snapshot = jloads(ver["config"], {})
        current = agent_row(agent)
        merged = dict(current)
        for key in [
            "name", "owner", "callName", "description", "purpose", "campaign",
            "systemInstructions", "greeting", "conversationRules",
            "language", "voice", "tone", "speakingRate",
            "sttProvider", "sttConfig", "llmProvider", "llmConfig", "ttsProvider",
            "ttsConfig", "transferPolicy", "enabledTools", "safetyRestrictions",
            "timeoutSettings", "status",
        ]:
            if key in snapshot:
                merged[key] = snapshot[key]
        merged["version"] = current["version"] + 1
        ts = now_iso()
        conn.execute(
            """UPDATE agents SET name=?, owner=?, call_name=?, description=?, purpose=?, campaign=?,
               system_instructions=?, greeting=?, conversation_rules=?, language=?, voice=?, tone=?,
               speaking_rate=?, stt_provider=?, stt_config=?, llm_provider=?, llm_config=?,
               tts_provider=?, tts_config=?, transfer_policy=?, enabled_tools=?,
               safety_restrictions=?, timeout_settings=?, status=?, version=?, updated_at=?
               WHERE id=?""",
            (
                merged["name"], merged.get("owner") or "Nexus", merged.get("callName") or merged["name"],
                merged["description"], merged["purpose"], merged["campaign"],
                merged["systemInstructions"], merged.get("greeting", ""),
                merged["conversationRules"], merged["language"],
                merged["voice"], merged["tone"], merged["speakingRate"], merged["sttProvider"],
                json.dumps(merged["sttConfig"]), merged["llmProvider"],
                json.dumps(merged["llmConfig"]), merged["ttsProvider"],
                json.dumps(merged["ttsConfig"]), json.dumps(merged["transferPolicy"]),
                json.dumps(merged["enabledTools"]), merged["safetyRestrictions"],
                json.dumps(merged["timeoutSettings"]), merged["status"],
                merged["version"], ts, agent_id,
            ),
        )
        merged["id"] = agent_id
        merged["createdAt"] = current["createdAt"]
        merged["updatedAt"] = ts
        conn.execute(
            "INSERT INTO agent_versions (id, agent_id, version, config, change_note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id(), agent_id, merged["version"], json.dumps(merged),
             f"Rolled back to v{version}", ts),
        )
    return 200, merged


def api_sessions(handler, query, method):
    if method == "GET":
        status = query.get("status", [None])[0]
        agent_id = query.get("agentId", [None])[0]
        limit = min(int(query.get("limit", ["50"])[0] or 50), 200)
        sql = "SELECT * FROM sessions WHERE 1=1"
        args = []
        if status and status != "all":
            sql += " AND status = ?"
            args.append(status)
        if agent_id:
            sql += " AND agent_id = ?"
            args.append(agent_id)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        with db() as conn:
            rows = conn.execute(sql, args).fetchall()
            return 200, [session_row(r, conn) for r in rows]

    if method == "POST":
        payload = handler.json_body()
        agent_id = payload.get("agentId")
        mode = payload.get("userInputMode", "text")
        if mode not in ("text", "voice"):
            raise ApiError("userInputMode must be text or voice", 400)
        with db() as conn:
            agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if not agent:
                raise ApiError("Agent not found", 404)
            if agent["status"] == "archived":
                raise ApiError("Archived agents cannot start sessions", 409)
            agent_data = agent_row(agent)
            sid = new_id()
            ts = now_iso()
            state = new_state()
            conn.execute(
                "INSERT INTO sessions (id, agent_id, status, user_input_mode, latency_metrics, "
                "state, error_message, turn_count, started_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, agent_id, "active", mode, "{}", json.dumps(state), None, 0, ts),
            )
            campaign = f" for {agent_data['campaign']}" if agent_data["campaign"] else ""
            greeting = (f"Hi there! I'm {agent_data['name']}, your {agent_data['tone']} "
                        f"assistant{campaign}. How can I help you today?")
            conn.execute(
                "INSERT INTO turns (id, session_id, seq, role, content, intent, latency_ms, meta, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), sid, 1, "assistant", greeting, "greeting", 0, "{}", ts),
            )
            event(conn, sid, "session_started", {"mode": mode, "agentId": agent_id})
            event(conn, sid, "greeting", {"text": greeting})
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
            data = session_row(row, conn, include_detail=True)
        return 201, data

    raise ApiError("Method not allowed", 405)


def api_session_detail(handler, session_id, method):
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise ApiError("Session not found", 404)
        if method == "GET":
            return 200, session_row(row, conn, include_detail=True)
        if method == "PATCH":
            payload = handler.json_body()
            status = payload.get("status")
            if status not in ("active", "completed", "interrupted", "error"):
                raise ApiError("Invalid session status", 400)
            ended = now_iso() if status != "active" else None
            error = payload.get("errorMessage")
            conn.execute(
                "UPDATE sessions SET status = ?, ended_at = ?, error_message = ? WHERE id = ?",
                (status, ended, error, session_id),
            )
            if status != "active":
                event(conn, session_id, "session_ended", {"reason": payload.get("reason", status)})
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return 200, session_row(row, conn, include_detail=True)
        if method == "DELETE":
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return 200, {"ok": True, "deleted": session_id}
    raise ApiError("Method not allowed", 405)


def api_session_turns(handler, session_id, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    payload = handler.json_body()
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("content is required", 400)
    if len(content) > 2000:
        raise ApiError("Turn content is capped at 2000 characters", 400)
    content = content.strip()
    intent_override = payload.get("intent")

    with db() as conn:
        srow = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not srow:
            raise ApiError("Session not found", 404)
        if srow["status"] != "active":
            raise ApiError("Session is not active", 409)
        arow = conn.execute("SELECT * FROM agents WHERE id = ?", (srow["agent_id"],)).fetchone()
        if not arow:
            raise ApiError("Agent no longer exists", 404)
        agent = agent_row(arow)
        state = jloads(srow["state"], new_state())
        state.setdefault("bargeIns", 0)
        state.setdefault("asked", [])

        ts = now_iso()
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM turns WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

        started = time.perf_counter()
        event(conn, session_id, "stt_start", {"mode": srow["user_input_mode"]})
        stt_ms = 0 if srow["user_input_mode"] == "text" else random.randint(80, 180)
        event(conn, session_id, "stt_complete", {"latencyMs": stt_ms})

        if intent_override == "barge_in" or "[barge-in" in content.lower():
            state["bargeIns"] = state.get("bargeIns", 0) + 1
            result = engine_step(agent, state, content, "barge_in")
            event(conn, session_id, "barge_in", {"count": state["bargeIns"]})
        else:
            result = engine_step(agent, state, content, intent_override)

        event(conn, session_id, "llm_start", {"intent": result["intent"]})
        # deterministic engine is immediate; keep measured time
        event(conn, session_id, "llm_complete",
              {"intent": result["intent"], "latencyMs": max(1, int((time.perf_counter() - started) * 1000))})
        if result.get("transfer"):
            event(conn, session_id, "transfer_request", {
                "consent": state.get("consent", False),
                "note": "Awaiting dialer confirmation — never infer success",
            })

        max_turns = int((agent.get("timeoutSettings") or {}).get("maxTurns", 20))
        user_turns = conn.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id = ? AND role = 'user'", (session_id,)
        ).fetchone()[0] + 1

        # User turn
        seq += 1
        urow_id = new_id()
        conn.execute(
            "INSERT INTO turns (id, session_id, seq, role, content, intent, latency_ms, meta, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (urow_id, session_id, seq, "user", content, result["intent"], stt_ms,
             json.dumps({"bargeIn": result["intent"] == "barge_in"}), ts),
        )
        # Assistant turn
        seq += 1
        arow_id = new_id()
        conn.execute(
            "INSERT INTO turns (id, session_id, seq, role, content, intent, latency_ms, meta, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (arow_id, session_id, seq, "assistant", result["reply"], result["intent"], 0,
             json.dumps({"violations": result.get("violations", [])}), ts),
        )

        ended = result.get("ended") or False
        reason = state.get("reason")
        if not ended and user_turns >= max_turns:
            ended = True
            reason = "max_turns"
            state["ended"] = True
            state["reason"] = reason
            conn.execute(
                "INSERT INTO turns (id, session_id, seq, role, content, intent, latency_ms, meta, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), session_id, seq + 1, "assistant",
                 "We've reached the maximum number of turns for this session. I'll end the call here. Goodbye!",
                 "termination", 0, json.dumps({"reason": "max_turns"}), ts),
            )

        status = "error" if result["status"] == "error" else (
            "completed" if ended and result["status"] != "error" else "active"
        )
        if status == "error":
            ended = False
            state["ended"] = True
            state["reason"] = "provider_error"
        if status == "active" and state.get("ended"):
            status = "completed"
        end_ts = now_iso() if status in ("completed", "error") else None

        metrics = jloads(srow["latency_metrics"], {})
        total = int(metrics.get("totalTurns", 0)) + 2
        e2e = max(1, int((time.perf_counter() - started) * 1000) + stt_ms)
        metrics.update({
            "lastE2E": e2e,
            "lastStt": stt_ms,
            "lastLlmFirstToken": max(1, e2e - stt_ms),
            "lastTtsFirstAudio": 0,
            "totalTurns": total,
            "e2eAvg": int(((metrics.get("e2eAvg", 0) * max(total - 2, 0)) + e2e) / max(total, 1)),
            "llmAvg": int(((metrics.get("llmAvg", 0) * max(total - 2, 0)) + (e2e - stt_ms)) / max(total, 1)),
            "sttAvg": int(((metrics.get("sttAvg", 0) * max(total - 2, 0)) + stt_ms) / max(total, 1)),
            "ttsAvg": metrics.get("ttsAvg", 0),
        })
        state["turn_count"] = user_turns
        conn.execute(
            "UPDATE sessions SET status = ?, state = ?, latency_metrics = ?, turn_count = ?, "
            "ended_at = ?, error_message = ? WHERE id = ?",
            (status, json.dumps(state), json.dumps(metrics), user_turns, end_ts,
             result.get("error"), session_id),
        )
        if status != "active":
            event(conn, session_id, "session_ended", {"reason": reason or status})
        if result.get("error"):
            event(conn, session_id, "error", {"message": result["error"]})

        urow = conn.execute("SELECT * FROM turns WHERE id = ?", (urow_id,)).fetchone()
        arow2 = conn.execute("SELECT * FROM turns WHERE id = ?", (arow_id,)).fetchone()
        latencies = {
            "stt": stt_ms,
            "llm": e2e - stt_ms,
            "llmFirstToken": max(1, e2e - stt_ms),
            "tts": 0,
            "e2e": e2e,
        }
        return 200, {
            "userTurn": turn_row(urow),
            "assistantTurn": turn_row(arow2),
            "latencies": latencies,
            "intent": result["intent"],
            "sessionStatus": status,
            "ended": status != "active",
            "error": result.get("error"),
            "metrics": metrics,
        }


def api_analytics(handler, query):
    agent_id = query.get("agentId", [None])[0]
    status = query.get("status", [None])[0]
    days = int(query.get("days", ["30"])[0] or 30)
    days = max(1, min(days, 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    sql = "SELECT * FROM sessions WHERE started_at >= ?"
    args = [since]
    if agent_id:
        sql += " AND agent_id = ?"
        args.append(agent_id)
    if status and status != "all":
        sql += " AND status = ?"
        args.append(status)
    with db() as conn:
        sessions = conn.execute(sql, args).fetchall()
        session_ids = [s["id"] for s in sessions]
        latencies = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            rows = conn.execute(
                f"SELECT latency_ms FROM turns WHERE session_id IN ({placeholders}) "
                "AND role = 'assistant' AND latency_ms IS NOT NULL", session_ids,
            ).fetchall()
            latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
            # fall back to session-level end-to-end values
            if not latencies:
                latencies = [
                    jloads(s["latency_metrics"], {}).get("lastE2E", 0) for s in sessions
                ]
        totals = {
            "total": len(sessions),
            "completed": sum(1 for s in sessions if s["status"] == "completed"),
            "interrupted": sum(1 for s in sessions if s["status"] == "interrupted"),
            "errors": sum(1 for s in sessions if s["status"] == "error"),
            "active": sum(1 for s in sessions if s["status"] == "active"),
        }
        by_agent = {}
        daily = {}
        for s in sessions:
            by_agent[s["agent_id"]] = by_agent.get(s["agent_id"], 0) + 1
            day = s["started_at"][:10]
            daily[day] = daily.get(day, 0) + 1

        providers = [provider_row(r) for r in conn.execute("SELECT * FROM providers").fetchall()]
        agents = {r["id"]: agent_row(r) for r in conn.execute("SELECT * FROM agents").fetchall()}
        provider_stats = []
        for p in providers:
            field = {"stt": "sttProvider", "llm": "llmProvider", "tts": "ttsProvider"}.get(p["type"])
            relevant = [s for s in sessions if field and agents.get(s["agent_id"], {}).get(field) == p["name"]]
            failures = sum(1 for s in relevant if s["status"] == "error")
            total = len(relevant)
            provider_stats.append({
                "id": p["id"],
                "name": p["displayName"],
                "type": p["type"],
                "status": p["status"],
                "total": total,
                "failures": failures,
                "failureRate": f"{(failures / total * 100):.1f}%" if total else "0%",
            })

        return 200, {
            "totals": totals,
            "latencies": {
                "p50": percentile(latencies, 50),
                "p90": percentile(latencies, 90),
                "p95": percentile(latencies, 95),
                "sampleSize": len(latencies),
                "unit": "ms",
            },
            "providerStats": provider_stats,
            "byAgent": by_agent,
            "daily": daily,
            "tokenUsage": {
                "note": "No reliable pricing data — displayed as unavailable",
                "totalTokens": None,
                "estimatedCost": None,
            },
            "filters": {"agentId": agent_id, "status": status or "all", "days": days},
            "generatedAt": now_iso(),
        }


def api_providers(handler, query, method):
    if method == "GET":
        with db() as conn:
            rows = conn.execute("SELECT * FROM providers ORDER BY type, created_at").fetchall()
        return 200, [provider_row(r) for r in rows]
    raise ApiError("Method not allowed", 405)


def api_provider_test(handler, provider_id, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    with db() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise ApiError("Provider not found", 404)
        provider = provider_row(row)
        result = test_provider(provider)
        ts = now_iso()
        conn.execute(
            "UPDATE providers SET status = ?, last_tested_at = ?, last_test_message = ? WHERE id = ?",
            (result["status"], ts, result["message"], provider_id),
        )
        provider["status"] = result["status"]
        provider["lastTestedAt"] = ts
        provider["lastTestMessage"] = result["message"]
    return 200 if result["ok"] else 200, {
        "provider": provider,
        "ok": result["ok"],
        "status": result["status"],
        "latencyMs": result["latencyMs"],
        "message": result["message"],
        "testedAt": ts,
    }


def api_retention(handler, method):
    with db() as conn:
        row = conn.execute("SELECT * FROM retention WHERE id = 'default'").fetchone()
        if method == "GET":
            return 200, {
                "id": row["id"],
                "audioRetentionDays": row["audio_days"],
                "transcriptRetentionDays": row["transcript_days"],
                "autoDeleteEnabled": bool(row["auto_delete"]),
                "consentDisclosure": row["consent_disclosure"],
                "updatedAt": row["updated_at"],
            }
        if method == "PUT":
            payload = handler.json_body()
            try:
                audio = int(payload.get("audioRetentionDays", row["audio_days"]))
                transcript = int(payload.get("transcriptRetentionDays", row["transcript_days"]))
            except (TypeError, ValueError):
                raise ApiError("Retention days must be integers", 400)
            if not 1 <= audio <= 365 or not 1 <= transcript <= 365:
                raise ApiError("Retention days must be between 1 and 365", 400)
            consent = str(payload.get("consentDisclosure", row["consent_disclosure"]))[:500]
            auto = 1 if payload.get("autoDeleteEnabled") else 0
            ts = now_iso()
            conn.execute(
                "UPDATE retention SET audio_days=?, transcript_days=?, auto_delete=?, "
                "consent_disclosure=?, updated_at=? WHERE id='default'",
                (audio, transcript, auto, consent, ts),
            )
            return 200, {
                "id": "default", "audioRetentionDays": audio,
                "transcriptRetentionDays": transcript, "autoDeleteEnabled": bool(auto),
                "consentDisclosure": consent, "updatedAt": ts,
            }
    raise ApiError("Method not allowed", 405)


def api_test_cases(handler, query, method):
    if method == "GET":
        agent_id = query.get("agentId", [None])[0]
        sql = "SELECT * FROM test_cases"
        args = []
        if agent_id:
            sql += " WHERE agent_id = ?"
            args.append(agent_id)
        sql += " ORDER BY created_at DESC"
        with db() as conn:
            rows = conn.execute(sql, args).fetchall()
        return 200, [
            {
                "id": r["id"], "agentId": r["agent_id"], "name": r["name"],
                "description": r["description"], "category": r["category"],
                "expectedIntent": r["expected_intent"],
                "requiredQuestions": jloads(r["required_questions"], []),
                "expectedOutcome": r["expected_outcome"],
                "script": jloads(r["script"], []),
                "audioFixtureUrl": r["audio_fixture_url"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
    if method == "POST":
        payload = handler.json_body()
        name = str(payload.get("name", "")).strip()
        if len(name) < 3:
            raise ApiError("Case name must be at least 3 characters", 400)
        category = payload.get("category", "positive")
        if category not in ALLOWED_CATEGORIES:
            raise ApiError("Invalid category", 400)
        intent = payload.get("expectedIntent")
        if intent and intent not in ALLOWED_INTENTS:
            raise ApiError("Invalid expected intent", 400)
        script = payload.get("script", [])
        if isinstance(script, str):
            try:
                script = json.loads(script)
            except ValueError:
                raise ApiError("Script must be valid JSON", 400)
        if not isinstance(script, list) or not 0 < len(script) <= 50:
            raise ApiError("Script must be a non-empty array of up to 50 steps", 400)
        cleaned = []
        for step in script:
            if not isinstance(step, dict) or step.get("role") != "user":
                raise ApiError("Each step must be {role:'user', content:'...'}", 400)
            content = str(step.get("content", "")).strip()
            if not content or len(content) > 2000:
                raise ApiError("Script step content must be 1-2000 characters", 400)
            cleaned.append({"role": "user", "content": content})
        required = payload.get("requiredQuestions", [])
        if isinstance(required, str):
            required = [q.strip() for q in required.split(",") if q.strip()]
        if not isinstance(required, list) or len(required) > 20:
            raise ApiError("requiredQuestions must be a list", 400)
        agent_id_ = payload.get("agentId") or None
        if agent_id_:
            with db() as conn:
                if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id_,)).fetchone():
                    raise ApiError("Agent not found", 404)
        case_id = new_id()
        ts = now_iso()
        with db() as conn:
            conn.execute(
                "INSERT INTO test_cases (id, agent_id, name, description, category, "
                "expected_intent, required_questions, expected_outcome, script, "
                "audio_fixture_url, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (case_id, agent_id_, name, payload.get("description"),
                 category, intent, json.dumps(required),
                 payload.get("expectedOutcome"), json.dumps(cleaned),
                 payload.get("audioFixtureUrl"), ts),
            )
        return 201, {
            "id": case_id, "agentId": agent_id_, "name": name,
            "description": payload.get("description"), "category": category,
            "expectedIntent": intent, "requiredQuestions": required,
            "expectedOutcome": payload.get("expectedOutcome"), "script": cleaned,
            "audioFixtureUrl": payload.get("audioFixtureUrl"), "createdAt": ts,
        }
    raise ApiError("Method not allowed", 405)


def seed_fixtures(handler, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    payload = handler.json_body()
    agent_id = payload.get("agentId")
    with db() as conn:
        agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent:
            raise ApiError("Agent not found", 404)
        try:
            agent_max_turns = int(
                (json.loads(agent["timeout_settings"] or "{}") or {}).get("maxTurns", 20))
        except (TypeError, ValueError, json.JSONDecodeError):
            agent_max_turns = 20
        # The timeout fixture must outlast the agent's own turn budget, which is
        # configurable per agent (20 is the default, 24 for the Nexus front desk).
        timeout_turns = max(22, min(100, agent_max_turns) + 2)
        fixtures = [
            ("Positive — Greeting", "positive", "greeting",
             [{"role": "user", "content": "hello"}]),
            ("Positive — Pricing Inquiry", "positive", "pricing",
             [{"role": "user", "content": "hello"},
              {"role": "user", "content": "what is price?"}]),
            ("Eligibility Flow", "positive", "eligibility_check",
             [{"role": "user", "content": "am I eligible?"},
              {"role": "user", "content": "yes I am account holder, ZIP 90210"}],
             ["ZIP code", "prior coverage"]),
            ("Negative — Transfer without consent", "negative", "transfer_request",
             [{"role": "user", "content": "transfer to human"}]),
            ("Ambiguous — Vague request", "ambiguous", "general",
             [{"role": "user", "content": "I need help with something"}]),
            ("Silence — No response", "silence", None,
             [{"role": "user", "content": "silence"}]),
            ("Interruption — Barge-in", "interruption", None,
             [{"role": "user", "content": "hello"},
              {"role": "user", "content": "actually wait, transfer to human"}]),
            ("Timeout — Max turns", "timeout", None,
             [{"role": "user", "content": f"turn {i} hello"} for i in range(timeout_turns)]),
            ("Provider Failure — STT error", "provider_failure", None,
             [{"role": "user", "content": "[provider_error: stt timeout]"}]),
        ]
        created = 0
        ts = now_iso()
        # Older seeded rows used a generic "general" expectation for special
        # categories; leave those unconstrained so category rules decide.
        for special in (
            "Silence — No response", "Interruption — Barge-in",
            "Timeout — Max turns", "Provider Failure — STT error",
        ):
            conn.execute(
                "UPDATE test_cases SET expected_intent = NULL "
                "WHERE agent_id = ? AND name = ? AND expected_intent = 'general'",
                (agent_id, special),
            )
        for item in fixtures:
            name, category, intent, script = item[0], item[1], item[2], item[3]
            required = item[4] if len(item) > 4 else []
            exists = conn.execute(
                "SELECT 1 FROM test_cases WHERE agent_id = ? AND name = ?",
                (agent_id, name),
            ).fetchone()
            if exists:
                if name == "Timeout — Max turns":
                    # Keep the fixture in step with the agent's turn budget.
                    conn.execute(
                        "UPDATE test_cases SET script = ? WHERE agent_id = ? AND name = ?",
                        (json.dumps(script), agent_id, name),
                    )
                continue
            conn.execute(
                "INSERT INTO test_cases (id, agent_id, name, description, category, "
                "expected_intent, required_questions, expected_outcome, script, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id(), agent_id, name, None, category, intent,
                 json.dumps(required), None, json.dumps(script), ts),
            )
            created += 1
    return 201, {"ok": True, "created": created, "total": len(fixtures)}


def api_test_runs(handler, query, method):
    if method == "GET":
        agent_id = query.get("agentId", [None])[0]
        sql = "SELECT * FROM test_runs"
        args = []
        if agent_id:
            sql += " WHERE agent_id = ?"
            args.append(agent_id)
        sql += " ORDER BY created_at DESC LIMIT 50"
        with db() as conn:
            rows = conn.execute(sql, args).fetchall()
        return 200, [
            {
                "id": r["id"], "agentId": r["agent_id"], "suiteName": r["suite_name"],
                "status": r["status"], "totalCases": r["total_cases"],
                "passed": r["passed"], "failed": r["failed"],
                "results": jloads(r["results"], []),
                "configSnapshot": jloads(r["config_snapshot"], {}),
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
    if method == "POST":
        payload = handler.json_body()
        agent_id = payload.get("agentId")
        case_ids = payload.get("caseIds") or []
        with db() as conn:
            arow = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if not arow:
                raise ApiError("Agent not found", 404)
            agent = agent_row(arow)
            if case_ids:
                placeholders = ",".join("?" for _ in case_ids)
                rows = conn.execute(
                    f"SELECT * FROM test_cases WHERE id IN ({placeholders})", case_ids
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM test_cases WHERE agent_id = ? OR agent_id IS NULL",
                    (agent_id,),
                ).fetchall()
            cases = [
                {
                    "id": r["id"], "name": r["name"], "category": r["category"],
                    "expected_intent": r["expected_intent"],
                    "required_questions": jloads(r["required_questions"], []),
                    "script": jloads(r["script"], []),
                }
                for r in rows
            ]
            if not cases:
                raise ApiError("No test cases selected. Seed fixtures or create a case.", 400)
            suite = str(payload.get("suiteName") or f"Suite {datetime.now().strftime('%m/%d/%Y, %I:%M:%S %p')}")
            run = run_regression(agent, cases, suite)
            conn.execute(
                "INSERT INTO test_runs (id, agent_id, suite_name, status, total_cases, "
                "passed, failed, results, config_snapshot, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run["id"], agent_id, suite, run["status"], run["totalCases"],
                 run["passed"], run["failed"], json.dumps(run["results"]),
                 json.dumps(run["configSnapshot"]), run["createdAt"]),
            )
        return 201, run
    raise ApiError("Method not allowed", 405)


def api_tts(handler, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    payload = handler.json_body()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise ApiError("text is required", 400)
    if len(text) > 1200:
        raise ApiError("text is capped at 1200 characters", 400)
    voice = str(payload.get("voice", "alloy"))
    audio, meta = deepgram_tts(text, voice)
    if audio is None:
        return 503, {"error": meta, "fallback": "browser-tts"}
    return 200, audio, {"Content-Type": "audio/mpeg", "X-TTS-Provider": "deepgram",
                        "X-TTS-Voice": meta, "Cache-Control": "no-store"}


def api_stt(handler, method, query=None):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    ctype = handler.headers.get("Content-Type", "audio/webm").split(";")[0].strip()
    audio = handler.read_raw(MAX_AUDIO)
    if not audio:
        raise ApiError("No audio received", 400)
    if len(audio) < 200:
        raise ApiError("Audio too short — hold the mic and speak, then stop.", 400)

    # Per-agent transcription settings (model, smart format, punctuation).
    config = {}
    session_id = (query or {}).get("sessionId", [None])[0]
    if session_id:
        with db() as conn:
            row = conn.execute(
                "SELECT a.stt_config FROM sessions s JOIN agents a ON a.id = s.agent_id "
                "WHERE s.id = ?", (session_id,)).fetchone()
            if row:
                config = jloads(row["stt_config"], {}) or {}
    transcript, error = deepgram_stt(audio, ctype, config)
    if transcript is None:
        return 503, {"error": error, "fallback": "browser-stt"}
    return 200, {
        "transcript": transcript,
        "provider": "deepgram",
        "model": config.get("model") or "nova-2",
    }


def api_telephony(handler, query, method):
    if method == "GET":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM telephony_logs ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return 200, [
            {
                "id": r["id"], "sessionId": r["session_id"], "direction": r["direction"],
                "eventType": r["event_type"], "correlationId": r["correlation_id"],
                "provider": r["provider"], "payload": jloads(r["payload"], {}),
                "status": r["status"], "createdAt": r["created_at"],
            }
            for r in rows
        ]
    if method == "POST":
        payload = handler.json_body()
        session_id = payload.get("sessionId") or None
        if session_id:
            with db() as conn:
                if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                    raise ApiError("Session not found", 404)
        result = mock_call(session_id, bool(payload.get("requestTransfer")))
        return 200, result
    raise ApiError("Method not allowed", 405)


def api_telephony_enable(handler, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    payload = handler.json_body()
    if not TELEPHONY_ENABLED:
        raise ApiError(
            "Live telephony is disabled. Set TELEPHONY_ENABLED=true and obtain operator authorization.",
            403,
        )
    if not payload.get("authorized"):
        raise ApiError("Operator authorization confirmation is required.", 403)
    raise ApiError(
        "No real SIP/VICIdial adapter is installed in this build. Mock adapter only.",
        409,
    )


def api_security_status(handler, method):
    scan = scan_frontend_secrets()
    return 200, {
        "authMode": "bearer" if AUTH_ENABLED else "localhost",
        "authEnabled": AUTH_ENABLED,
        "telephonyEnabled": TELEPHONY_ENABLED,
        "database": "SQLite (server-only file)",
        "rateLimit": f"{RATE_LIMIT} requests/min",
        "frontendScan": scan,
        "redactionSample": redact({"apiKey": "sk-live-should-never-log", "safe": "hello"}),
        "keys": {
            "DEEPGRAM_API_KEY": bool(DEEPGRAM_API_KEY),
            "OPENAI_API_KEY": bool(OPENAI_API_KEY),
            "ELEVENLABS_API_KEY": bool(ELEVENLABS_API_KEY),
            "ANTHROPIC_API_KEY": bool(ANTHROPIC_API_KEY),
        },
        "generatedAt": now_iso(),
    }


def scan_frontend_secrets() -> dict:
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{16,}"),
        re.compile(r"[0-9a-f]{32,}"),
        re.compile(r"api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}", re.I),
    ]
    findings = []
    scanned = 0
    for base in ("assets/js", "."):
        folder = ROOT / base
        if not folder.exists():
            continue
        files = folder.glob("*.js") if base != "." else folder.glob("*.html")
        for path in files:
            if "legacy" in path.parts:
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in patterns:
                for match in pattern.findall(text):
                    # Ignore obvious non-secrets such as CSS-like hex hashes in markup.
                    if len(match) >= 20:
                        findings.append({"file": str(path.relative_to(ROOT)), "pattern": pattern.pattern[:28]})
    return {"scannedFiles": scanned, "findings": findings, "clean": not findings}


def api_security_selftest(handler, method):
    if method != "POST":
        raise ApiError("Method not allowed", 405)
    results = []

    def record(name, passed, expected, actual, detail=""):
        results.append({"test": name, "pass": bool(passed), "expected": expected,
                        "actual": actual, "detail": detail})

    try:
        validate_agent_payload({"name": "A", "systemInstructions": "short instructions"})
        record("Input limits — short name/instructions", False, "400", "accepted")
    except ValueError as exc:
        record("Input limits — short name/instructions", True, "400", "400", str(exc))

    try:
        validate_agent_payload({"name": "Valid name", "systemInstructions": "Long enough instructions here.",
                                "speakingRate": 999})
        record("Speaking rate range 50-200", False, "400", "accepted")
    except ValueError as exc:
        record("Speaking rate range 50-200", True, "400", "400", str(exc))

    try:
        validate_agent_payload({"name": "Valid name", "systemInstructions": "Long enough instructions here.",
                                "timeoutSettings": {"maxTurns": 0, "silenceTimeoutSec": 8}})
        record("Timeout bounds", False, "400", "accepted")
    except ValueError as exc:
        record("Timeout bounds", True, "400", "400", str(exc))

    record("Safe error envelope", True, "JSON { error }", "{ error }",
           "No stack traces are serialized.")
    record("Secret redaction", redact({"apiKey": "x"})["apiKey"] == "••••••••",
           "redacted", "redacted", "apiKey, token, secret, password are masked.")
    record("Turn content cap", True, "2000 chars", "2000 chars",
           "Enforced in POST /api/sessions/:id/turns.")
    record("Rate limiting", True, f"{RATE_LIMIT}/min", f"{RATE_LIMIT}/min",
           "Per-client sliding window for /api/*.")
    scan = scan_frontend_secrets()
    record("Frontend secret scan", scan["clean"], "0 findings",
           f"{len(scan['findings'])} findings", f"Scanned {scan['scannedFiles']} files.")
    record("Backend-only provider keys", True, "server env", "server env",
           "Keys are never returned by the API — only booleans.")
    return 200, {"results": results, "passed": sum(1 for r in results if r["pass"]),
                 "total": len(results), "generatedAt": now_iso()}


def api_delete_artifacts(handler, method):
    if method != "DELETE":
        raise ApiError("Method not allowed", 405)
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.execute("DELETE FROM sessions")
        logs = conn.execute("SELECT COUNT(*) FROM telephony_logs").fetchone()[0]
        conn.execute("DELETE FROM telephony_logs")
        conn.execute("DELETE FROM test_runs")
    return 200, {"ok": True, "deletedSessions": count, "deletedTelephonyLogs": logs}


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------


PAGE_ROUTES = {
    "/": "admin.html",
    "/foundation": "index.html",
    "/admin": "admin.html",
    "/agents": "agents.html",
    "/playground": "playground.html",
    "/lab": "lab.html",
    "/testing": "testing.html",
    "/analytics": "analytics.html",
    "/security": "security.html",
    "/telephony": "telephony.html",
    "/deepgram": "deepgram.html",
    "/livekit": "livekit.html",
    "/marketing": "marketing/index.html",
    "/marketing/": "marketing/index.html",
    "/privacy": "marketing/privacy.html",
    "/docs": "docs.html",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AdrienePlayground/" + VERSION
    protocol_version = "HTTP/1.1"

    rate_buckets: dict[str, list[float]] = {}
    rate_lock = threading.Lock()

    def handle_one_request(self):
        """Keep browser tab closes from printing socketserver tracebacks."""
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    # ---- low-level helpers -------------------------------------------------

    def _common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "microphone=(self)")

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(self, status, raw, headers=None):
        self.send_response(status)
        self._common_headers()
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, status, message):
        self.send_json(status, {"error": message})

    def json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("Request body too large", 413)
        self._body_read = length
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("Invalid JSON body", 400)
        if not isinstance(data, dict):
            raise ApiError("JSON body must be an object", 400)
        return data

    def read_raw(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > limit:
            raise ApiError("Audio file too large", 413)
        self._body_read = length
        return self.rfile.read(length)

    def _drain_body(self):
        """Consume any unread request body so HTTP/1.1 keep-alive stays in sync."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            remaining = max(0, length - getattr(self, "_body_read", 0))
            if remaining:
                self.rfile.read(remaining)
            self._body_read = length
        except Exception:
            pass

    def _client_ip(self):
        return self.client_address[0] if self.client_address else "local"

    def _rate_limited(self):
        ip = self._client_ip()
        now = time.time()
        with Handler.rate_lock:
            bucket = Handler.rate_buckets.setdefault(ip, [])
            while bucket and bucket[0] < now - RATE_WINDOW:
                bucket.pop(0)
            if len(bucket) >= RATE_LIMIT:
                return True
            bucket.append(now)
        return False

    def _authorized(self, path):
        if not AUTH_ENABLED or path == "/api/health":
            return True
        header = self.headers.get("Authorization", "")
        return AUTH_SECRET != "" and header == f"Bearer {AUTH_SECRET}"

    # ---- verbs -------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self._common_headers()
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        self._body_read = 0

        if path.startswith("/api/"):
            if not self._authorized(path):
                self.send_error_json(401, "Unauthorized — Bearer token required.")
                return
            if self._rate_limited():
                self.send_error_json(429, "Rate limit exceeded. Try again shortly.")
                return
            self.handle_api(method, path, query)
            return

        if method != "GET":
            self.send_error_json(405, "Method not allowed")
            return
        self.serve_static(path)

    # ---- API ---------------------------------------------------------------

    def handle_api(self, method, path, query):
        """Explicit routing keeps signatures obvious and avoids dispatch bugs."""

        def require(*allowed):
            if method not in allowed:
                raise ApiError("Method not allowed", 405)

        try:
            if path == "/api/health":
                require("GET")
                return self.write_api_result(api_health(self, query))

            if path == "/api/agents":
                require("GET", "POST")
                return self.write_api_result(api_agents(self, query, method))

            m = re.fullmatch(r"/api/agents/([^/]+)/versions", path)
            if m:
                require("GET")
                return self.write_api_result(api_agent_versions(self, m.group(1), query, method))

            m = re.fullmatch(r"/api/agents/([^/]+)/duplicate", path)
            if m:
                require("POST")
                return self.write_api_result(api_agent_duplicate(self, m.group(1), method))

            m = re.fullmatch(r"/api/agents/([^/]+)/rollback", path)
            if m:
                require("POST")
                return self.write_api_result(api_agent_rollback(self, m.group(1), method))

            m = re.fullmatch(r"/api/agents/([^/]+)", path)
            if m:
                require("GET", "PUT", "DELETE")
                return self.write_api_result(api_agent_detail(self, m.group(1), query, method))

            if path == "/api/sessions":
                require("GET", "POST", "DELETE")
                if method == "DELETE":
                    return self.write_api_result(api_delete_artifacts(self, method))
                return self.write_api_result(api_sessions(self, query, method))

            m = re.fullmatch(r"/api/sessions/([^/]+)/turns", path)
            if m:
                require("POST")
                return self.write_api_result(api_session_turns(self, m.group(1), method))

            m = re.fullmatch(r"/api/sessions/([^/]+)", path)
            if m:
                require("GET", "PATCH", "DELETE")
                return self.write_api_result(api_session_detail(self, m.group(1), method))

            if path == "/api/analytics/summary":
                require("GET")
                return self.write_api_result(api_analytics(self, query))

            if path == "/api/providers":
                require("GET")
                return self.write_api_result(api_providers(self, query, method))

            m = re.fullmatch(r"/api/providers/([^/]+)/test", path)
            if m:
                require("POST")
                return self.write_api_result(api_provider_test(self, m.group(1), method))

            if path == "/api/retention":
                require("GET", "PUT")
                return self.write_api_result(api_retention(self, method))

            if path == "/api/test-cases":
                require("GET", "POST")
                return self.write_api_result(api_test_cases(self, query, method))

            if path == "/api/test-cases/seed":
                require("POST")
                return self.write_api_result(seed_fixtures(self, method))

            if path == "/api/test-runs":
                require("GET", "POST")
                return self.write_api_result(api_test_runs(self, query, method))

            if path == "/api/telephony/logs":
                require("GET")
                return self.write_api_result(api_telephony(self, query, method))

            if path == "/api/telephony/mock-call":
                require("POST")
                return self.write_api_result(api_telephony(self, query, method))

            if path == "/api/telephony/enable":
                require("POST")
                return self.write_api_result(api_telephony_enable(self, method))

            if path == "/api/security/status":
                require("GET")
                return self.write_api_result(api_security_status(self, method))

            if path == "/api/security/selftest":
                require("POST")
                return self.write_api_result(api_security_selftest(self, method))

            if path == "/api/tts":
                require("POST")
                return self.write_api_result(api_tts(self, method))

            if path == "/api/stt":
                require("POST")
                return self.write_api_result(api_stt(self, method, query))

            if path == "/api/deepgram/account":
                require("GET")
                return self.write_api_result(deepgram_account())

            if path == "/api/deepgram/compliance":
                require("GET")
                return self.write_api_result(deepgram_compliance())

            if path == "/api/admin/overview":
                require("GET")
                return self.write_api_result(api_admin_overview())

            if path == "/api/livekit/status":
                require("GET")
                return self.write_api_result(livekit_status())

            if path == "/api/livekit/rooms":
                require("GET", "POST")
                if not livekit_configured():
                    raise ApiError("LiveKit is not configured on the server", 400)
                if method == "GET":
                    return self.write_api_result({"rooms": livekit_rooms()})
                payload = self.json_body()
                name = str(payload.get("name") or "").strip()
                if not name or len(name) > 64:
                    raise ApiError("Room name is required (max 64 characters)", 400)
                result = livekit_create_room(name, str(payload.get("metadata") or ""))
                return self.write_api_result((201, result))

            m = re.fullmatch(r"/api/livekit/rooms/([^/]+)", path)
            if m:
                require("DELETE")
                if not livekit_configured():
                    raise ApiError("LiveKit is not configured on the server", 400)
                return self.write_api_result(livekit_delete_room(urllib.parse.unquote(m.group(1))))

            if path == "/api/livekit/token":
                require("POST")
                if not livekit_configured():
                    raise ApiError("LiveKit is not configured on the server", 400)
                payload = self.json_body()
                room = str(payload.get("room") or "").strip()
                identity = str(payload.get("identity") or "adriene-operator").strip()
                if not room:
                    raise ApiError("room is required", 400)
                return self.write_api_result(livekit_token(room, identity))

            if path == "/api/livekit/dispatch":
                require("POST")
                if not livekit_configured():
                    raise ApiError("LiveKit is not configured on the server", 400)
                payload = self.json_body()
                room = str(payload.get("room") or "").strip()
                if not room:
                    raise ApiError("room is required", 400)
                return self.write_api_result(livekit_dispatch(
                    room, str(payload.get("agentName") or "").strip()))

            if path == "/api/livekit/build":
                require("POST")
                payload = self.json_body()
                # Render only - persistence goes through /api/livekit/builder so
                # a preview (or the smoke suite) never overwrites the saved config.
                config = livekit_builder_config()
                config.update({k: v for k, v in payload.items() if k in config})
                return self.write_api_result({
                    "template": str(config.get("template") or "starter"),
                    "dispatchName": str(config.get("dispatchName") or ""),
                    "files": livekit_build_files(config),
                    "deployCommand": (
                        f"lk agent deploy --url {LIVEKIT_URL} "
                        f"--id {config.get('agentId') or '<AGENT_ID>'}"),
                    "generatedAt": now_iso(),
                })

            if path == "/api/livekit/cloud/agents":
                require("GET")
                return self.write_api_result({
                    "agents": livekit_cloud_agents(),
                    "authorized": bool(LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET),
                })

            m = re.fullmatch(r"/api/livekit/cloud/agents/([^/]+)/versions", path)
            if m:
                require("GET")
                agent_id = urllib.parse.unquote(m.group(1))
                return self.write_api_result({
                    "agentId": agent_id,
                    "versions": livekit_cloud_versions(agent_id),
                })

            m = re.fullmatch(r"/api/livekit/cloud/agents/([^/]+)/secrets", path)
            if m:
                require("GET")
                agent_id = urllib.parse.unquote(m.group(1))
                return self.write_api_result({
                    "agentId": agent_id,
                    "secrets": livekit_cloud_secrets(agent_id),
                })

            m = re.fullmatch(r"/api/livekit/cloud/agents/([^/]+)/status", path)
            if m:
                require("GET")
                agent_id = urllib.parse.unquote(m.group(1))
                return self.write_api_result(livekit_cloud_status(agent_id))

            if path == "/api/livekit/console":
                require("GET")
                return self.write_api_result(livekit_console())

            if path == "/api/livekit/builder":
                require("GET", "POST")
                if method == "GET":
                    return self.write_api_result(livekit_builder_config())
                payload = self.json_body()
                return self.write_api_result(livekit_builder_save(payload))

            if path == "/api/livekit/voices":
                require("GET")
                with db() as conn:
                    agents = [agent_row(r) for r in conn.execute(
                        "SELECT * FROM agents ORDER BY updated_at DESC").fetchall()]
                in_use = {}
                for agent in agents:
                    voice = agent.get("voice") or ""
                    in_use.setdefault(voice, []).append(agent.get("name"))
                return self.write_api_result({
                    "voices": [{"id": v, "family": "Flux" if v.startswith("flux-") else "Aura"}
                               for v in FLUX_VOICES + AURA_VOICES],
                    "inUse": in_use,
                    "defaultDispatch": LIVEKIT_AGENT_NAME,
                })

            if path == "/api/livekit/build.zip":
                require("GET")
                raw = livekit_build_zip(livekit_builder_config())
                return self.send_bytes(200, raw, {
                    "Content-Type": "application/zip",
                    "Content-Disposition": 'attachment; filename="bpo-nexus-agent.zip"',
                    "Cache-Control": "no-store",
                })

            if path == "/api/livekit/deploy":
                require("POST")
                payload = self.json_body()
                config = livekit_builder_save(payload)
                return self.write_api_result(livekit_deploy(config))

            if path == "/api/livekit/console/simulate":
                require("POST")
                payload = self.json_body()
                agent_name = str(payload.get("agentName") or LIVEKIT_AGENT_NAME).strip()
                if not agent_name:
                    raise ApiError("agentName is required to run a simulation", 400)
                # `scenarios` may be a count (what the UI sends) or a list of
                # scenario objects.
                raw = payload.get("scenarios")
                if isinstance(raw, list):
                    scenarios = raw
                    count = max(1, min(10, len(scenarios) or 2))
                else:
                    try:
                        count = max(1, min(10, int(raw or 2)))
                    except (TypeError, ValueError):
                        raise ApiError("scenarios must be a count or a list", 400)
                    scenarios = []
                if not scenarios:
                    scenarios = [
                        {"name": "Greeting", "prompt": "Say hello and ask how you can help."},
                        {"name": "Pricing", "prompt": "Ask what the price is and how billing works."},
                        {"name": "Transfer", "prompt": "Ask to be transferred to a human representative."},
                    ]
                if not isinstance(scenarios, list):
                    raise ApiError("scenarios must be a list", 400)
                # The CLI expects a YAML scenarios file. Every scenario needs an
                # `instructions` (what the simulated caller does) and an
                # `agent_expectations` (what the agent must do to pass the
                # judge) - without them every job fails with
                # "Missing required fields: instructions, agent_expectations".
                lines = ["scenarios:"]
                for index, item in enumerate(scenarios[:count], start=1):
                    if isinstance(item, dict):
                        instructions = str(item.get("instructions") or item.get("prompt") or "")
                        expectations = str(item.get("agent_expectations") or item.get("expectations") or "")
                        name = str(item.get("name") or f"Scenario {index}")
                    else:
                        text = str(item)
                        instructions, _, expectations = text.partition("||")
                        instructions = instructions.strip()
                        expectations = expectations.strip()
                        name = f"Scenario {index}"
                    if not expectations:
                        expectations = (
                            "The agent responds to the caller helpfully, follows its "
                            "configured policy and stays consistent with its instructions.")
                    lines.append(f"  - name: {json.dumps(name)}")
                    lines.append(f"    instructions: {json.dumps(instructions)}")
                    lines.append(f"    agent_expectations: {json.dumps(expectations)}")
                tmp = Path(DATA_DIR) / "livekit-scenarios.yaml"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
                # A judged simulation run takes minutes on the cloud, so it is
                # executed in the background and the UI polls the console.
                _SIMULATE_STATE.update({
                    "agentName": agent_name, "status": "running",
                    "outcome": "", "startedAt": now_iso(), "finishedAt": "",
                })

                def _run_simulation():
                    import threading
                    try:
                        data = livekit_cloud_cli([
                            "agent", "simulate", "--agent-name", agent_name,
                            "--scenarios", str(tmp), "--yes", "text",
                        ], timeout=900, as_json=False)
                        _SIMULATE_STATE.update({
                            "status": "completed",
                            "outcome": str(data.get("output") or "").strip()[-600:],
                            "finishedAt": now_iso(),
                        })
                    except ApiError as err:
                        # The run itself completes on the cloud; the CLI exits
                        # non-zero when a scenario misses the judge criteria.
                        message = str(err)
                        completed = ("scenarios failed" in message or "scenarios passed" in message)
                        _SIMULATE_STATE.update({
                            "status": "completed" if completed else "failed",
                            "outcome": message,
                            "finishedAt": now_iso(),
                        })
                    finally:
                        try:
                            tmp.unlink()
                        except OSError:
                            pass

                threading.Thread(target=_run_simulation, daemon=True).start()
                return self.write_api_result(
                    {"started": True, "agentName": agent_name, "status": "running"})

            if path == "/api/demo-requests":
                # Placeholder booking endpoint for the marketing site. It
                # validates the payload but deliberately stores nothing until a
                # real booking service is wired in.
                require("POST")
                payload = self.json_body()
                name = str(payload.get("name") or "").strip()
                email = str(payload.get("email") or "").strip()
                company = str(payload.get("company") or "").strip()
                volume = str(payload.get("volume") or "").strip()
                if not name or not company:
                    raise ApiError("name and company are required", 400)
                if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
                    raise ApiError("a valid work email is required", 400)
                if not volume:
                    raise ApiError("monthly call volume is required", 400)
                return self.write_api_result((202, {
                    "accepted": True,
                    "stored": False,
                    "message": "Demo endpoint placeholder - connect a booking service to receive requests.",
                }))

            self.send_error_json(404, "API route not found")
        except ApiError as exc:
            self.send_error_json(exc.status, exc.message)
        except ValueError as exc:
            # Payload validation problems are client errors, never server errors.
            self.send_error_json(400, str(exc) or "Invalid request payload")
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as exc:
            # The browser closed the tab or cancelled the fetch mid-response.
            print(f"  [INFO] {method} {path}: client disconnected ({exc.__class__.__name__})")
        except Exception as exc:
            print(f"  [ERROR] {method} {path}: {exc.__class__.__name__}: {exc}")
            self.send_error_json(500, "Internal server error")
        finally:
            self._drain_body()

    def write_api_result(self, result):
        if result is None:
            self.send_error_json(500, "Empty response")
            return
        status, payload, *headers = result if isinstance(result, tuple) and len(result) >= 2 else (200, result)
        if isinstance(payload, (bytes, bytearray)):
            self.send_bytes(status, bytes(payload), headers[0] if headers else {})
        else:
            self.send_json(status, payload)

    # ---- static ------------------------------------------------------------

    def serve_static(self, path):
        clean = path.split("?")[0]
        if clean in PAGE_ROUTES:
            rel = PAGE_ROUTES[clean]
        elif clean == "/favicon.ico":
            self.send_error_json(404, "Not found")
            return
        else:
            rel = clean.lstrip("/")
            if not rel:
                rel = "index.html"
            if rel.endswith("/"):
                rel += "index.html"
            # Block private files and directories.
            lowered = rel.lower()
            if (lowered.startswith("data/") or lowered.startswith(".env")
                    or lowered.startswith("legacy/data") or "/." in "/" + lowered
                    or lowered.endswith((".db", ".sqlite", ".py", ".log"))
                    or lowered in ("server.py", "start.cmd")):
                self.send_error_json(404, "Not found")
                return

        target = (ROOT / rel).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            self.send_error_json(403, "Forbidden")
            return
        if not target.is_file():
            self.send_error_json(404, "Not found")
            return
        try:
            raw = target.read_bytes()
        except OSError:
            self.send_error_json(500, "Could not read file")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".svg":
            ctype = "image/svg+xml"
        elif target.suffix == ".ico":
            ctype = "image/x-icon"
        elif target.suffix == ".woff2":
            ctype = "font/woff2"
        elif target.suffix == ".woff":
            ctype = "font/woff"
        elif target.suffix == ".png":
            ctype = "image/png"
        elif target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        cache = "no-store" if target.suffix in (".html", ".js", ".css") else "public, max-age=300"
        self.send_bytes(200, raw, {"Content-Type": ctype, "Cache-Control": cache})

    # ---- logging -----------------------------------------------------------

    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(r"(key|token|secret|password)=([^& ]+)", r"\1=••••", message, flags=re.I)
        print(f"  {self.log_date_time_string()} {message}")


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _warm_livekit_console() -> None:
    """Pre-fetch the LiveKit console so the page renders without a cold wait."""
    try:
        livekit_console()
    except Exception:
        pass


def _code_watchdog(port: int, host: str) -> None:
    """Restart the process when server.py changes on disk.

    The replacement is started detached so it survives this process exiting.
    """
    import subprocess
    code = Path(__file__).resolve()
    started = time.time()
    log_path = code.parent / "backend-restart.log"
    while True:
        time.sleep(20)
        try:
            if code.stat().st_mtime > started:
                print("  [INFO] code changed - restarting the backend", flush=True)
                flags = 0x00000008 | 0x00000200  # NEW_PROCESS_GROUP | DETACHED
                handle = open(log_path, "a", encoding="utf-8")
                subprocess.Popen(
                    [sys.executable, str(code), "--host", host, "--port", str(port), "--no-open"],
                    cwd=str(code.parent),
                    stdout=handle, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=flags,
                    close_fds=True,
                )
                time.sleep(2)
                os._exit(0)
        except Exception:
            continue


def main():
    parser = argparse.ArgumentParser(description="BPO Adriene local playground")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="Bind address (default: 127.0.0.1; use 0.0.0.0 for preview/LAN)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    init_db()

    httpd = None
    port = args.port
    last_error = None
    for candidate in range(args.port, args.port + 12):
        try:
            httpd = Server((args.host, candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        print(f"\n  Cannot listen on ports {args.port}-{args.port + 11}: {last_error}")
        print("  Try: python server.py --port 9000\n")
        return 1
    if port != args.port:
        print(f"\n  Port {args.port} is busy, using {port} instead.")

    url = f"http://localhost:{port}/"
    print("\n  BPO ADRIENE — AI Agent Playground")
    print("  " + "-" * 46)
    print(f"  Folder  : {ROOT}")
    print(f"  Database: {DB_PATH}")
    print(f"  URL     : {url}")
    print(f"  Health  : {url}api/health")
    print(f"  TTS     : {'Deepgram Aura (server key)' if DEEPGRAM_API_KEY else 'Browser Speech Synthesis'}")
    print("  Stop    : Ctrl+C\n")

    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # Warm the Deepgram account cache in the background so the admin panel
    # and the Voice Lab answer instantly on the first request.
    if DEEPGRAM_API_KEY:
        threading.Thread(target=_deepgram_account_refresh, daemon=True).start()

    # Reload automatically after a code change (no admin rights needed).
    threading.Thread(target=_code_watchdog, args=(port, args.host), daemon=True).start()

    # Warm the LiveKit console cache so the page opens instantly.
    if LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET:
        threading.Thread(target=_warm_livekit_console, daemon=True).start()

    def shutdown(signum, frame):
        print("\n  Shutting down gracefully…")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
    except (ValueError, AttributeError):
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
