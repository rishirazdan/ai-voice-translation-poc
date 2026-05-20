import json
import logging
import time
from collections.abc import Mapping
from uuid import uuid4
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, ConversationRelay, VoiceResponse

from app.config import get_runtime_websocket_url, get_settings
from app.handoff import (
    ElevenLabsHandoffRequest,
    ElevenLabsHandoffResponse,
    HandoffConfigError,
    HandoffExecutionError,
    TwilioHandoffOrchestrator,
    safe_reason_fingerprint,
)
from app.latency import LatencyTracker, TurnLatencyMetric
from app.models import build_token_messages, parse_conversationrelay_event, safe_text_fingerprint
from app.session_bridge import BridgeSessionRegistry
from app.translation import create_translator


settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("live_translation_poc")
app = FastAPI(title="Live Translation PoC", version="0.1.0")
translator = create_translator(settings)
registry = BridgeSessionRegistry()
handoff_orchestrator = TwilioHandoffOrchestrator(settings)
latency_tracker = LatencyTracker(sample_size=settings.latency_sample_size)


def _build_relay_for_leg(
    *,
    url: str,
    language: str,
    transcription_language: str,
    tts_language: str,
) -> ConversationRelay:
    relay = ConversationRelay(
        url=url,
        language=language,
        transcriptionLanguage=transcription_language,
        ttsLanguage=tts_language,
    )
    relay.language(
        code=transcription_language,
        tts_provider=settings.tts_provider or None,
    )
    return relay


def _should_translate_event(event_type: str) -> bool:
    normalized = event_type.strip().lower()
    if normalized in {"start", "connected", "media", "heartbeat", "ping", "ready"}:
        return False
    # Keep a permissive allow-list for common user-utterance events.
    if normalized in {"prompt", "speech", "utterance", "transcript", "message", "input"}:
        return True
    # Unknown events may still include utterance text; process only if they are not obvious output/token events.
    noisy_markers = ("token", "output", "assistant", "agent_response")
    return not any(marker in normalized for marker in noisy_markers)


def _pick_runtime_language(
    request: Request,
    form_data: object,
    *,
    keys: tuple[str, ...],
    fallback: str,
) -> str:
    if isinstance(form_data, Mapping):
        for key in keys:
            value = str(form_data.get(key, "")).strip()
            if value:
                return value
    for key in keys:
        value = request.query_params.get(key, "").strip()
        if value:
            return value
    return fallback


async def _validate_twilio_signature(request: Request) -> None:
    if not settings.require_twilio_signature:
        return
    if not settings.twilio_auth_token:
        raise HTTPException(
            status_code=500,
            detail="REQUIRE_TWILIO_SIGNATURE is enabled but TWILIO_AUTH_TOKEN is missing.",
        )

    signature = request.headers.get("X-Twilio-Signature", "")
    form_data = await request.form()
    validator = RequestValidator(settings.twilio_auth_token)
    is_valid = validator.validate(str(request.url), dict(form_data), signature)
    if not is_valid:
        logger.warning("Twilio signature validation failed for /voice/incoming")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")


def _validate_elevenlabs_secret(request: Request) -> None:
    if not settings.require_elevenlabs_handoff_secret:
        return
    incoming = request.headers.get("X-ElevenLabs-Handoff-Secret", "")
    if not settings.elevenlabs_handoff_secret:
        raise HTTPException(
            status_code=500,
            detail="REQUIRE_ELEVENLABS_HANDOFF_SECRET is enabled but ELEVENLABS_HANDOFF_SECRET is missing.",
        )
    if incoming != settings.elevenlabs_handoff_secret:
        raise HTTPException(status_code=403, detail="Invalid ElevenLabs handoff secret.")


@app.get("/health")
async def health() -> dict[str, str | int]:
    latency_summary = latency_tracker.summary()
    return {
        "status": "ok",
        "service": "live-translation-poc",
        "translation_provider": settings.translation_provider,
        "active_bridge_sessions": registry.active_session_count(),
        "handoff_dry_run": int(settings.handoff_dry_run),
        "latency_samples": int(latency_summary["count"]),
    }


@app.post("/voice/incoming")
async def voice_incoming(request: Request) -> Response:
    await _validate_twilio_signature(request)
    form_data = await request.form()
    caller_language = _pick_runtime_language(
        request,
        form_data,
        keys=("caller_language", "caller_lang", "source_language", "language"),
        fallback=settings.default_caller_language,
    )
    explicit_agent_language = _pick_runtime_language(
        request,
        form_data,
        keys=("agent_language", "agent_lang", "target_language"),
        fallback="",
    )
    _ = explicit_agent_language  # accepted for compatibility, ignored by policy
    agent_language = settings.default_agent_language
    call_sid = str(form_data.get("CallSid", "")).strip() or None
    session_id = call_sid or uuid4().hex

    query = urlencode(
        {
            "session_id": session_id,
            "leg": "caller",
            "caller_lang": caller_language,
            "agent_lang": agent_language,
        }
    )
    relay_url = f"{get_runtime_websocket_url(settings)}?{query}"

    twiml = VoiceResponse()
    connect = Connect()
    connect.append(
        _build_relay_for_leg(
            url=relay_url,
            language=caller_language,
            transcription_language=caller_language,
            tts_language=caller_language,
        )
    )
    twiml.append(connect)

    logger.info(
        "Issued ConversationRelay TwiML session_id=%s call_sid=%s caller_lang=%s agent_lang=%s ws=%s",
        session_id,
        call_sid,
        caller_language,
        agent_language,
        settings.conversation_relay_ws_path,
    )
    return Response(content=str(twiml), media_type="application/xml")


@app.websocket("/ws/conversationrelay")
async def conversationrelay_ws(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session_id", uuid4().hex)
    leg = websocket.query_params.get("leg", "caller").strip().lower()
    caller_lang = websocket.query_params.get("caller_lang", settings.default_caller_language)
    agent_lang = websocket.query_params.get("agent_lang", settings.default_agent_language)
    await websocket.accept()

    participant = registry.register(session_id=session_id, leg=leg, call_sid=None, websocket=websocket)
    logger.info(
        "ConversationRelay websocket accepted session_id=%s leg=%s participants=%s caller_lang=%s agent_lang=%s",
        session_id,
        participant.leg,
        registry.participant_count(session_id),
        caller_lang,
        agent_lang,
    )
    queued_for_this_leg = registry.dequeue_pending(session_id, participant.leg)
    for queued_message in queued_for_this_leg:
        await websocket.send_json(queued_message)
    if queued_for_this_leg:
        logger.info(
            "Flushed queued translated tokens session_id=%s leg=%s queued_messages=%s",
            session_id,
            participant.leg,
            len(queued_for_this_leg),
        )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Ignoring non-JSON websocket frame")
                continue

            if not isinstance(payload, dict):
                logger.warning("Ignoring websocket frame with non-object JSON")
                continue

            event = parse_conversationrelay_event(payload)
            text_info = safe_text_fingerprint(event.text)
            logger.info(
                "WS event session_id=%s leg=%s type=%s call_sid=%s text_len=%s text_sha=%s",
                session_id,
                participant.leg,
                event.event_type,
                event.call_sid,
                text_info["length"],
                text_info["sha256_12"],
            )

            normalized = event.event_type.lower()
            if normalized == "ping":
                await websocket.send_json({"type": "pong"})
            if not _should_translate_event(event.event_type):
                continue

            if not event.text:
                logger.debug("No translatable text found in event type=%s", event.event_type)
                continue

            turn_start = time.perf_counter()
            source = event.source_language
            target = event.target_language
            if not source or not target:
                if participant.leg == "caller":
                    source = source or caller_lang
                    target = target or agent_lang
                elif participant.leg == "agent":
                    source = source or agent_lang
                    target = target or caller_lang
                else:
                    source = source or caller_lang
                    target = target or agent_lang
            translate_start = time.perf_counter()
            translated = await translator.translate(
                event.text,
                source,
                target,
                call_sid=event.call_sid,
            )
            translate_done = time.perf_counter()

            token_messages = build_token_messages(translated)
            token_emit_start = time.perf_counter()
            counterpart = registry.get_counterpart(participant)
            if counterpart is None:
                target_leg = "agent" if participant.leg == "caller" else "caller"
                for message in token_messages:
                    registry.enqueue_pending(session_id, target_leg, message)
                logger.info(
                    "Queued translated tokens waiting_for_counterpart session_id=%s from_leg=%s target_leg=%s token_count=%s",
                    session_id,
                    participant.leg,
                    target_leg,
                    len(token_messages),
                )
            else:
                for message in token_messages:
                    await counterpart.websocket.send_json(message)
            token_emit_done = time.perf_counter()

            ingest_to_translate_start_ms = max((translate_start - turn_start) * 1000.0, 0.0)
            translate_ms = max((translate_done - translate_start) * 1000.0, 0.0)
            token_emit_ms = max((token_emit_done - token_emit_start) * 1000.0, 0.0)
            total_estimated_turn_ms = (
                ingest_to_translate_start_ms
                + translate_ms
                + token_emit_ms
                + settings.estimated_tts_ms_per_turn
            )
            metric = TurnLatencyMetric(
                session_id=session_id,
                leg=participant.leg,
                event_type=event.event_type,
                source_language=source,
                target_language=target,
                input_text_length=len(event.text),
                output_text_length=len(translated),
                token_count=len(token_messages),
                ingest_to_translate_start_ms=round(ingest_to_translate_start_ms, 2),
                translate_ms=round(translate_ms, 2),
                token_emit_ms=round(token_emit_ms, 2),
                estimated_tts_ms=round(settings.estimated_tts_ms_per_turn, 2),
                total_estimated_turn_ms=round(total_estimated_turn_ms, 2),
            )
            latency_tracker.add(metric)
            logger.info(
                "Latency session_id=%s leg=%s total_estimated_turn_ms=%.2f translate_ms=%.2f token_emit_ms=%.2f",
                session_id,
                participant.leg,
                total_estimated_turn_ms,
                translate_ms,
                token_emit_ms,
            )
    except WebSocketDisconnect:
        logger.info(
            "ConversationRelay websocket disconnected session_id=%s leg=%s",
            session_id,
            participant.leg,
        )
    except Exception:
        logger.exception("Unhandled websocket error")
        await websocket.close(code=1011)
    finally:
        registry.unregister(participant)


@app.post("/handoff/elevenlabs", response_model=ElevenLabsHandoffResponse)
async def elevenlabs_handoff(
    request: Request,
    payload: ElevenLabsHandoffRequest,
) -> ElevenLabsHandoffResponse:
    _validate_elevenlabs_secret(request)
    if not payload.handoff_required:
        raise HTTPException(status_code=400, detail="handoff_required must be true for this endpoint.")

    caller_language = payload.caller_language or settings.default_caller_language
    agent_language = payload.agent_language or settings.default_agent_language
    reason_fp = safe_reason_fingerprint(payload.reason, payload.context_summary)
    sid_preview = (payload.twilio_call_sid or "").strip()
    sid_preview = f"{sid_preview[:10]}..." if sid_preview else "none"
    logger.info(
        "ElevenLabs handoff requested session_id=%s call_sid=%s caller_lang=%s agent_lang=%s reason_fp=%s has_customer_number=%s has_agent_number=%s",
        payload.session_id,
        sid_preview,
        caller_language,
        agent_language,
        reason_fp,
        bool((payload.customer_number or "").strip()),
        bool((payload.agent_number or payload.human_agent_number or "").strip()),
    )

    try:
        result = await run_in_threadpool(handoff_orchestrator.execute, payload)
    except HandoffConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HandoffExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ElevenLabsHandoffResponse(
        status="handoff_started",
        mode="dry_run" if settings.handoff_dry_run else "live",
        conference_name=result.conference_name,
        session_id=result.session_id,
        twilio_call_sid=result.twilio_call_sid,
        agent_call_sid=result.agent_call_sid,
        customer_call_sid=result.customer_call_sid,
        caller_language=caller_language,
        agent_language=agent_language,
    )


@app.get("/metrics/latency")
async def latency_summary() -> dict[str, object]:
    return latency_tracker.summary()


@app.get("/metrics/latency/recent")
async def latency_recent(limit: int = 20) -> dict[str, object]:
    return {"items": latency_tracker.recent(limit=limit)}


@app.post("/metrics/latency/reset")
async def latency_reset() -> dict[str, str]:
    latency_tracker.reset()
    return {"status": "ok"}


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    return "Live Translation PoC running. See /health."
