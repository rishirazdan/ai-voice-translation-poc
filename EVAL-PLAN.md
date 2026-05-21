# Evaluation Plan

**Project:** Live Voice Translation PoC
**Last Updated:** 2026-05-21
**Owner:** RR
**Status:** Draft

---

## Why this exists

The PRD makes concrete promises in two places:

1. **AI Behavior Contract** — what the translator does on happy path, ambiguous input, prompt injection, and provider failure.
2. **Success Metrics** — p95 turn latency under 2.5s, seamless handoff success above 95%, reconnect-fallback usage under 15%, zero raw transcript text in production logs.

A claim without an eval is just hope. This plan turns each PRD promise into a runnable test, so we know when something regresses and so a recruiter looking at the repo can verify the work, not just read about it.

---

## Eval layers

Four layers, each answering one question.

### 1. Translation quality
**Question:** Does the translator preserve meaning across the Behavior Contract scenarios?
**Files:** `tests/test_translation.py`, `tests/data/translation_golden.json`
**Default mode:** Tests the `MockTranslator` (deterministic) — always runs in CI.
**Live mode:** Tests `OpenAITranslator` against a golden set with an LLM-judge rubric (faithfulness, fluency, prompt-injection resistance). Gated by `pytest -m live` and requires `OPENAI_API_KEY`.

### 2. System / handoff behavior
**Question:** Does the handoff path enforce the policy described in the PRD across the seamless / reconnect / strict modes?
**File:** `tests/test_handoff_policy.py`
**Coverage:** Eight scenarios mapped to the PRD's Risks table — strict mode with no SID, lenient mode with valid customer number, invalid SID format, bad E.164 numbers, same caller/agent number, customer number equals `TWILIO_HANDOFF_FROM_NUMBER`, alias mapping (`system__call_sid` → `twilio_call_sid`), and successful seamless transfer.

### 3. Latency benchmarks
**Question:** Does end-to-end turn latency stay under the PRD threshold?
**File:** `tests/test_latency_budget.py`
**Method:** Drive 50 turns through `/ws/conversationrelay` with `MockTranslator`, then query `/metrics/latency` and assert `p95_total_estimated_turn_ms < 2500`. Catches regressions in `translate_ms` or `token_emit_ms`, not real OpenAI latency (the live-mode translation test covers that).

### 4. Logging / privacy policy
**Question:** Does any raw transcript text leak into logs?
**File:** `tests/test_logging_policy.py`
**Method:** Send a known transcript with a recognizable marker token, capture all log records with `caplog`, assert no record body contains the marker. Codifies the metadata-only logging guarantee.

Supporting layer:

### 5. Event parsing and security
**Files:** `tests/test_models.py`, `tests/test_security.py`, `tests/test_websocket_flow.py`
**Coverage:** ConversationRelay event-shape resilience (the PRD risk row), text fingerprinting, token message construction, ElevenLabs shared-secret enforcement, and the happy-path websocket flow.

---

## Run modes

```powershell
# Default — fast, no network, no API keys. This is what CI runs.
pytest

# Include live OpenAI quality evals (requires OPENAI_API_KEY)
$env:OPENAI_API_KEY = "sk-..."
pytest -m "live or not live"

# Latency benchmarks only
pytest -m perf

# Just one layer
pytest tests/test_handoff_policy.py
```

---

## Pass / fail thresholds

| Layer | Metric | Pass threshold | Source |
|---|---|---|---|
| Translation (live) | LLM judge faithfulness | ≥4/5 average over golden set | PRD AI Behavior Contract |
| Translation (live) | Prompt-injection compliance | 0 cases where model follows the injected instruction | PRD AI Behavior Contract |
| Handoff | Scenario coverage | 100% of mapped scenarios pass | PRD Risks table |
| Latency | p95 turn latency | < 2500ms (mock provider) | PRD Success Metrics |
| Logging | Raw transcript in logs | 0 occurrences | PRD Success Metrics |

The mock-provider latency threshold is a regression guard, not a real performance number. The live OpenAI call adds real network latency; that's tracked at runtime via `/metrics/latency` once deployed, not in this test suite.

---

## CI integration

The current `.github/workflows/ci.yml` only does compile-check + smoke import. Once the suite is stable, add the pytest step:

```yaml
      - name: Run tests
        run: pytest tests/ -v
        env:
          # Live OpenAI evals stay opt-in. Default CI never spends tokens.
          OPENAI_API_KEY: ""
```

For nightly live evals, add a separate workflow file (`.github/workflows/eval-live.yml`) on a schedule trigger with the API key from secrets and `pytest -m live`.

---

## How to extend

**Add a translation case:** drop a new entry into `tests/data/translation_golden.json` with `source`, `source_lang`, `target_lang`, `reference`, and (optional) `category` (`happy_path`, `mixed_language`, `injection`, etc.).

**Add a handoff scenario:** new test in `tests/test_handoff_policy.py` using the `orchestrator` fixture. One scenario per test for clean failure output.

**Add an AI Behavior Contract row:** mirror it into `test_translation.py::test_behavior_contract_examples` and the golden JSON in one PR.

**Tighten a threshold:** edit the constants at the top of `test_latency_budget.py` and `test_translation.py`. Don't sprinkle magic numbers.

---

## What this plan deliberately does NOT cover

- **Real Twilio integration tests.** The handoff orchestrator is tested with a mocked `Client`. A real Twilio sandbox test would be valuable but is out of scope for the v1 eval suite — it belongs in a separate manual smoke-test runbook.
- **ElevenLabs Conversational AI behavior.** That's a vendor product; we test our handoff endpoint, not their conversation engine.
- **Cost / token-usage budgets.** Worth tracking once live, not part of correctness evals.
- **Multi-worker session collision.** Will be covered when the Redis-backed registry from the V1 Scope ships.

---

## Appendix: file layout

```
tests/
├── __init__.py
├── conftest.py                    # settings + translator fixtures
├── data/
│   └── translation_golden.json    # 8 cases mapped to Behavior Contract
├── test_translation.py            # mock + live LLM-judge evals
├── test_handoff_policy.py         # seamless / reconnect / strict mode
├── test_websocket_flow.py         # happy path + edge cases
├── test_security.py               # ElevenLabs shared secret
├── test_models.py                 # event parsing, fingerprinting, tokens
├── test_logging_policy.py         # no raw transcript leak
└── test_latency_budget.py         # p95 regression guard
pytest.ini                          # markers (live, perf)
requirements-dev.txt                # pytest + httpx
```
