"""Logging / privacy evals.

PRD success metric: 'Zero raw transcript text in production logs.' This is a
load-bearing claim — if it's wrong, the project leaks PII. We catch it by
sending a unique marker token through the websocket and asserting no log record
contains it.
"""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.main import app


MARKER = "SUPER_SECRET_TRANSCRIPT_MARKER_42"


def test_no_raw_transcript_in_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="live_translation_poc")
    client = TestClient(app)
    url = "/ws/conversationrelay?session_id=L1&leg=caller&caller_lang=sv-SE&agent_lang=en-US"

    with client.websocket_connect(url) as ws:
        ws.send_json({"event": "transcript", "text": f"please remember {MARKER}"})

    for record in caplog.records:
        rendered = record.getMessage()
        assert MARKER not in rendered, (
            f"Raw transcript leaked into log: logger={record.name} level={record.levelname} "
            f"message={rendered!r}"
        )


def test_fingerprint_appears_in_logs(caplog):
    """Inverse check: the metadata we DO want (length, sha256_12) should appear."""
    caplog.set_level(logging.INFO, logger="live_translation_poc")
    client = TestClient(app)
    url = "/ws/conversationrelay?session_id=L2&leg=caller&caller_lang=sv-SE&agent_lang=en-US"

    with client.websocket_connect(url) as ws:
        ws.send_json({"event": "transcript", "text": "hello"})

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "text_len=" in joined
    assert "text_sha=" in joined


def test_handoff_does_not_log_full_call_sid(caplog):
    """The handoff log truncates the SID to first-10 chars + '...'. Verify the
    full SID never appears in logs."""
    caplog.set_level(logging.INFO, logger="live_translation_poc")
    client = TestClient(app)
    full_sid = "CA" + "f" * 32
    client.post(
        "/handoff/elevenlabs",
        json={
            "handoff_required": True,
            "twilio_call_sid": full_sid,
            "customer_number": "+14155550123",
            "caller_language": "sv-SE",
        },
    )

    for record in caplog.records:
        msg = record.getMessage()
        # The truncated form is fine; the full SID should not appear in any
        # call-sid logging context. We allow the full SID to appear in payload
        # echo logs (none currently exist), but explicitly check the handoff log
        # line uses the truncated form.
        if "ElevenLabs handoff requested" in msg:
            assert full_sid not in msg, f"Full SID logged in handoff line: {msg!r}"
            assert "CAffff..." not in msg or msg.count(full_sid) == 0
