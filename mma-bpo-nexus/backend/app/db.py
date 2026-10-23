"""SQLite connection and schema management."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    active_version_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    campaign TEXT NOT NULL,
    greeting TEXT NOT NULL,
    persona_preset TEXT NOT NULL DEFAULT 'intake',
    purpose TEXT NOT NULL DEFAULT 'Inbound service qualification',
    tone TEXT NOT NULL DEFAULT 'professional',
    transfers_enabled INTEGER NOT NULL,
    require_consent INTEGER NOT NULL,
    max_turns INTEGER NOT NULL DEFAULT 20,
    stt_provider TEXT NOT NULL DEFAULT 'browser',
    stt_model TEXT NOT NULL DEFAULT 'nova-2',
    tts_provider TEXT NOT NULL DEFAULT 'browser',
    tts_voice TEXT NOT NULL DEFAULT 'aura-asteria-en',
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, version)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    agent_version_id TEXT NOT NULL REFERENCES agent_versions(id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    state_json TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    intent TEXT NOT NULL,
    latency_ms REAL NOT NULL DEFAULT 0,
    input_method TEXT NOT NULL DEFAULT 'text',
    stt_latency_ms REAL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_requests (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK(operation IN ('stt', 'tts')),
    provider TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('server', 'browser')),
    status TEXT NOT NULL CHECK(status IN ('success', 'error')),
    latency_ms REAL NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retention_policy (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    transcript_days INTEGER NOT NULL DEFAULT 30,
    auto_delete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_iterations INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    detail_json TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_agent ON agent_versions(agent_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_transfers_session ON transfers(session_id, status);
CREATE INDEX IF NOT EXISTS idx_voice_requests_session ON voice_requests(session_id, operation, created_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute("PRAGMA journal_mode = WAL")

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add Stage 2 fields without deleting Stage 1 databases."""
        agent_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_versions)")}
        for column, ddl in (
            ("persona_preset", "TEXT NOT NULL DEFAULT 'intake'"),
            ("purpose", "TEXT NOT NULL DEFAULT 'Inbound service qualification'"),
            ("tone", "TEXT NOT NULL DEFAULT 'professional'"),
            ("stt_provider", "TEXT NOT NULL DEFAULT 'browser'"),
            ("stt_model", "TEXT NOT NULL DEFAULT 'nova-2'"),
            ("tts_provider", "TEXT NOT NULL DEFAULT 'browser'"),
            ("tts_voice", "TEXT NOT NULL DEFAULT 'aura-asteria-en'"),
        ):
            if column not in agent_columns:
                conn.execute(f"ALTER TABLE agent_versions ADD COLUMN {column} {ddl}")

        turn_columns = {row["name"] for row in conn.execute("PRAGMA table_info(turns)")}
        for column, ddl in (
            ("input_method", "TEXT NOT NULL DEFAULT 'text'"),
            ("stt_latency_ms", "REAL"),
        ):
            if column not in turn_columns:
                conn.execute(f"ALTER TABLE turns ADD COLUMN {column} {ddl}")
