"""Shared fixtures.

The app's `config.py` calls `load_dotenv(override=True)` at import time, which
means any local `.env` shadows process env vars. To get deterministic tests we
build `Settings` directly and patch the module-level globals in `app.main`.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import pytest

from app.config import Settings
from app.handoff import TwilioHandoffOrchestrator
from app.latency import LatencyTracker
from app.translation import MockTranslator


GOLDEN_PATH = Path(__file__).parent / "data" / "translation_golden.json"


def _make_test_settings(**overrides: object) -> Settings:
    base = Settings(
        app_host="127.0.0.1",
        app_port=8010,
        public_base_url="https://test.example.com",
        twilio_account_sid="ACtest1234567890abcdef1234567890ab",
        twilio_auth_token="test_token",
        require_twilio_signature=False,
        conversation_relay_ws_path="/ws/conversationrelay",
        default_caller_language="sv-SE",
        default_agent_language="en-US",
        translation_provider="mock",
        openai_api_key="",
        openai_translation_model="gpt-4.1-mini",
        require_elevenlabs_handoff_secret=False,
        elevenlabs_handoff_secret="test-shared-secret",
        twilio_handoff_from_number="+15550001111",
        default_human_agent_number="+15550002222",
        require_active_call_sid_for_handoff=False,
        handoff_dry_run=True,
        enable_customer_reconnect=True,
        customer_reconnect_announcement="Please stay available. Reconnecting now.",
        latency_sample_size=500,
        estimated_tts_ms_per_turn=650.0,
        log_level="INFO",
        tts_provider="ElevenLabs",
        transcription_provider="Deepgram",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def test_settings() -> Settings:
    return _make_test_settings()


@pytest.fixture
def strict_settings() -> Settings:
    return _make_test_settings(
        require_active_call_sid_for_handoff=True,
        enable_customer_reconnect=False,
    )


@pytest.fixture(autouse=True)
def patch_app_globals(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Replace app.main module-level globals with test instances.

    autouse so every test gets a clean app state. Tests that need different
    settings (e.g. security tests with the secret enforced) can override by
    patching app.main.settings inside the test.
    """
    from app import main as app_main

    settings = _make_test_settings()
    monkeypatch.setattr(app_main, "settings", settings)
    monkeypatch.setattr(app_main, "translator", MockTranslator())
    monkeypatch.setattr(app_main, "handoff_orchestrator", TwilioHandoffOrchestrator(settings))
    monkeypatch.setattr(
        app_main,
        "latency_tracker",
        LatencyTracker(sample_size=settings.latency_sample_size),
    )
    yield settings


@pytest.fixture
def golden_cases() -> list[dict]:
    with GOLDEN_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def make_test_settings(**overrides: object) -> Settings:
    """Helper for tests that need a fresh Settings instance with overrides."""
    return _make_test_settings(**overrides)
