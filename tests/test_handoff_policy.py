"""Handoff policy evals.

Maps to the PRD Risks table — every scenario where the handoff endpoint has to
make a policy decision (strict vs lenient, seamless vs reconnect, invalid input)
gets one test.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.handoff import (
    ElevenLabsHandoffRequest,
    HandoffConfigError,
    TwilioHandoffOrchestrator,
)
from tests.conftest import make_test_settings


# ---------- dry-run (no Twilio API calls) ----------


def test_dry_run_with_valid_call_sid_succeeds():
    orchestrator = TwilioHandoffOrchestrator(make_test_settings(handoff_dry_run=True))
    payload = ElevenLabsHandoffRequest(
        twilio_call_sid="CA" + "a" * 32,
        customer_number="+14155550123",
        caller_language="sv-SE",
    )
    result = orchestrator.execute(payload)
    assert result.twilio_call_sid == "CA" + "a" * 32
    assert result.agent_call_sid is not None
    assert result.conference_name.startswith("ltpoc-")


def test_dry_run_without_call_sid_still_returns_synthetic_sids():
    """In dry-run we return fake SIDs so local demos work; the strict/reconnect
    policy checks only run in live mode."""
    orchestrator = TwilioHandoffOrchestrator(make_test_settings(handoff_dry_run=True))
    payload = ElevenLabsHandoffRequest(customer_number="+14155550123", caller_language="sv-SE")
    result = orchestrator.execute(payload)
    assert result.twilio_call_sid is not None
    assert result.agent_call_sid is not None


# ---------- live mode: strict / lenient / reconnect paths ----------


def _patch_twilio_client(orchestrator: TwilioHandoffOrchestrator) -> MagicMock:
    """Replace Client construction so we never hit the real Twilio API."""
    fake_client = MagicMock()
    fake_client.calls.create.return_value.sid = "CA" + "b" * 32
    return fake_client


def test_live_strict_mode_without_call_sid_rejects():
    settings = make_test_settings(
        handoff_dry_run=False,
        require_active_call_sid_for_handoff=True,
        enable_customer_reconnect=False,
    )
    orchestrator = TwilioHandoffOrchestrator(settings)

    with patch.object(orchestrator, "_client", return_value=_patch_twilio_client(orchestrator)):
        payload = ElevenLabsHandoffRequest(customer_number="+14155550123")
        with pytest.raises(HandoffConfigError, match="twilio_call_sid is required"):
            orchestrator.execute(payload)


def test_live_strict_mode_with_valid_call_sid_updates_existing_leg():
    settings = make_test_settings(
        handoff_dry_run=False,
        require_active_call_sid_for_handoff=True,
        enable_customer_reconnect=False,
    )
    orchestrator = TwilioHandoffOrchestrator(settings)
    fake_client = _patch_twilio_client(orchestrator)

    with patch.object(orchestrator, "_client", return_value=fake_client):
        payload = ElevenLabsHandoffRequest(
            twilio_call_sid="CA" + "a" * 32,
            caller_language="sv-SE",
        )
        result = orchestrator.execute(payload)

    fake_client.calls.assert_any_call("CA" + "a" * 32)  # update path
    assert result.twilio_call_sid == "CA" + "a" * 32


def test_live_lenient_mode_without_sid_uses_reconnect_path():
    settings = make_test_settings(
        handoff_dry_run=False,
        require_active_call_sid_for_handoff=False,
        enable_customer_reconnect=True,
    )
    orchestrator = TwilioHandoffOrchestrator(settings)
    fake_client = _patch_twilio_client(orchestrator)

    with patch.object(orchestrator, "_client", return_value=fake_client):
        payload = ElevenLabsHandoffRequest(customer_number="+14155550123", caller_language="sv-SE")
        result = orchestrator.execute(payload)

    # Two .create calls: one for the customer reconnect leg, one for the agent leg.
    assert fake_client.calls.create.call_count == 2
    assert result.customer_call_sid is not None


def test_live_lenient_mode_without_sid_or_customer_number_rejects():
    settings = make_test_settings(
        handoff_dry_run=False,
        require_active_call_sid_for_handoff=False,
        enable_customer_reconnect=True,
    )
    orchestrator = TwilioHandoffOrchestrator(settings)

    with patch.object(orchestrator, "_client", return_value=_patch_twilio_client(orchestrator)):
        payload = ElevenLabsHandoffRequest()
        with pytest.raises(HandoffConfigError, match="No active customer leg available"):
            orchestrator.execute(payload)


def test_invalid_call_sid_format_rejects():
    settings = make_test_settings(handoff_dry_run=False)
    orchestrator = TwilioHandoffOrchestrator(settings)

    with patch.object(orchestrator, "_client", return_value=_patch_twilio_client(orchestrator)):
        payload = ElevenLabsHandoffRequest(twilio_call_sid="not-a-valid-sid")
        with pytest.raises(HandoffConfigError, match="invalid"):
            orchestrator.execute(payload)


def test_invalid_e164_agent_number_rejects():
    settings = make_test_settings(default_human_agent_number="not-e164")
    orchestrator = TwilioHandoffOrchestrator(settings)
    payload = ElevenLabsHandoffRequest(twilio_call_sid="CA" + "a" * 32)
    with pytest.raises(HandoffConfigError, match="valid E.164 agent number"):
        orchestrator.execute(payload)


def test_same_customer_and_agent_number_rejects():
    settings = make_test_settings()
    orchestrator = TwilioHandoffOrchestrator(settings)
    payload = ElevenLabsHandoffRequest(
        twilio_call_sid="CA" + "a" * 32,
        customer_number="+15550002222",  # same as DEFAULT_HUMAN_AGENT_NUMBER
        agent_number="+15550002222",
    )
    with pytest.raises(HandoffConfigError, match="cannot be the same"):
        orchestrator.execute(payload)


# ---------- payload aliasing (ElevenLabs sends various key names) ----------


def test_system_call_sid_alias_maps_to_twilio_call_sid():
    payload = ElevenLabsHandoffRequest.model_validate(
        {"handoff_required": True, "system__call_sid": "CA" + "c" * 32}
    )
    assert payload.twilio_call_sid == "CA" + "c" * 32


def test_caller_id_alias_maps_to_customer_number():
    payload = ElevenLabsHandoffRequest.model_validate(
        {
            "handoff_required": True,
            "twilio_call_sid": "CA" + "c" * 32,
            "system__caller_id": "+14155550123",
        }
    )
    assert payload.customer_number == "+14155550123"
