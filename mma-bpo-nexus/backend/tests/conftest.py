"""Test imports and isolated authenticated application fixtures."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.main import create_app  # noqa: E402

TEST_USERNAME = "admin"
TEST_PASSWORD = "Stage3-secure-password1"


def authenticate_client(client: TestClient) -> None:
    response = client.post("/api/v1/auth/setup", json={
        "username": TEST_USERNAME,
        "displayName": "Test Administrator",
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrfToken"]


def login_client(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrfToken"]


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "nexus-test.db")
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        authenticate_client(test_client)
        yield test_client
