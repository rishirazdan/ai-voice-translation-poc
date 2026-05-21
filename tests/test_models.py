"""Event parsing, fingerprinting, and token construction.

Covers the PRD risk row 'Twilio ConversationRelay event-shape change': the parser
must accept multiple known shapes and ignore unknowns without crashing.
"""
from app.models import (
    build_token_messages,
    parse_conversationrelay_event,
    safe_text_fingerprint,
)


def test_parses_top_level_text_field():
    event = parse_conversationrelay_event({"event": "transcript", "text": "hej"})
    assert event.event_type == "transcript"
    assert event.text == "hej"


def test_parses_nested_prompt_voiceprompt():
    event = parse_conversationrelay_event(
        {"type": "prompt", "prompt": {"voicePrompt": "hello there"}}
    )
    assert event.event_type == "prompt"
    assert event.text == "hello there"


def test_parses_nested_payload_utterance():
    event = parse_conversationrelay_event(
        {"name": "utterance", "payload": {"utterance": "good morning"}}
    )
    assert event.text == "good morning"


def test_parses_call_sid_aliases():
    event = parse_conversationrelay_event({"event": "x", "text": "y", "callSid": "CA123"})
    assert event.call_sid == "CA123"


def test_unknown_shape_does_not_raise():
    event = parse_conversationrelay_event({"weird": {"shape": True}})
    assert event.event_type == "unknown"
    assert event.text is None


def test_fingerprint_with_text():
    fp = safe_text_fingerprint("hello world")
    assert fp["length"] == 11
    assert isinstance(fp["sha256_12"], str)
    assert len(fp["sha256_12"]) == 12


def test_fingerprint_with_none():
    fp = safe_text_fingerprint(None)
    assert fp["length"] == 0
    assert fp["sha256_12"] is None


def test_fingerprint_is_deterministic():
    a = safe_text_fingerprint("same text")
    b = safe_text_fingerprint("same text")
    assert a["sha256_12"] == b["sha256_12"]


def test_token_messages_split_and_flag_last():
    messages = build_token_messages("hello world")
    assert len(messages) == 2
    assert messages[0] == {"type": "text", "token": "hello ", "last": False}
    assert messages[1] == {"type": "text", "token": "world", "last": True}


def test_token_messages_empty_input():
    assert build_token_messages("") == []
    assert build_token_messages("   ") == []
