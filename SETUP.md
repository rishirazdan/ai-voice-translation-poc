# Setup Guide (Local PoC)

## Prerequisites

- Python 3.11+
- PowerShell (Windows)
- A Twilio phone number and Console access
- A public tunnel URL (for example ngrok)

## 1) Create environment and install dependencies

```powershell
cd "C:\Users\RR\Test Live Translation"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) Configure environment variables

```powershell
Copy-Item .env.example .env
```

Edit `.env` values:

- `PUBLIC_BASE_URL`: your live tunnel URL (for example `https://xxxxx.ngrok-free.app`)
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_HANDOFF_FROM_NUMBER=+1...`
- `DEFAULT_HUMAN_AGENT_NUMBER=+1...`
- `DEFAULT_CALLER_LANGUAGE=auto`
- `DEFAULT_AGENT_LANGUAGE=en-US`
- `TRANSCRIPTION_PROVIDER=Deepgram` (required when `DEFAULT_CALLER_LANGUAGE=auto`)
- `TTS_PROVIDER=ElevenLabs` (required when `DEFAULT_CALLER_LANGUAGE=auto`)
- `TRANSLATION_PROVIDER=mock` (or `openai`)
- `HANDOFF_DRY_RUN=true` for local MVP checks
- `ELEVENLABS_HANDOFF_SECRET=...`
- `REQUIRE_ACTIVE_CALL_SID_FOR_HANDOFF=false` (default callback fallback enabled)
- `ENABLE_CUSTOMER_RECONNECT=true` (recommended for managed-service reliability)
- if using OpenAI:
  - `OPENAI_API_KEY=...`
  - `OPENAI_TRANSLATION_MODEL=gpt-4.1-mini`

Optional security:

- Set `REQUIRE_TWILIO_SIGNATURE=true` after webhook routing is stable.

## 3) Run the app locally

```powershell
.\scripts\run_dev.ps1 -Host 127.0.0.1 -Port 8010
```

Server base URL:

- `http://127.0.0.1:8010`

Health endpoint:

- `GET /health`

## 4) Expose local app publicly

Example with ngrok:

```powershell
ngrok http 8010
```

Copy the HTTPS forwarding URL and set it as `PUBLIC_BASE_URL` in `.env`.

## 5) Configure Twilio webhook

Set your Twilio number Voice webhook to:

- `POST https://<your-public-url>/voice/incoming`

Do not point this number to Studio for this PoC path.

## 6) Basic local checks

From another terminal:

```powershell
curl http://127.0.0.1:8010/health
```

Expected output includes:

- `status: ok`
- selected `translation_provider`

## 6b) Handoff endpoint local check

```powershell
$body = @{
  handoff_required = $true
  twilio_call_sid = "CA1234567890abcdef1234567890abcd"
  customer_number = "+14155550123"
  caller_language = "sv-SE"
  agent_language = "en-US"
  reason = "human_requested"
} | ConvertTo-Json

Invoke-WebRequest `
  -UseBasicParsing `
  -Method POST `
  -Uri http://127.0.0.1:8010/handoff/elevenlabs `
  -Headers @{ "X-ElevenLabs-Handoff-Secret" = "replace-with-strong-shared-secret" } `
  -ContentType "application/json" `
  -Body $body
```

Expected for local dry-run:

- `status` is `handoff_started`
- `mode` is `dry_run`
- response contains `conference_name`, `session_id`, and call SID values

For live seamless handoff, ElevenLabs must pass a real runtime call SID:

- `twilio_call_sid = {{system__call_sid}}`

## 6c) Latency instrumentation check

Generate a few websocket translation turns, then query metrics:

```powershell
@'
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
with client.websocket_connect('/ws/conversationrelay?session_id=L1&leg=caller&caller_lang=sv-SE&agent_lang=en-US') as ws:
    ws.send_json({'event': 'transcript', 'text': 'hej varlden'})
    _ = ws.receive_json()

print(client.get('/metrics/latency').json())
print(client.get('/metrics/latency/recent?limit=3').json())
'@ | python -
```

You should see `count >= 1` and values for:

- `avg_total_estimated_turn_ms`
- `p95_total_estimated_turn_ms`
- `avg_translate_ms`

## 7) Notes for phase 1

- This scaffold returns TwiML for ConversationRelay and accepts websocket frames.
- Event handling is resilient for unknown frame types.
- Full dual-leg caller <-> agent orchestration is intentionally deferred to later milestones.

## 8) Local websocket translation simulation

Run this quick in-process simulation:

```powershell
@'
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

with client.websocket_connect('/ws/conversationrelay?session_id=S1&leg=caller&caller_lang=sv-SE&agent_lang=en-US') as caller_ws, \
     client.websocket_connect('/ws/conversationrelay?session_id=S1&leg=agent&caller_lang=sv-SE&agent_lang=en-US') as agent_ws:
    caller_ws.send_json({'event': 'transcript', 'text': 'hej'})
    agent_ws.send_json({'event': 'transcript', 'text': 'hello'})
    print('caller token:', caller_ws.receive_json())
    print('agent token:', agent_ws.receive_json())
'@ | python -
```

Expected with `TRANSLATION_PROVIDER=mock`:

- caller leg token begins with `[sv-SE->en-US]`
- agent leg token begins with `[en-US->sv-SE]`
