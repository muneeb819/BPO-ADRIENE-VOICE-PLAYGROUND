"""Temporary preview-only authentication bypass tests."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_preview_bypass_opens_admin_without_login_and_keeps_csrf(tmp_path):
    app = create_app(tmp_path / "preview-bypass.db", preview_bypass=True)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        status = client.get("/api/v1/auth/status")
        assert status.status_code == 200
        data = status.json()
        assert data["authenticated"] is True
        assert data["requiresSetup"] is False
        assert data["previewBypass"] is True
        assert data["user"]["role"] == "admin"
        assert client.get("/api/v1/agent").status_code == 200
        blocked = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"})
        assert blocked.status_code == 403
        client.headers["X-CSRF-Token"] = data["csrfToken"]
        created = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"})
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        audit = client.get("/api/v1/auth/audit")
        assert audit.status_code == 200
        assert any(row["action"] == "session_created" for row in audit.json())
        deleted = client.delete(f"/api/v1/sessions/{session_id}")
        assert deleted.status_code == 200
