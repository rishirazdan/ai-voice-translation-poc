# Security Policy

## Reporting a vulnerability

If you discover a security issue, do not open a public issue with sensitive details.

Share:

1. Impact summary
2. Reproduction steps
3. Affected file/endpoint
4. Suggested mitigation

## Sensitive data handling

This PoC is designed to avoid raw PII persistence in logs. Contributors must:

1. Avoid logging raw utterance text.
2. Avoid committing `.env`, tokens, credentials, or call artifacts.
3. Keep webhook authentication checks enabled in non-local environments.

## Operational security baseline

1. `REQUIRE_ELEVENLABS_HANDOFF_SECRET=true`
2. `REQUIRE_TWILIO_SIGNATURE=true` in production-like environments
3. Use strong shared secrets and rotate them regularly
