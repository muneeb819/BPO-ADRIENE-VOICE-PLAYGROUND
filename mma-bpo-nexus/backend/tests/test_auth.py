"""Authentication, authorization, retention, and audit tests."""

import json
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from conftest import TEST_PASSWORD, TEST_USERNAME, authenticate_client, login_client


def raw_client(tmp_path, name="auth.db"):
    return TestClient(
        create_app(tmp_path / name),
        base_url="https://testserver",
        raise_server_exceptions=False,
    )


def test_bootstrap_secure_cookie_and_setup_lockout(tmp_path):
    with raw_client(tmp_path) as client:
        initial = client.get("/api/v1/auth/status")
        assert initial.json() == {"requiresSetup": True, "authenticated": False}
        assert client.get("/api/v1/agent").status_code == 401
        weak = client.post("/api/v1/auth/setup", json={
            "username": "admin", "displayName": "Admin", "password": "short",
        })
        assert weak.status_code == 422
        authenticate_client(client)
        status = client.get("/api/v1/auth/status").json()
        assert status["authenticated"] is True
        assert status["user"]["role"] == "admin"
        assert status["csrfToken"]
        cookie = client.cookies.get("mma_nexus_session")
        assert cookie and len(cookie) > 40
        with sqlite3.connect(tmp_path / "auth.db") as conn:
            stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
            token_hash = conn.execute("SELECT token_hash FROM auth_sessions").fetchone()[0]
        assert stored != TEST_PASSWORD
        assert token_hash != cookie
        repeated = client.post("/api/v1/auth/setup", json={
            "username": "another", "displayName": "Another", "password": "Another-password1",
        })
        assert repeated.status_code == 409


def test_login_logout_and_csrf_enforcement(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        client.headers.pop("X-CSRF-Token")
        assert client.post("/api/v1/auth/logout").status_code == 403
        login_client(client)
        response = client.post("/api/v1/auth/logout", headers={
            "X-CSRF-Token": client.get("/api/v1/auth/status").json()["csrfToken"]
        })
        assert response.status_code == 200
        assert client.get("/api/v1/auth/status").json()["authenticated"] is False
        wrong = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert wrong.status_code == 401
        assert wrong.json()["error"] == "Invalid username or password"
        login_client(client)
        assert client.get("/api/v1/auth/me").json()["user"]["username"] == TEST_USERNAME


def test_viewer_is_read_only_and_cannot_manage_users(tmp_path):
    with raw_client(tmp_path) as admin:
        authenticate_client(admin)
        created = admin.post("/api/v1/auth/users", json={
            "username": "viewer",
            "displayName": "Read Only",
            "password": "Viewer-password1",
            "role": "viewer",
        })
        assert created.status_code == 200, created.text
        viewer_id = created.json()["id"]
        with raw_client(tmp_path) as viewer:
            login = viewer.post("/api/v1/auth/login", json={
                "username": "viewer", "password": "Viewer-password1",
            })
            assert login.status_code == 200
            viewer.headers["X-CSRF-Token"] = login.json()["csrfToken"]
            assert viewer.get("/api/v1/agent").status_code == 200
            assert viewer.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).status_code == 403
            assert viewer.put("/api/v1/agent/mma-nexus-intake", json={}).status_code == 403
            assert viewer.get("/api/v1/auth/users").status_code == 403
            assert viewer.post("/api/v1/auth/logout").status_code == 200
        changed = admin.patch(f"/api/v1/auth/users/{viewer_id}", json={"role": "viewer", "active": False})
        assert changed.status_code == 200
        assert changed.json()["active"] is False


def test_last_admin_cannot_be_demoted_or_deactivated(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        user = client.get("/api/v1/auth/status").json()["user"]
        demote = client.patch(f"/api/v1/auth/users/{user['id']}", json={"role": "viewer", "active": True})
        assert demote.status_code == 409
        deactivate = client.patch(f"/api/v1/auth/users/{user['id']}", json={"role": "admin", "active": False})
        assert deactivate.status_code == 409


def test_password_reset_invalidates_existing_sessions(tmp_path):
    with raw_client(tmp_path) as admin:
        authenticate_client(admin)
        created = admin.post("/api/v1/auth/users", json={
            "username": "viewer", "displayName": "Viewer", "password": "Viewer-password1", "role": "viewer",
        }).json()
        with raw_client(tmp_path) as viewer:
            login = viewer.post("/api/v1/auth/login", json={"username": "viewer", "password": "Viewer-password1"})
            viewer.headers["X-CSRF-Token"] = login.json()["csrfToken"]
            assert viewer.get("/api/v1/auth/status").json()["authenticated"] is True
            reset = admin.post(f"/api/v1/auth/users/{created['id']}/password", json={"password": "New-viewer-password2"})
            assert reset.status_code == 200
            assert viewer.get("/api/v1/auth/status").json()["authenticated"] is False
            old = viewer.post("/api/v1/auth/login", json={"username": "viewer", "password": "Viewer-password1"})
            assert old.status_code == 401
            new = viewer.post("/api/v1/auth/login", json={"username": "viewer", "password": "New-viewer-password2"})
            assert new.status_code == 200


def test_retention_removes_only_expired_sessions(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        old = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        with sqlite3.connect(tmp_path / "auth.db") as conn:
            conn.execute("UPDATE sessions SET started_at = '2020-01-01T00:00:00Z' WHERE id = ?", (old["id"],))
        saved = client.put("/api/v1/auth/retention", json={"transcriptDays": 1, "autoDelete": True})
        assert saved.status_code == 200
        assert saved.json()["autoDelete"] is True
        cleaned = client.post("/api/v1/auth/retention/cleanup")
        assert cleaned.status_code == 200
        assert cleaned.json()["deletedSessions"] == 1
        assert client.get(f"/api/v1/sessions/{old['id']}").status_code == 404
        assert client.get(f"/api/v1/sessions/{current['id']}").status_code == 200
        audit = client.get("/api/v1/auth/audit").json()
        assert any(row["action"] == "retention_cleanup" for row in audit)


def test_retention_disabled_preserves_expired_sessions(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        with sqlite3.connect(tmp_path / "auth.db") as conn:
            conn.execute("UPDATE sessions SET started_at = '2020-01-01T00:00:00Z' WHERE id = ?", (current["id"],))
        client.put("/api/v1/auth/retention", json={"transcriptDays": 1, "autoDelete": False})
        cleaned = client.post("/api/v1/auth/retention/cleanup")
        assert cleaned.json()["deletedSessions"] == 0
        assert client.get(f"/api/v1/sessions/{current['id']}").status_code == 200


def test_session_export_and_delete(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        exported = client.get(f"/api/v1/sessions/{current['id']}/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        payload = json.loads(exported.content)
        assert payload["id"] == current["id"]
        assert payload["turns"][0]["content"]
        deleted = client.delete(f"/api/v1/sessions/{current['id']}")
        assert deleted.status_code == 200
        assert client.get(f"/api/v1/sessions/{current['id']}").status_code == 404
        assert client.delete(f"/api/v1/sessions/{current['id']}").status_code == 404


def test_backup_copy_is_readable(tmp_path):
    with raw_client(tmp_path) as client:
        authenticate_client(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        source = sqlite3.connect(tmp_path / "auth.db")
        backup_path = tmp_path / "backup.db"
        destination = sqlite3.connect(backup_path)
        source.backup(destination)
        source.close()
        destination.close()
        with sqlite3.connect(backup_path) as backup:
            restored_id = backup.execute("SELECT id FROM sessions WHERE id = ?", (current["id"],)).fetchone()[0]
        assert restored_id == current["id"]
