import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConversationRelayEvent:
    event_type: str
    call_sid: str | None
    text: str | None
    source_language: str | None
    target_language: str | None
    payload: dict[str, Any]


def _extract_text(payload: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        payload.get("text"),
        payload.get("token"),
        payload.get("utterance"),
        payload.get("voicePrompt"),
        payload.get("prompt"),
        payload.get("transcript"),
        payload.get("speechText"),
    ]

    nested_paths = [
        ("speech", "text"),
        ("transcript", "text"),
        ("message", "text"),
        ("payload", "text"),
        ("payload", "utterance"),
        ("payload", "voicePrompt"),
        ("prompt", "text"),
        ("prompt", "voicePrompt"),
        ("data", "text"),
        ("data", "voicePrompt"),
    ]

    for first, second in nested_paths:
        node = payload.get(first)
        if isinstance(node, dict):
            candidates.append(node.get(second))

    for value in candidates:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None


def parse_conversationrelay_event(payload: dict[str, Any]) -> ConversationRelayEvent:
    event_type = (
        payload.get("event")
        or payload.get("type")
        or payload.get("name")
        or payload.get("eventType")
        or "unknown"
    )

    call_sid = (
        payload.get("callSid")
        or payload.get("call_sid")
        or payload.get("sessionId")
        or payload.get("session_id")
    )

    source_language = (
        payload.get("sourceLanguage")
        or payload.get("source_language")
        or payload.get("language")
        or payload.get("lang")
    )
    target_language = payload.get("targetLanguage") or payload.get("target_language")

    return ConversationRelayEvent(
        event_type=str(event_type),
        call_sid=str(call_sid) if call_sid is not None else None,
        text=_extract_text(payload),
        source_language=str(source_language) if source_language is not None else None,
        target_language=str(target_language) if target_language is not None else None,
        payload=payload,
    )


def safe_text_fingerprint(text: str | None) -> dict[str, Any]:
    if not text:
        return {"length": 0, "sha256_12": None}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return {"length": len(text), "sha256_12": digest}


def build_token_messages(text: str, *, lang: str | None = None) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    parts = text.strip().split()
    result: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        token = part + (" " if index < len(parts) - 1 else "")
        message: dict[str, Any] = {
            "type": "text",
            "token": token,
            "last": index == len(parts) - 1,
        }
        cleaned_lang = (lang or "").strip()
        if cleaned_lang:
            message["lang"] = cleaned_lang
        result.append(message)
    return result
