"""Security evals.

The ElevenLabs handoff webhook is the most exposed surface — anyone with the URL
could trigger calls if the shared-secret check is off or broken. These tests
verify the gate works in both directions.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.handoff import TwilioHandoffOrchestrator
from app.main import app
from tests.conftest import make_test_settings


VALID_SID = "CA" + "a" * 32


def _enable_secret(monkeypatch) -> None:
    settings = make_test_settings(
        require_elevenlabs_handoff_secret=True,
        elevenlabs_handoff_secret="test-shared-secret",
    )
    monkeypatch.setattr(app_main, "settings", settings)
    monkeypatch.setattr(app_main, "handoff_orchestrator", TwilioHandoffOrchestrator(settings))


def test_handoff_rejects_missing_secret_when_required(monkeypatch):
    _enable_secret(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/handoff/elevenlabs",
        json={"handoff_required": True, "twilio_call_sid": VALID_SID, "customer_number": "+14155550123"},
    )
    assert response.status_code == 403


def test_handoff_rejects_wrong_secret_when_required(monkeypatch):
    _enable_secret(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/handoff/elevenlabs",
        json={"handoff_required": True, "twilio_call_sid": VALID_SID, "customer_number": "+14155550123"},
        headers={"X-ElevenLabs-Handoff-Secret": "wrong"},
    )
    assert response.status_code == 403


def test_handoff_accepts_correct_secret_when_required(monkeypatch):
    _enable_secret(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/handoff/elevenlabs",
        json={"handoff_required": True, "twilio_call_sid": VALID_SID, "customer_number": "+14155550123"},
        headers={"X-ElevenLabs-Handoff-Secret": "test-shared-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "handoff_started"


def test_handoff_allows_no_header_when_secret_not_required():
    """With the autouse fixture, require_elevenlabs_handoff_secret defaults to False."""
    client = TestClient(app)
    response = client.post(
        "/handoff/elevenlabs",
        json={"handoff_required": True, "twilio_call_sid": VALID_SID, "customer_number": "+14155550123"},
    )
    assert response.status_code == 200


def test_handoff_required_false_returns_400():
    client = TestClient(app)
    response = client.post(
        "/handoff/elevenlabs",
        json={"handoff_required": False, "twilio_call_sid": VALID_SID},
    )
    assert response.status_code == 400
