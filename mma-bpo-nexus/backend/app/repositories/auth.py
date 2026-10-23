"""Secure users, opaque server-side sessions, CSRF state, and audit records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import sqlite3

from ..db import Database
from .nexus import ConflictError, NotFoundError, new_id, utc_now


PASSWORD_ITERATIONS = 320_000
SESSION_HOURS = 8


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class AuthRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _public_user(row) -> dict:
        return {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "role": row["role"],
            "active": bool(row["active"]),
            "createdAt": row["created_at"],
            "lastLoginAt": row["last_login_at"],
        }

    def user_count(self) -> int:
        with self.database.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def requires_setup(self) -> bool:
        return self.user_count() == 0

    def list_users(self) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
            return [self._public_user(row) for row in rows]

    def get_user(self, user_id: str) -> dict:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise NotFoundError("User not found")
            return self._public_user(row)

    def create_user(self, username: str, display_name: str, password: str, role: str) -> dict:
        user_id = new_id()
        salt = secrets.token_bytes(16)
        timestamp = utc_now()
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """INSERT INTO users (
                        id, username, display_name, password_salt, password_hash,
                        password_iterations, role, active, created_at, last_login_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id, username, display_name, salt.hex(),
                        _password_hash(password, salt), PASSWORD_ITERATIONS,
                        role, 1, timestamp, None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Username is already registered") from exc
        return self.get_user(user_id)

    def create_bootstrap_admin(self, username: str, display_name: str, password: str) -> dict:
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise ConflictError("Initial administrator setup is already complete")
            user_id = new_id()
            salt = secrets.token_bytes(16)
            timestamp = utc_now()
            conn.execute(
                """INSERT INTO users (
                    id, username, display_name, password_salt, password_hash,
                    password_iterations, role, active, created_at, last_login_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, username, display_name, salt.hex(),
                    _password_hash(password, salt), PASSWORD_ITERATIONS,
                    "admin", 1, timestamp, None,
                ),
            )
        return self.get_user(user_id)

    def authenticate(self, username: str, password: str) -> dict | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
            salt = bytes.fromhex(row["password_salt"]) if row else b"mma-nexus-dummy"
            iterations = row["password_iterations"] if row else PASSWORD_ITERATIONS
            candidate = _password_hash(password, salt, iterations)
            valid = bool(row and row["active"] and hmac.compare_digest(candidate, row["password_hash"]))
            if not valid:
                return None
            timestamp = utc_now()
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (timestamp, row["id"]))
            return self._public_user(row)

    def create_session(self, user_id: str) -> dict:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        timestamp = datetime.now(timezone.utc)
        expires = timestamp + timedelta(hours=SESSION_HOURS)
        iso = timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        expires_iso = expires.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.database.connect() as conn:
            conn.execute(
                """INSERT INTO auth_sessions (
                    token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (_token_hash(token), user_id, csrf, iso, expires_iso, iso),
            )
        return {"token": token, "csrfToken": csrf, "expiresAt": expires_iso}

    def get_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT u.*, s.csrf_token, s.expires_at
                   FROM auth_sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ?""",
                (_token_hash(token),),
            ).fetchone()
            if not row or not row["active"] or row["expires_at"] <= utc_now():
                if row:
                    conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(token),))
                return None
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (utc_now(), _token_hash(token)),
            )
            return {
                "user": self._public_user(row),
                "csrfToken": row["csrf_token"],
                "expiresAt": row["expires_at"],
            }

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self.database.connect() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(token),))

    def set_user_access(self, user_id: str, role: str, active: bool) -> dict:
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise NotFoundError("User not found")
            removing_admin = row["role"] == "admin" and row["active"] and (role != "admin" or not active)
            if removing_admin:
                admins = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
                ).fetchone()[0]
                if admins <= 1:
                    raise ConflictError("Cannot remove the last active administrator")
            conn.execute(
                "UPDATE users SET role = ?, active = ? WHERE id = ?",
                (role, int(active), user_id),
            )
            if not active:
                conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)

    def reset_password(self, user_id: str, password: str) -> dict:
        salt = secrets.token_bytes(16)
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                raise NotFoundError("User not found")
            conn.execute(
                """UPDATE users SET password_salt = ?, password_hash = ?,
                   password_iterations = ? WHERE id = ?""",
                (salt.hex(), _password_hash(password, salt), PASSWORD_ITERATIONS, user_id),
            )
            conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)

    def audit(
        self, user_id: str | None, action: str, entity_type: str,
        entity_id: str | None, detail: dict, ip_address: str,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """INSERT INTO audit_logs (
                    id, user_id, action, entity_type, entity_id,
                    detail_json, ip_address, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id(), user_id, action, entity_type, entity_id,
                    json.dumps(detail), ip_address[:80], utc_now(),
                ),
            )

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT a.*, u.username FROM audit_logs a
                   LEFT JOIN users u ON u.id = a.user_id
                   ORDER BY a.rowid DESC LIMIT ?""",
                (min(max(1, limit), 200),),
            ).fetchall()
            return [{
                "id": row["id"],
                "userId": row["user_id"],
                "username": row["username"],
                "action": row["action"],
                "entityType": row["entity_type"],
                "entityId": row["entity_id"],
                "detail": json.loads(row["detail_json"]),
                "ipAddress": row["ip_address"],
                "createdAt": row["created_at"],
            } for row in rows]
