# Live Translation PoC (ConversationRelay)

This repository is a **PoC** for near-real-time human-to-human call translation using ElevenLabs + Twilio ConversationRelay.

## Current behavior

1. Caller can speak any language (`caller_language=auto` supported).
2. Human agent side is fixed to English (`DEFAULT_AGENT_LANGUAGE=en-US`).
3. Twilio ConversationRelay streams utterances to websocket.
4. Backend translates text and returns translated tokens for playback.
5. ElevenLabs can trigger handoff through `POST /handoff/elevenlabs`.

## Handoff modes

1. **Primary (default): seamless transfer**
   - Requires valid `twilio_call_sid` from ElevenLabs runtime (`system__call_sid`).
   - No customer callback leg is created.
2. **Backup (opt-in): customer reconnect callback**
   - Controlled by `ENABLE_CUSTOMER_RECONNECT=true`.
   - Intended for emergency fallback only.
   - Emits explicit warning logs when used.

## Endpoints

- `GET /health`
- `POST /voice/incoming`
- `WS /ws/conversationrelay`
- `POST /handoff/elevenlabs`
- `GET /metrics/latency`
- `GET /metrics/latency/recent`
- `POST /metrics/latency/reset`

## Security baseline

1. No raw transcript text is persisted in logs.
2. ElevenLabs webhook shared-secret validation:
   - `REQUIRE_ELEVENLABS_HANDOFF_SECRET=true`
   - header: `X-ElevenLabs-Handoff-Secret`
3. Twilio signature validation is supported for inbound voice webhooks:
   - `REQUIRE_TWILIO_SIGNATURE=true`

## Quick start

See [SETUP.md](./SETUP.md).
