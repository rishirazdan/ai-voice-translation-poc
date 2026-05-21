"""Latency budget eval.

PRD primary metric: p95 turn latency under 2.5s end-to-end. This test uses the
MockTranslator (zero translation latency) so it's really a regression guard on
the overhead of the websocket loop + token emission + the fixed TTS estimate.
The real OpenAI latency is covered by the live translation test and by runtime
/metrics/latency once deployed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


P95_BUDGET_MS = 2500.0  # PRD threshold
TURNS = 50


@pytest.mark.perf
def test_p95_turn_latency_under_budget():
    client = TestClient(app)

    # Reset metrics so previous tests don't pollute this run.
    client.post("/metrics/latency/reset")

    url = "/ws/conversationrelay?session_id=PERF1&leg=caller&caller_lang=sv-SE&agent_lang=en-US"
    agent_url = "/ws/conversationrelay?session_id=PERF1&leg=agent&caller_lang=sv-SE&agent_lang=en-US"

    with client.websocket_connect(url) as caller, client.websocket_connect(agent_url) as agent:
        for i in range(TURNS):
            caller.send_json({"event": "transcript", "text": f"turn number {i}"})
            agent.receive_json()  # drain so the buffer doesn't block

    summary = client.get("/metrics/latency").json()
    assert summary["count"] >= TURNS, f"expected at least {TURNS} samples, got {summary['count']}"
    p95 = summary["p95_total_estimated_turn_ms"]
    assert p95 is not None
    assert p95 < P95_BUDGET_MS, (
        f"p95 turn latency {p95:.2f}ms exceeded PRD budget {P95_BUDGET_MS}ms. "
        f"avg_translate_ms={summary.get('avg_translate_ms')} "
        f"avg_token_emit_ms={summary.get('avg_token_emit_ms')}"
    )


@pytest.mark.perf
def test_translation_step_is_fast_under_mock():
    """The mock provider returns instantly; if avg_translate_ms creeps up, the
    translation layer added overhead."""
    client = TestClient(app)
    client.post("/metrics/latency/reset")

    url = "/ws/conversationrelay?session_id=PERF2&leg=caller&caller_lang=sv-SE&agent_lang=en-US"
    agent_url = "/ws/conversationrelay?session_id=PERF2&leg=agent&caller_lang=sv-SE&agent_lang=en-US"

    with client.websocket_connect(url) as caller, client.websocket_connect(agent_url) as agent:
        for i in range(20):
            caller.send_json({"event": "transcript", "text": f"text {i}"})
            agent.receive_json()

    summary = client.get("/metrics/latency").json()
    avg_translate = summary["avg_translate_ms"]
    assert avg_translate is not None
    assert avg_translate < 50.0, f"mock translator should be ~0ms; got avg {avg_translate:.2f}ms"
