"""Transactional SQLite repository for agents, sessions, turns, and transfers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time
import uuid

from ..db import Database
from ..domain.conversation import AgentPolicy, engine_turn, initial_state


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    pass


class NexusRepository:
    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()
        self._seed()
        self._ensure_retention()

    def _ensure_retention(self) -> None:
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM retention_policy WHERE id = 1").fetchone():
                conn.execute(
                    "INSERT INTO retention_policy (id, transcript_days, auto_delete, updated_at) VALUES (1, 30, 0, ?)",
                    (utc_now(),),
                )

    def _seed(self) -> None:
        with self.database.connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]:
                return
            timestamp = utc_now()
            conn.execute(
                "INSERT INTO agents (id, active_version_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("mma-nexus-intake", "mma-nexus-intake-v1", timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO agent_versions (
                    id, agent_id, version, name, campaign, greeting,
                    persona_preset, purpose, tone, transfers_enabled, require_consent, max_turns,
                    stt_provider, stt_model, tts_provider, tts_voice, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "mma-nexus-intake-v1",
                    "mma-nexus-intake",
                    1,
                    "MMA Nexus Intake",
                    "Inbound service qualification",
                    "Hello — welcome to MMA BPO NEXUS. I’ll guide you through a short, transparent intake. Are you the account holder?",
                    "intake",
                    "Inbound service qualification",
                    "professional",
                    1,
                    1,
                    20,
                    "browser",
                    "browser",
                    "browser",
                    "aura-asteria-en",
                    timestamp,
                ),
            )

    @staticmethod
    def _agent_from_rows(agent, version) -> dict:
        return {
            "id": agent["id"],
            "name": version["name"],
            "campaign": version["campaign"],
            "greeting": version["greeting"],
            "personaPreset": version["persona_preset"],
            "purpose": version["purpose"],
            "tone": version["tone"],
            "transfersEnabled": bool(version["transfers_enabled"]),
            "requireConsent": bool(version["require_consent"]),
            "maxTurns": version["max_turns"],
            "sttProvider": version["stt_provider"],
            "sttModel": version["stt_model"],
            "ttsProvider": version["tts_provider"],
            "ttsVoice": version["tts_voice"],
            "version": version["version"],
            "versionId": version["id"],
            "createdAt": agent["created_at"],
            "updatedAt": version["created_at"],
        }

    def get_agent(self, agent_id: str | None = None) -> dict:
        with self.database.connect() as conn:
            if agent_id:
                agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            else:
                agent = conn.execute("SELECT * FROM agents ORDER BY created_at LIMIT 1").fetchone()
            if not agent:
                raise NotFoundError("Agent not found")
            version = conn.execute(
                "SELECT * FROM agent_versions WHERE id = ?", (agent["active_version_id"],)
            ).fetchone()
            if not version:
                raise NotFoundError("Active agent version not found")
            return self._agent_from_rows(agent, version)

    def list_agent_versions(self, agent_id: str) -> list[dict]:
        self.get_agent(agent_id)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_versions WHERE agent_id = ? ORDER BY version DESC",
                (agent_id,),
            ).fetchall()
        return [{
            "id": row["id"],
            "version": row["version"],
            "name": row["name"],
            "campaign": row["campaign"],
            "greeting": row["greeting"],
            "personaPreset": row["persona_preset"],
            "purpose": row["purpose"],
            "tone": row["tone"],
            "transfersEnabled": bool(row["transfers_enabled"]),
            "requireConsent": bool(row["require_consent"]),
            "maxTurns": row["max_turns"],
            "sttProvider": row["stt_provider"],
            "sttModel": row["stt_model"],
            "ttsProvider": row["tts_provider"],
            "ttsVoice": row["tts_voice"],
            "createdAt": row["created_at"],
        } for row in rows]

    def update_agent(self, agent_id: str, payload: dict) -> dict:
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if not agent:
                raise NotFoundError("Agent not found")
            current = conn.execute(
                "SELECT * FROM agent_versions WHERE id = ?", (agent["active_version_id"],)
            ).fetchone()
            if not current:
                raise NotFoundError("Active agent version not found")
            version_number = current["version"] + 1
            version_id = new_id()
            timestamp = utc_now()
            conn.execute(
                """INSERT INTO agent_versions (
                    id, agent_id, version, name, campaign, greeting,
                    persona_preset, purpose, tone, transfers_enabled, require_consent, max_turns,
                    stt_provider, stt_model, tts_provider, tts_voice, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    agent_id,
                    version_number,
                    payload["name"],
                    payload["campaign"],
                    payload["greeting"],
                    payload.get("personaPreset", current["persona_preset"]),
                    payload.get("purpose", current["purpose"]),
                    payload.get("tone", current["tone"]),
                    int(payload["transfersEnabled"]),
                    int(payload["requireConsent"]),
                    current["max_turns"],
                    payload["sttProvider"],
                    payload["sttModel"],
                    payload["ttsProvider"],
                    payload["ttsVoice"],
                    timestamp,
                ),
            )
            conn.execute(
                "UPDATE agents SET active_version_id = ?, updated_at = ? WHERE id = ?",
                (version_id, timestamp, agent_id),
            )
        return self.get_agent(agent_id)

    def create_session(self, agent_id: str) -> dict:
        agent = self.get_agent(agent_id)
        session_id = new_id()
        timestamp = utc_now()
        state = initial_state()
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO sessions (
                    id, agent_id, agent_version_id, status, stage, state_json,
                    turn_count, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    agent["id"],
                    agent["versionId"],
                    "active",
                    state["stage"],
                    json.dumps(state),
                    0,
                    timestamp,
                    None,
                ),
            )
            conn.execute(
                """INSERT INTO turns (
                    id, session_id, seq, role, content, intent, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id(), session_id, 1, "assistant", agent["greeting"], "greeting", 0, timestamp),
            )
            self._insert_event(conn, session_id, "session_started", {
                "agentId": agent["id"],
                "agentVersion": agent["version"],
                "channel": "text+voice",
            })
            self._insert_event(conn, session_id, "greeting", {"text": agent["greeting"]})
        return self.get_session(session_id)

    @staticmethod
    def _insert_event(conn, session_id: str, event_type: str, payload: dict) -> None:
        conn.execute(
            "INSERT INTO events (id, session_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id(), session_id, event_type, json.dumps(payload), utc_now()),
        )

    @staticmethod
    def _session_summary(row) -> dict:
        return {
            "id": row["id"],
            "agentId": row["agent_id"],
            "agentVersionId": row["agent_version_id"],
            "agentVersion": row["agent_version"],
            "agentName": row["agent_name"],
            "status": row["status"],
            "stage": row["stage"],
            "turnCount": row["turn_count"],
            "startedAt": row["started_at"],
            "endedAt": row["ended_at"],
        }

    def _session_query(self, conn, session_id: str):
        return conn.execute(
            """SELECT s.*, v.version AS agent_version, v.name AS agent_name,
                      v.campaign AS agent_campaign, v.greeting AS agent_greeting,
                      v.transfers_enabled, v.require_consent, v.max_turns,
                      v.stt_provider, v.stt_model, v.tts_provider, v.tts_voice,
                      v.persona_preset, v.purpose, v.tone
               FROM sessions s
               JOIN agent_versions v ON v.id = s.agent_version_id
               WHERE s.id = ?""",
            (session_id,),
        ).fetchone()

    def get_session(self, session_id: str) -> dict:
        with self.database.connect() as conn:
            row = self._session_query(conn, session_id)
            if not row:
                raise NotFoundError("Session not found")
            data = self._session_summary(row)
            data["state"] = json.loads(row["state_json"])
            data["policy"] = {
                "transfersEnabled": bool(row["transfers_enabled"]),
                "requireConsent": bool(row["require_consent"]),
                "maxTurns": row["max_turns"],
                "sttProvider": row["stt_provider"],
                "sttModel": row["stt_model"],
                "ttsProvider": row["tts_provider"],
                "ttsVoice": row["tts_voice"],
                "personaPreset": row["persona_preset"],
                "purpose": row["purpose"],
                "tone": row["tone"],
            }
            data["turns"] = [{
                "id": turn["id"],
                "seq": turn["seq"],
                "role": turn["role"],
                "content": turn["content"],
                "intent": turn["intent"],
                "latencyMs": turn["latency_ms"],
                "inputMethod": turn["input_method"],
                "sttLatencyMs": turn["stt_latency_ms"],
                "createdAt": turn["created_at"],
            } for turn in conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY seq", (session_id,)
            ).fetchall()]
            data["events"] = [{
                "id": event["id"],
                "type": event["type"],
                "payload": json.loads(event["payload_json"]),
                "createdAt": event["created_at"],
            } for event in conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()]
            data["transfers"] = [{
                "id": transfer["id"],
                "status": transfer["status"],
                "reason": transfer["reason"],
                "createdAt": transfer["created_at"],
                "updatedAt": transfer["updated_at"],
            } for transfer in conn.execute(
                "SELECT * FROM transfers WHERE session_id = ? ORDER BY created_at", (session_id,)
            ).fetchall()]
            data["voiceRequests"] = [{
                "id": request["id"],
                "operation": request["operation"],
                "provider": request["provider"],
                "source": request["source"],
                "status": request["status"],
                "latencyMs": request["latency_ms"],
                "message": request["message"],
                "createdAt": request["created_at"],
            } for request in conn.execute(
                "SELECT * FROM voice_requests WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()]
            return data

    def list_sessions(self, limit: int = 25) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT s.*, v.version AS agent_version, v.name AS agent_name
                   FROM sessions s
                   JOIN agent_versions v ON v.id = s.agent_version_id
                   ORDER BY s.started_at DESC, s.rowid DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._session_summary(row) for row in rows]

    def add_turn(
        self, session_id: str, content: str, input_method: str = "text",
        stt_latency_ms: float | None = None,
    ) -> dict:
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_query(conn, session_id)
            if not row:
                raise NotFoundError("Session not found")
            if row["status"] != "active":
                raise ConflictError(f"Session is {row['status']} and cannot accept turns")
            expected_provider = {
                "browser-stt": "browser",
                "deepgram-stt": "deepgram",
                "deepgram-flux-stt": "deepgram-flux",
            }.get(input_method)
            if expected_provider and row["stt_provider"] != expected_provider:
                raise ConflictError(
                    f"This session is bound to {row['stt_provider']} STT, not {expected_provider}"
                )

            state = json.loads(row["state_json"])
            policy = AgentPolicy(
                transfers_enabled=bool(row["transfers_enabled"]),
                require_consent=bool(row["require_consent"]),
                max_turns=row["max_turns"],
                purpose=row["purpose"],
                tone=row["tone"],
            )
            turn_number = row["turn_count"] + 1
            started = time.perf_counter()
            result = engine_turn(policy, state, content, turn_number=turn_number)
            latency_ms = max(0.01, round((time.perf_counter() - started) * 1000, 3))
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            timestamp = utc_now()
            conn.execute(
                """INSERT INTO turns (
                    id, session_id, seq, role, content, intent, latency_ms,
                    input_method, stt_latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id(), session_id, next_seq, "user", content, "caller_input", 0,
                    input_method, stt_latency_ms, timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO turns (
                    id, session_id, seq, role, content, intent, latency_ms,
                    input_method, stt_latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id(), session_id, next_seq + 1, "assistant", result.reply,
                    result.intent, latency_ms, "text", None, timestamp,
                ),
            )
            ended_at = utc_now() if result.status == "completed" else None
            conn.execute(
                """UPDATE sessions
                   SET status = ?, stage = ?, state_json = ?, turn_count = ?, ended_at = ?
                   WHERE id = ?""",
                (
                    result.status,
                    result.state["stage"],
                    json.dumps(result.state),
                    turn_number,
                    ended_at,
                    session_id,
                ),
            )
            for event in result.events:
                self._insert_event(conn, session_id, event["type"], event["payload"])
            self._insert_event(conn, session_id, "turn_completed", {
                "turn": turn_number,
                "intent": result.intent,
                "latencyMs": latency_ms,
                "stage": result.state["stage"],
                "status": result.status,
                "inputMethod": input_method,
                "sttLatencyMs": stt_latency_ms,
            })
            if input_method == "browser-stt":
                self._insert_voice_request(
                    conn, session_id, "stt", "browser", "browser", "success",
                    float(stt_latency_ms or 0), "Browser-measured elapsed recognition time",
                )
            if result.transfer:
                timestamp = utc_now()
                conn.execute(
                    """INSERT INTO transfers (
                        id, session_id, status, reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        new_id(), session_id, result.transfer["status"],
                        result.transfer["reason"], timestamp, timestamp,
                    ),
                )
        return self.get_session(session_id)

    @staticmethod
    def _insert_voice_request(
        conn, session_id: str | None, operation: str, provider: str, source: str,
        status: str, latency_ms: float, message: str | None,
    ) -> str:
        request_id = new_id()
        conn.execute(
            """INSERT INTO voice_requests (
                id, session_id, operation, provider, source, status,
                latency_ms, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id, session_id, operation, provider, source, status,
                max(0, float(latency_ms)), (message or None) and message[:200], utc_now(),
            ),
        )
        if session_id:
            NexusRepository._insert_event(conn, session_id, f"voice_{operation}_{status}", {
                "requestId": request_id,
                "provider": provider,
                "source": source,
                "latencyMs": max(0, float(latency_ms)),
                "message": (message or None) and message[:200],
            })
        return request_id

    def record_voice_request(
        self, session_id: str | None, operation: str, provider: str, source: str,
        status: str, latency_ms: float, message: str | None = None,
    ) -> str:
        """Persist metadata only; audio never enters this method or the database."""
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if session_id:
                row = self._session_query(conn, session_id)
                if not row:
                    raise NotFoundError("Session not found")
                configured = row[f"{operation}_provider"]
                if configured != provider and (source == "server" or operation == "stt"):
                    raise ConflictError(
                        f"Session {operation.upper()} is bound to {configured}, not {provider}"
                    )
            return self._insert_voice_request(
                conn, session_id, operation, provider, source, status, latency_ms, message
            )

    def end_session(self, session_id: str) -> dict:
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_query(conn, session_id)
            if not row:
                raise NotFoundError("Session not found")
            if row["status"] != "active":
                raise ConflictError(f"Session is already {row['status']}")
            state = json.loads(row["state_json"])
            state["stage"] = "ended"
            state["outcome"] = "operator_ended"
            if state.get("transferStatus") in {"awaiting_consent", "blocked"}:
                state["transferStatus"] = "not_requested"
            timestamp = utc_now()
            conn.execute(
                """UPDATE sessions
                   SET status = 'completed', stage = 'ended', state_json = ?, ended_at = ?
                   WHERE id = ?""",
                (json.dumps(state), timestamp, session_id),
            )
            self._insert_event(conn, session_id, "session_completed", {"reason": "operator_ended"})
        return self.get_session(session_id)

    def get_retention(self) -> dict:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM retention_policy WHERE id = 1").fetchone()
            return {
                "transcriptDays": row["transcript_days"],
                "autoDelete": bool(row["auto_delete"]),
                "updatedAt": row["updated_at"],
                "audioStored": False,
            }

    def update_retention(self, transcript_days: int, auto_delete: bool) -> dict:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE retention_policy SET transcript_days = ?, auto_delete = ?, updated_at = ?
                   WHERE id = 1""",
                (transcript_days, int(auto_delete), utc_now()),
            )
        return self.get_retention()

    def cleanup_expired(self) -> int:
        """Delete expired transcripts and cascaded evidence only when enabled."""
        policy = self.get_retention()
        if not policy["autoDelete"]:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=policy["transcriptDays"]))
        cutoff_iso = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id FROM sessions WHERE started_at < ?", (cutoff_iso,)
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
            return len(rows)

    def delete_session(self, session_id: str) -> None:
        with self.database.connect() as conn:
            result = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            if result.rowcount == 0:
                raise NotFoundError("Session not found")

    def health(self) -> dict:
        with self.database.connect() as conn:
            conn.execute("SELECT 1").fetchone()
            agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            voice_requests = conn.execute("SELECT COUNT(*) FROM voice_requests").fetchone()[0]
        return {
            "ok": True,
            "service": "MMA BPO NEXUS",
            "version": "0.4.1",
            "stage": 4,
            "mode": "secure-conversation-voice-and-livekit",
            "database": "connected",
            "counts": {"agents": agents, "sessions": sessions, "voiceRequests": voice_requests},
            "audioStored": False,
            "realTelephony": False,
        }
