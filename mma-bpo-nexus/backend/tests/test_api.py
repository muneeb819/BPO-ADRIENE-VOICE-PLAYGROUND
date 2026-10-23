"""Isolated API and persistence tests for the Stage 1 vertical slice."""

from app.main import create_app
from conftest import login_client
from fastapi.testclient import TestClient


def create_session(client):
    response = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"})
    assert response.status_code == 201, response.text
    return response.json()


def turn(client, session_id, content):
    response = client.post(f"/api/v1/sessions/{session_id}/turns", json={"content": content})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_static_security_headers(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["service"] == "MMA BPO NEXUS"
    assert health.json()["stage"] == 4
    assert health.json()["audioStored"] is False
    assert health.json()["voice"]["deepgramConfigured"] is False
    assert health.json()["realTelephony"] is False
    page = client.get("/")
    assert page.status_code == 200
    assert "MMA BPO NEXUS" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["x-request-id"]
    assert "https://" not in page.text


def test_custom_greeting_and_version_immutability(client):
    first = create_session(client)
    assert first["agentVersion"] == 1
    assert "welcome to MMA BPO NEXUS" in first["turns"][0]["content"]
    updated = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "MMA Nexus Custom",
        "campaign": "Safe intake",
        "greeting": "This is my exact custom greeting for every new session.",
        "transfersEnabled": True,
        "requireConsent": True,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    existing = client.get(f"/api/v1/sessions/{first['id']}").json()
    assert existing["agentVersion"] == 1
    assert existing["turns"][0]["content"] == first["turns"][0]["content"]
    second = create_session(client)
    assert second["agentVersion"] == 2
    assert second["turns"][0]["content"] == "This is my exact custom greeting for every new session."
    versions = client.get("/api/v1/agent/mma-nexus-intake/versions")
    assert versions.status_code == 200
    assert [row["version"] for row in versions.json()] == [2, 1]


def test_complete_policy_flow_creates_only_pending_transfer(client):
    current = create_session(client)
    session_id = current["id"]
    assert turn(client, session_id, "Yes, I am the account holder")["state"]["stage"] == "zip"
    assert turn(client, session_id, "90210")["state"]["stage"] == "coverage"
    current = turn(client, session_id, "Yes, I have insurance")
    assert current["state"]["eligibility"] == "preliminary_eligible"
    current = turn(client, session_id, "Yes, I would like a specialist")
    assert current["state"]["stage"] == "consent_pending"
    assert current["transfers"] == []
    current = turn(client, session_id, "Yes, I consent")
    assert current["status"] == "pending_transfer"
    assert current["state"]["transferStatus"] == "pending"
    assert len(current["transfers"]) == 1
    assert current["transfers"][0]["status"] == "pending"
    assert current["transfers"][0]["reason"] == "no_live_adapter_connected"
    assert any(event["type"] == "consent_recorded" for event in current["events"])
    assistant_turns = [row for row in current["turns"] if row["role"] == "assistant" and row["intent"] != "greeting"]
    assert all(row["latencyMs"] >= 0.01 for row in assistant_turns)
    closed = client.post(f"/api/v1/sessions/{session_id}/turns", json={"content": "hello"})
    assert closed.status_code == 409


def test_non_account_holder_path_is_safe(client):
    current = create_session(client)
    current = turn(client, current["id"], "No, I am not the account holder")
    assert current["status"] == "completed"
    assert current["state"]["eligibility"] == "not_assessed"
    assert current["transfers"] == []


def test_disabled_transfer_policy_is_enforced_through_api(client):
    updated = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "MMA Nexus Intake",
        "campaign": "Inbound service qualification",
        "greeting": "This greeting is long enough for the disabled transfer test.",
        "transfersEnabled": False,
        "requireConsent": False,
    })
    assert updated.status_code == 200
    current = create_session(client)
    current = turn(client, current["id"], "Transfer to a human")
    assert current["state"]["transferStatus"] == "blocked"
    assert current["status"] == "active"
    assert current["transfers"] == []


def test_transcripts_persist_across_application_instances(client, tmp_path):
    current = create_session(client)
    session_id = current["id"]
    turn(client, session_id, "Yes, I am the account holder")
    database = tmp_path / "nexus-test.db"
    # The fixture app uses this same isolated path. A second factory proves reload.
    with TestClient(create_app(database), base_url="https://testserver", raise_server_exceptions=False) as restarted:
        login_client(restarted)
        restored = restarted.get(f"/api/v1/sessions/{session_id}")
        assert restored.status_code == 200
        assert len(restored.json()["turns"]) == 3
        assert restored.json()["state"]["accountHolder"] is True


def test_end_session_and_history(client):
    current = create_session(client)
    ended = client.post(f"/api/v1/sessions/{current['id']}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "completed"
    assert ended.json()["state"]["outcome"] == "operator_ended"
    history = client.get("/api/v1/sessions?limit=1")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["id"] == current["id"]


def test_input_and_query_validation(client):
    current = create_session(client)
    whitespace = client.post(f"/api/v1/sessions/{current['id']}/turns", json={"content": "   "})
    assert whitespace.status_code == 422
    oversized = client.post(f"/api/v1/sessions/{current['id']}/turns", json={"content": "x" * 2001})
    assert oversized.status_code == 422
    bad_limit = client.get("/api/v1/sessions?limit=0")
    assert bad_limit.status_code == 422
    bad_agent = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "x", "campaign": "bad", "greeting": "short",
        "transfersEnabled": True, "requireConsent": True,
    })
    assert bad_agent.status_code == 422


def test_cross_site_and_non_json_writes_are_rejected(client):
    cross_site = client.post(
        "/api/v1/sessions",
        json={"agentId": "mma-nexus-intake"},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert cross_site.status_code == 403
    text_plain = client.post(
        "/api/v1/sessions",
        content='{"agentId":"mma-nexus-intake"}',
        headers={"Content-Type": "text/plain"},
    )
    assert text_plain.status_code == 415
    assert client.get("/api/v1/sessions").json() == []


def test_missing_resources_return_safe_errors(client):
    missing = client.get("/api/v1/sessions/not-a-session")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Session not found"}
    unknown_agent = client.post("/api/v1/sessions", json={"agentId": "not-an-agent"})
    assert unknown_agent.status_code == 404
    assert unknown_agent.json() == {"error": "Agent not found"}
