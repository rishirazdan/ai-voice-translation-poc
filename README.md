# Live Voice Translation PoC (ElevenLabs + Twilio + OpenAI)

Near-real-time bilingual call support PoC with AI-first intake and human handoff.

## Resume Summary

Built a live call translation MVP that:

1. starts on an ElevenLabs conversational AI phone agent,
2. hands off to a human Twilio agent,
3. translates both sides of the call in near real time,
4. keeps agent workflow fixed in English while caller language stays flexible.

## Problem and Goal

Customer support teams need multilingual coverage without staffing every language.

This project demonstrates:

1. AI front-door triage,
2. seamless escalation to a human,
3. bilingual turn-by-turn translation during the live call.

## Architecture

See full design in [ARCHITECTURE.md](./ARCHITECTURE.md).

High-level flow:

1. Customer calls ElevenLabs number.
2. ElevenLabs triggers handoff webhook when human agent is needed.
3. FastAPI orchestrator updates/creates Twilio call legs.
4. Twilio ConversationRelay streams transcript events to websocket.
5. Backend translates text and sends translated tokens back for TTS playback.

## Key Features

1. **Seamless handoff (preferred path)**
   - Uses active `twilio_call_sid` from ElevenLabs (`system__call_sid`) when present.
2. **Automatic reconnect fallback (default path when SID is missing)**
   - Enabled by default with `ENABLE_CUSTOMER_RECONNECT=true`.
   - Also used when ElevenLabs sends a placeholder/non-existent `twilio_call_sid`.
   - Can be disabled by setting `REQUIRE_ACTIVE_CALL_SID_FOR_HANDOFF=true`.
   - Emits explicit fallback warning logs.
3. **Agent-side language policy**
   - Agent remains English (`DEFAULT_AGENT_LANGUAGE=en-US`).
   - `caller_language=auto` enables Twilio `multi` STT/TTS mode for dynamic caller-language detection.
   - Caller detected language is used to route agent-to-caller translation target during the session.
4. **Provider abstraction**
   - `mock` translator for deterministic testing.
   - `openai` translator for live translation.
5. **Security and privacy baseline**
   - Shared-secret validation for ElevenLabs webhook.
   - Optional Twilio signature validation.
   - Metadata-only logging (no raw transcript logging).

## Tech Stack

1. Python, FastAPI, Uvicorn
2. Twilio Programmable Voice + ConversationRelay
3. ElevenLabs Conversational AI
4. OpenAI API (`gpt-4.1-mini` for translation)
5. PowerShell automation scripts
6. Cloudflare Tunnel for local webhook exposure

## API Endpoints

1. `GET /health`
2. `POST /voice/incoming`
3. `WS /ws/conversationrelay`
4. `POST /handoff/elevenlabs`
5. `GET /metrics/latency`
6. `GET /metrics/latency/recent`
7. `POST /metrics/latency/reset`

## Local Setup

Use [SETUP.md](./SETUP.md) for end-to-end setup and test steps.

## Suggested Demo Assets

For portfolio/recruiter review, add:

1. 2-3 minute demo video link,
2. screenshot of ElevenLabs handoff tool config,
3. screenshot of live terminal logs showing websocket translation events,
4. short outcomes section (latency range, handoff success behavior, known limits).

## Current Limitations

1. PoC-level runtime resilience (single-process, in-memory session state).
2. Tunnel-based local exposure for demos (not production hosting).
3. No persistent conversation storage/analytics pipeline.
4. `auto` language detection depends on Twilio `multi` mode compatibility:
   - `TRANSCRIPTION_PROVIDER=Deepgram`
   - `TTS_PROVIDER=ElevenLabs`

## Next Milestones

1. Add automated integration tests for handoff + websocket flows.
2. Add robust failover/retry behavior for transient provider failures.
3. Move session state to shared storage for multi-worker deployment.
4. Add production deployment profile and observability dashboards.
