# Contributing

Thanks for contributing to this PoC.

## Development setup

1. Create venv and install dependencies.
2. Copy `.env.example` to `.env` and fill local values.
3. Run app with:
   - `python -m uvicorn app.main:app --host 127.0.0.1 --port 8010`

## Pull request guidelines

1. Keep changes scoped and small.
2. Do not commit secrets (`.env`, tokens, call recordings, or raw PII).
3. Keep logs and generated artifacts out of commits.
4. Update `README.md`, `SETUP.md`, and `ARCHITECTURE.md` when behavior changes.
5. Ensure basic checks pass locally:
   - `python -m compileall app`
   - `python -m pytest` (when tests exist)

## Coding expectations

1. Preserve existing security posture:
   - validate webhook shared secrets
   - avoid raw transcript logging
2. Keep agent-side language behavior explicit:
   - agent is English (`DEFAULT_AGENT_LANGUAGE`)
3. For handoff behavior:
   - seamless mode requires active `twilio_call_sid`
   - callback fallback is enabled by default unless strict SID mode is enforced
