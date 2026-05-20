from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from requests.exceptions import RequestException
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, ConversationRelay, Say, VoiceResponse

from app.config import Settings, get_runtime_websocket_url

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
TWILIO_CALL_SID_PATTERN = re.compile(r"^CA[0-9a-fA-F]{32}$")
logger = logging.getLogger("live_translation_poc")


def _extract_string(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, dict):
        for key in ("value", "phone", "phone_number", "number", "text"):
            nested = _extract_string(value.get(key))
            if nested:
                return nested
    return None


def _find_string_recursive(value: object, candidate_keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in candidate_keys:
            if key in value:
                found = _extract_string(value.get(key))
                if found:
                    return found
        for nested_value in value.values():
            found = _find_string_recursive(nested_value, candidate_keys)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_string_recursive(item, candidate_keys)
            if found:
                return found
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            return _find_string_recursive(parsed, candidate_keys)
    return None


class ElevenLabsHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    handoff_required: bool = True
    twilio_call_sid: str | None = None
    customer_number: str | None = None
    agent_number: str | None = None
    human_agent_number: str | None = None
    session_id: str | None = None
    caller_language: str | None = None
    agent_language: str | None = None
    reason: str | None = None
    context_summary: str | None = Field(default=None, max_length=1_500)

    @model_validator(mode="before")
    @classmethod
    def _map_common_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        if not _extract_string(data.get("twilio_call_sid")):
            twilio_call_sid = _find_string_recursive(
                data,
                (
                    "twilio_call_sid",
                    "twilioCallSid",
                    "call_sid",
                    "callSid",
                    "system__call_sid",
                    "system__twilio_call_sid",
                    "customer_call_sid",
                    "active_call_sid",
                ),
            )
            if twilio_call_sid:
                data["twilio_call_sid"] = twilio_call_sid
        else:
            data["twilio_call_sid"] = _extract_string(data.get("twilio_call_sid"))

        if not _extract_string(data.get("customer_number")):
            customer_number = _find_string_recursive(
                data,
                (
                    "customer_number",
                    "system__caller_id",
                    "caller_id",
                    "caller_number",
                    "customer_phone",
                    "from",
                    "from_number",
                    "phone_number",
                ),
            )
            if customer_number:
                data["customer_number"] = customer_number
        else:
            data["customer_number"] = _extract_string(data.get("customer_number"))

        if not _extract_string(data.get("agent_number")):
            agent_number = _find_string_recursive(
                data,
                (
                    "agent_number",
                    "human_agent_number",
                    "agent_phone_number",
                    "human_agent_phone_number",
                ),
            )
            if agent_number:
                data["agent_number"] = agent_number
        else:
            data["agent_number"] = _extract_string(data.get("agent_number"))

        if not _extract_string(data.get("caller_language")):
            caller_language = _find_string_recursive(
                data,
                (
                    "caller_language",
                    "caller_lang",
                    "customer_language",
                    "source_language",
                    "language",
                ),
            )
            if caller_language:
                data["caller_language"] = caller_language
        else:
            data["caller_language"] = _extract_string(data.get("caller_language"))

        if not _extract_string(data.get("agent_language")):
            agent_language = _find_string_recursive(
                data,
                (
                    "agent_language",
                    "agent_lang",
                    "human_agent_language",
                    "target_language",
                ),
            )
            if agent_language:
                data["agent_language"] = agent_language
        else:
            data["agent_language"] = _extract_string(data.get("agent_language"))

        return data


class ElevenLabsHandoffResponse(BaseModel):
    status: str
    mode: str
    conference_name: str
    session_id: str
    twilio_call_sid: str | None = None
    agent_call_sid: str | None = None
    customer_call_sid: str | None = None
    caller_language: str
    agent_language: str


@dataclass(frozen=True)
class HandoffResult:
    conference_name: str
    session_id: str
    twilio_call_sid: str | None
    agent_call_sid: str | None
    customer_call_sid: str | None


class HandoffConfigError(RuntimeError):
    pass


class HandoffExecutionError(RuntimeError):
    pass


def is_valid_e164(phone_number: str | None) -> bool:
    if not phone_number:
        return False
    return bool(E164_PATTERN.match(phone_number))


def is_valid_twilio_call_sid(value: str | None) -> bool:
    if not value:
        return False
    return bool(TWILIO_CALL_SID_PATTERN.match(value.strip()))


def normalize_phone(phone_number: str | None) -> str:
    if not phone_number:
        return ""
    return re.sub(r"\D", "", phone_number)


def safe_reason_fingerprint(reason: str | None, context_summary: str | None) -> str | None:
    combined = ((reason or "") + "|" + (context_summary or "")).strip("|")
    if not combined:
        return None
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]


def build_conference_name(session_id: str) -> str:
    compact = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:36]
    if not compact:
        compact = uuid4().hex[:12]
    return f"ltpoc-{compact}"


def relay_twiml(
    ws_url: str,
    *,
    language: str,
    transcription_language: str,
    tts_language: str,
    tts_provider: str,
) -> str:
    response = VoiceResponse()
    connect = Connect()
    relay = ConversationRelay(
        url=ws_url,
        language=language,
        transcriptionLanguage=transcription_language,
        ttsLanguage=tts_language,
    )
    relay.language(
        code=tts_language,
        tts_provider=tts_provider or None,
    )
    connect.append(relay)
    response.append(connect)
    return str(response)


def reconnect_relay_twiml(
    ws_url: str,
    *,
    language: str,
    transcription_language: str,
    tts_language: str,
    tts_provider: str,
    announcement: str,
) -> str:
    response = VoiceResponse()
    if announcement:
        response.append(Say(announcement))
    connect = Connect()
    relay = ConversationRelay(
        url=ws_url,
        language=language,
        transcriptionLanguage=transcription_language,
        ttsLanguage=tts_language,
    )
    relay.language(
        code=tts_language,
        tts_provider=tts_provider or None,
    )
    connect.append(relay)
    response.append(connect)
    return str(response)


class TwilioHandoffOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self) -> Client:
        if not self.settings.twilio_account_sid or not self.settings.twilio_auth_token:
            raise HandoffConfigError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required.")
        return Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    def execute(self, payload: ElevenLabsHandoffRequest) -> HandoffResult:
        session_id = payload.session_id or payload.twilio_call_sid or uuid4().hex
        conference_name = build_conference_name(session_id)
        agent_number = (
            payload.agent_number
            or payload.human_agent_number
            or self.settings.default_human_agent_number
        )
        customer_number = payload.customer_number

        if not is_valid_e164(agent_number):
            raise HandoffConfigError(
                "A valid E.164 agent number is required (agent_number or DEFAULT_HUMAN_AGENT_NUMBER)."
            )

        if not is_valid_e164(self.settings.twilio_handoff_from_number):
            raise HandoffConfigError("TWILIO_HANDOFF_FROM_NUMBER must be valid E.164.")

        if is_valid_e164(customer_number) and normalize_phone(customer_number) == normalize_phone(
            agent_number
        ):
            raise HandoffConfigError(
                "customer_number and agent_number cannot be the same phone number."
            )

        if self.settings.handoff_dry_run:
            twilio_sid = payload.twilio_call_sid or f"CA{uuid4().hex[:32]}"
            agent_sid = f"CA{uuid4().hex[:32]}"
            customer_sid = f"CA{uuid4().hex[:32]}" if payload.customer_number else None
            return HandoffResult(
                conference_name=conference_name,
                session_id=session_id,
                twilio_call_sid=twilio_sid,
                agent_call_sid=agent_sid,
                customer_call_sid=customer_sid,
            )

        try:
            client = self._client()
            caller_lang = payload.caller_language or self.settings.default_caller_language
            _ = payload.agent_language  # accepted for compatibility, ignored by policy
            agent_lang = self.settings.default_agent_language
            websocket_base_url = get_runtime_websocket_url(self.settings)
            customer_query = urlencode(
                {
                    "session_id": session_id,
                    "leg": "caller",
                    "caller_lang": caller_lang,
                    "agent_lang": agent_lang,
                }
            )
            agent_query = urlencode(
                {
                    "session_id": session_id,
                    "leg": "agent",
                    "caller_lang": caller_lang,
                    "agent_lang": agent_lang,
                }
            )
            customer_leg_twiml = relay_twiml(
                f"{websocket_base_url}?{customer_query}",
                language=caller_lang,
                transcription_language=caller_lang,
                tts_language=caller_lang,
                tts_provider=self.settings.tts_provider,
            )
            agent_leg_twiml = relay_twiml(
                f"{websocket_base_url}?{agent_query}",
                language=agent_lang,
                transcription_language=agent_lang,
                tts_language=agent_lang,
                tts_provider=self.settings.tts_provider,
            )

            twilio_call_sid = (payload.twilio_call_sid or "").strip() or None
            customer_call_sid: str | None = None
            if self.settings.require_active_call_sid_for_handoff and not twilio_call_sid:
                raise HandoffConfigError(
                    "twilio_call_sid is required for seamless handoff. "
                    "Configure ElevenLabs to pass system__call_sid."
                )
            if twilio_call_sid:
                if not is_valid_twilio_call_sid(twilio_call_sid):
                    raise HandoffConfigError(
                        "twilio_call_sid is present but invalid. Expected Twilio Call SID format: CA + 32 hex chars."
                    )
                client.calls(twilio_call_sid).update(twiml=customer_leg_twiml)
            else:
                if self.settings.require_active_call_sid_for_handoff:
                    raise HandoffConfigError(
                        "Customer callback path is disabled. Provide a valid twilio_call_sid from ElevenLabs."
                    )
                if self.settings.enable_customer_reconnect and is_valid_e164(customer_number):
                    if normalize_phone(customer_number) == normalize_phone(
                        self.settings.twilio_handoff_from_number
                    ):
                        raise HandoffConfigError(
                            "customer_number cannot be the same as TWILIO_HANDOFF_FROM_NUMBER. "
                            "Pass the real caller number or provide twilio_call_sid."
                        )
                    customer_reconnect_twiml = reconnect_relay_twiml(
                        f"{websocket_base_url}?{customer_query}",
                        language=caller_lang,
                        transcription_language=caller_lang,
                        tts_language=caller_lang,
                        tts_provider=self.settings.tts_provider,
                        announcement=self.settings.customer_reconnect_announcement,
                    )
                    logger.warning(
                        "FALLBACK_RECONNECT_USED session_id=%s customer_number_suffix=%s",
                        session_id,
                        customer_number[-4:],
                    )
                    customer_call = client.calls.create(
                        from_=self.settings.twilio_handoff_from_number,
                        to=customer_number,
                        twiml=customer_reconnect_twiml,
                    )
                    customer_call_sid = customer_call.sid
                else:
                    raise HandoffConfigError(
                        "No active customer leg available. Provide twilio_call_sid from ElevenLabs "
                        "or pass a valid customer_number with ENABLE_CUSTOMER_RECONNECT=true."
                    )

            agent_call = client.calls.create(
                from_=self.settings.twilio_handoff_from_number,
                to=agent_number,
                twiml=agent_leg_twiml,
            )
            return HandoffResult(
                conference_name=conference_name,
                session_id=session_id,
                twilio_call_sid=twilio_call_sid,
                agent_call_sid=agent_call.sid,
                customer_call_sid=customer_call_sid,
            )
        except TwilioRestException as exc:
            raise HandoffExecutionError(f"Twilio handoff failed: {exc.msg}") from exc
        except RequestException as exc:
            raise HandoffExecutionError(f"Twilio API connection failed: {exc}") from exc
