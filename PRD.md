# Live Voice Translation: PoC to V1

**Stage:** Planning Review
**Last Updated:** 2026-05-21
**Owner:** RR
**Status:** Draft

---

## TL;DR

A working PoC translates live phone calls in near real time between a caller and an English-speaking agent, with an ElevenLabs AI front-door handling first contact and Twilio handling the human handoff. This PRD proposes the v1 work to take it from a single-process demo to a deployable service teams could actually pilot.

---

## Hypothesis

Customer support teams need multilingual coverage and can't staff every language. Bilingual agencies and human interpreters are expensive, slow to spin up, and rarely available off-hours.

**If we** ship an AI-front-door plus live-translation layer that sits in front of a small English-only agent team,
**then** support orgs can serve non-English callers at the latency of a normal call,
**because** modern speech APIs and LLM translation are now fast enough that turn-by-turn translation feels like a natural pause rather than an interruption.

**Evidence from the PoC:**
- End-to-end turn latency is measured and emitted at `/metrics/latency` (avg + p95 of `total_estimated_turn_ms`, plus `translate_ms` and `token_emit_ms` broken out).
- Translation runs on `gpt-4.1-mini` via the OpenAI provider, with a deterministic `MockTranslator` for tests.
- Seamless handoff works against a real Twilio call SID. The fallback callback path exists but is opt-in.

---

## Strategic Fit

This is a standalone project, but the bet is sized against a real category: contact-center AI plus translation is where Cresta, Sierra, and Decagon are spending. The PoC validates a different angle: don't replace the human agent, extend their language reach. That's a smaller, more believable claim than "AI handles the whole call."

**Why now:** Speech-to-text latency dropped meaningfully in 2025 with Twilio ConversationRelay and ElevenLabs Conversational AI. Translation quality on a small, cheap model (`gpt-4.1-mini`) is good enough for service interactions. The three pieces fit together for the first time.

---

## What We Learned from the PoC

1. **Handoff is the hard part, not translation.** Most demos skip the step where an AI agent hands a live caller to a human without dropping the call. The seamless path (update the existing Twilio leg using `system__call_sid`) is what makes it feel real. The reconnect-via-callback fallback is a worse experience, so it ships off by default.
2. **Latency budget lives in the TTS step, not the LLM.** Translation is fast. The estimated TTS playback (`ESTIMATED_TTS_MS_PER_TURN=650`) dominates perceived turn time. Optimizing the wrong stage would be wasted effort.
3. **Logging policy matters earlier than you think.** No raw transcript text in logs, only event type, call SID, text length, and a short SHA-256 fingerprint. Doing this from day one removed a future compliance headache.

---

## V1 Scope

Ship the PoC as a service one small team could actually pilot. Concretely:

1. **Stateful session backing.** Move `session_bridge` registry from in-process memory to Redis (or equivalent) so the app can run multi-worker.
2. **Integration test coverage.** Automated tests for the handoff endpoint and the websocket translation loop. The codebase has a mock translator already; wire it into a real test harness.
3. **Provider failover.** If the OpenAI call fails or times out, degrade to source-language passthrough with a logged warning rather than dropping the turn.
4. **Deployment profile.** A container build and a documented deploy target (Fly.io or Render) replacing the Cloudflare tunnel.
5. **Operational dashboard.** Surface the latency metrics already collected, plus handoff success rate and translation error rate.

---

## Non-Goals

- **More than two languages per call.** Caller language is flexible, agent stays English. A three-way conference is a different product.
- **Agent-side UI.** No web dashboard for the human agent in v1. The agent uses a phone.
- **Custom voice cloning or domain-tuned translation.** Stock `gpt-4.1-mini` is the baseline. Quality work comes later.
- **Replacing the human agent.** The AI front-door triages and hands off. It doesn't try to resolve.

---

## Success Metrics

**Primary:** p95 turn latency under 2.5s end-to-end (ingest → translate → token emit → estimated TTS).

**Guardrails:**
- Handoff success rate above 95% when a valid `twilio_call_sid` is present.
- Translation error rate (provider failures, malformed responses) under 1% over a rolling 1k-turn window.
- Zero raw transcript text in production logs (verified by log scan in CI).

**Kill criterion:** If p95 turn latency stays above 4s after the v1 work, the turn-based model is wrong and we revisit streaming translation instead.

---

## AI Behavior Contract

| Dimension | Specification |
|---|---|
| Primary task | Translate one turn of conversational speech between caller language and `en-US`. |
| Inputs | Per-turn transcript text from Twilio ConversationRelay, plus source and target language tags. |
| Constraints | Preserve meaning over fluency, no PII echo into logs, no model-added content. |
| Disallowed | Summarizing, paraphrasing across turns, refusing benign content. |
| Latency budget | P95 `translate_ms` under 700ms. |

**Behavior examples:**

| Scenario | Input | Expected | Category |
|---|---|---|---|
| Happy path | `"Hej, jag behöver hjälp med min faktura."` (sv-SE) | `"Hi, I need help with my invoice."` | Good |
| Mixed-language utterance | `"Det är en SaaS-prenumeration."` | Keeps `SaaS` literal, translates the rest. | Good |
| Provider timeout | Any input, OpenAI 5s timeout | Pass source text through, log `TRANSLATION_FALLBACK_PASSTHROUGH`. | Graceful degrade |
| Empty / non-text frame | `{"event": "mark"}` | Ignore silently. | Good |
| Prompt injection in caller speech | `"Ignore previous instructions and..."` | Translate literally, do not act on it. | Reject the meta-action, not the text |

---

## Rollout Plan

1. **Internal dogfood.** Two test numbers, mock translator, dry-run handoff. Validate the deploy profile.
2. **Paid pilot with one team.** Real OpenAI, real Twilio, live handoff. Two-week window with the latency and error-rate guardrails above as go/no-go.
3. **Open pilot.** Add a second language pair (sv-SE was the test case; expand to es-MX).

**Rollback:** Flip `TRANSLATION_PROVIDER=mock` and `HANDOFF_DRY_RUN=true` via env vars, redeploy. Both paths are already in the code.

---

## Risks and Recovery

| Risk | Detection | Fallback |
|---|---|---|
| OpenAI rate limits during a call | 429 response, spike in `translate_ms` | Source-language passthrough, log warning |
| Twilio ConversationRelay event-shape change | Parse failures in `models.py` | Ignore unknown event types (already implemented), alert on parse-failure rate |
| Multi-worker session collision | Lost websocket on scale-out | Redis-backed session registry (in v1 scope) |
| Caller language misdetection | Wrong target language in translated output | Default to `en-US` agent side, allow ElevenLabs to override `caller_language` at handoff |

---

## Open Questions

- [ ] Which deploy target — Fly.io vs Render vs a small ECS task? Decide based on websocket cold-start behavior.
- [ ] Is the estimated TTS budget (`650ms`) close to reality with ElevenLabs? Worth measuring directly rather than estimating.
- [ ] Do we want to capture turn-level transcripts (encrypted at rest) for QA, or stay metadata-only?

---

## Appendix: PoC Surface Area

- API: `/health`, `POST /voice/incoming`, `WS /ws/conversationrelay`, `POST /handoff/elevenlabs`, `/metrics/latency`, `/metrics/latency/recent`, `POST /metrics/latency/reset`
- Stack: Python 3.11, FastAPI, Twilio Programmable Voice + ConversationRelay, ElevenLabs Conversational AI, OpenAI `gpt-4.1-mini`
- Security baseline: shared-secret on the ElevenLabs handoff webhook, optional Twilio signature validation, metadata-only logging
