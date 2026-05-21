"""End-to-end websocket evals.

Drives the FastAPI TestClient against the real /ws/conversationrelay handler with
MockTranslator wired in. Validates the happy path plus the edge cases listed in
the PRD Behavior Contract (ignore unknown events, ignore empty frames, pong on
ping).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


WS_URL_CALLER = "/ws/conversationrelay?session_id=T1&leg=caller&caller_lang=sv-SE&agent_lang=en-US"
WS_URL_AGENT = "/ws/conversationrelay?session_id=T1&leg=agent&caller_lang=sv-SE&agent_lang=en-US"


def _drain_translated_text(ws) -> str:
    """build_token_messages emits one message per word; concatenate them until
    we see last=True to reconstruct the full translated utterance."""
    parts: list[str] = []
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "text":
            continue
        parts.append(msg["token"])
        if msg.get("last"):
            break
    return "".join(parts)


def test_health_endpoint_reports_mock_provider():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["translation_provider"] == "mock"


def test_caller_text_is_translated_and_delivered_to_agent():
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as caller, client.websocket_connect(
        WS_URL_AGENT
    ) as agent:
        caller.send_json({"event": "transcript", "text": "hej"})
        translated = _drain_translated_text(agent)
        assert translated == "[sv-SE->en-US] hej"


def test_ping_returns_pong():
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as ws:
        ws.send_json({"event": "ping"})
        response = ws.receive_json()
        assert response == {"type": "pong"}


def test_unknown_event_does_not_translate():
    """Token/output/agent_response events must be skipped, per _should_translate_event."""
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as caller, client.websocket_connect(
        WS_URL_AGENT
    ) as agent:
        caller.send_json({"event": "token", "text": "should-not-translate"})
        caller.send_json({"event": "transcript", "text": "hej"})
        # Only the second event produces output; if the filter were broken the
        # first translated text would be "[sv-SE->en-US] should-not-translate".
        translated = _drain_translated_text(agent)
        assert translated == "[sv-SE->en-US] hej"


def test_empty_text_is_silently_ignored():
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as caller, client.websocket_connect(
        WS_URL_AGENT
    ) as agent:
        caller.send_json({"event": "transcript", "text": ""})
        caller.send_json({"event": "transcript", "text": "after empty"})
        translated = _drain_translated_text(agent)
        assert translated == "[sv-SE->en-US] after empty"


def test_non_json_frame_does_not_crash():
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as caller, client.websocket_connect(
        WS_URL_AGENT
    ) as agent:
        caller.send_text("not json {")
        caller.send_json({"event": "transcript", "text": "after garbage"})
        translated = _drain_translated_text(agent)
        assert translated == "[sv-SE->en-US] after garbage"


def test_tokens_are_queued_for_late_arriving_counterpart():
    """Caller sends before agent connects -> translated tokens are queued and
    flushed when the agent leg arrives. Per session_bridge.unregister(), the
    queue is purged when ALL participants disconnect, so the agent must connect
    while the caller is still attached for this contract to hold.
    """
    client = TestClient(app)
    with client.websocket_connect(WS_URL_CALLER) as caller:
        caller.send_json({"event": "transcript", "text": "early-message"})
        with client.websocket_connect(WS_URL_AGENT) as agent:
            translated = _drain_translated_text(agent)
            assert translated == "[sv-SE->en-US] early-message"
