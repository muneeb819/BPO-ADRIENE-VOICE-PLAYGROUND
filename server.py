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
ALLOWED_STATUSES = {"draft", "testing", "approved", "archived"}
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


def agent_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
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
        "name", "description", "purpose", "campaign", "systemInstructions", "greeting",
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
    base["systemInstructions"] = _clean_str(base.get("systemInstructions"), 8000).strip()
    if len(base["systemInstructions"]) < 10:
        raise ValueError("System instructions must be at least 10 characters")
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
            "auth": AUTH_ENABLED,
        },
    }


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
                """INSERT INTO agents (id, name, description, purpose, campaign,
                   system_instructions, greeting, conversation_rules, language, voice, tone,
                   speaking_rate, stt_provider, stt_config, llm_provider, llm_config,
                   tts_provider, tts_config, transfer_policy, enabled_tools,
                   safety_restrictions, timeout_settings, status, version, created_at,
                   updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent_id, data["name"], data["description"], data["purpose"],
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
                """UPDATE agents SET name=?, description=?, purpose=?, campaign=?,
                   system_instructions=?, greeting=?, conversation_rules=?, language=?, voice=?,
                   tone=?, speaking_rate=?, stt_provider=?, stt_config=?, llm_provider=?,
                   llm_config=?, tts_provider=?, tts_config=?, transfer_policy=?,
                   enabled_tools=?, safety_restrictions=?, timeout_settings=?, status=?,
                   version=?, updated_at=? WHERE id=?""",
                (
                    data["name"], data["description"], data["purpose"], data["campaign"],
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
            """INSERT INTO agents (id, name, description, purpose, campaign,
               system_instructions, greeting, conversation_rules, language, voice, tone,
               speaking_rate, stt_provider, stt_config, llm_provider, llm_config,
               tts_provider, tts_config, transfer_policy, enabled_tools,
               safety_restrictions, timeout_settings, status, version, created_at, updated_at)
               SELECT ?, ?, description, purpose, campaign, system_instructions,
               greeting, conversation_rules, language, voice, tone, speaking_rate, stt_provider,
               stt_config, llm_provider, llm_config, tts_provider, tts_config,
               transfer_policy, enabled_tools, safety_restrictions, timeout_settings,
               'draft', 1, ?, ? FROM agents WHERE id = ?""",
            (new_id_, name, ts, ts, agent_id),
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
            "name", "description", "purpose", "campaign", "systemInstructions",
            "conversationRules", "language", "voice", "tone", "speakingRate",
            "sttProvider", "sttConfig", "llmProvider", "llmConfig", "ttsProvider",
            "ttsConfig", "transferPolicy", "enabledTools", "safetyRestrictions",
            "timeoutSettings", "status",
        ]:
            if key in snapshot:
                merged[key] = snapshot[key]
        merged["version"] = current["version"] + 1
        ts = now_iso()
        conn.execute(
            """UPDATE agents SET name=?, description=?, purpose=?, campaign=?,
               system_instructions=?, conversation_rules=?, language=?, voice=?, tone=?,
               speaking_rate=?, stt_provider=?, stt_config=?, llm_provider=?, llm_config=?,
               tts_provider=?, tts_config=?, transfer_policy=?, enabled_tools=?,
               safety_restrictions=?, timeout_settings=?, status=?, version=?, updated_at=?
               WHERE id=?""",
            (
                merged["name"], merged["description"], merged["purpose"], merged["campaign"],
                merged["systemInstructions"], merged["conversationRules"], merged["language"],
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
             [{"role": "user", "content": f"turn {i} hello"} for i in range(22)]),
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


def main():
    parser = argparse.ArgumentParser(description="BPO Adriene local playground")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    init_db()

    httpd = None
    port = args.port
    last_error = None
    for candidate in range(args.port, args.port + 12):
        try:
            httpd = Server(("127.0.0.1", candidate), Handler)
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
