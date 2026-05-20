import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin

from dotenv import load_dotenv


load_dotenv(override=True)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return default


def _normalize_ws_url(base_url: str, ws_path: str) -> str:
    merged = urljoin(base_url.rstrip("/") + "/", ws_path.lstrip("/"))
    if merged.startswith("https://"):
        return "wss://" + merged[len("https://") :]
    if merged.startswith("http://"):
        return "ws://" + merged[len("http://") :]
    return merged


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    public_base_url: str
    twilio_account_sid: str
    twilio_auth_token: str
    require_twilio_signature: bool
    conversation_relay_ws_path: str
    default_caller_language: str
    default_agent_language: str
    translation_provider: str
    openai_api_key: str
    openai_translation_model: str
    require_elevenlabs_handoff_secret: bool
    elevenlabs_handoff_secret: str
    twilio_handoff_from_number: str
    default_human_agent_number: str
    require_active_call_sid_for_handoff: bool
    handoff_dry_run: bool
    enable_customer_reconnect: bool
    customer_reconnect_announcement: str
    latency_sample_size: int
    estimated_tts_ms_per_turn: float
    log_level: str
    tts_provider: str

    @property
    def websocket_url(self) -> str:
        return _normalize_ws_url(self.public_base_url, self.conversation_relay_ws_path)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8010")),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "https://example.ngrok-free.app"),
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            require_twilio_signature=_as_bool(os.getenv("REQUIRE_TWILIO_SIGNATURE"), False),
            conversation_relay_ws_path=os.getenv(
                "CONVERSATION_RELAY_WS_PATH", "/ws/conversationrelay"
            ),
            default_caller_language=os.getenv("DEFAULT_CALLER_LANGUAGE", "auto"),
            default_agent_language=os.getenv("DEFAULT_AGENT_LANGUAGE", "en-US"),
            translation_provider=os.getenv("TRANSLATION_PROVIDER", "mock").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_translation_model=os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini"),
            require_elevenlabs_handoff_secret=_as_bool(
                os.getenv("REQUIRE_ELEVENLABS_HANDOFF_SECRET"), True
            ),
            elevenlabs_handoff_secret=os.getenv("ELEVENLABS_HANDOFF_SECRET", ""),
            twilio_handoff_from_number=os.getenv("TWILIO_HANDOFF_FROM_NUMBER", ""),
            default_human_agent_number=os.getenv("DEFAULT_HUMAN_AGENT_NUMBER", ""),
            require_active_call_sid_for_handoff=_as_bool(
                os.getenv("REQUIRE_ACTIVE_CALL_SID_FOR_HANDOFF"), True
            ),
            handoff_dry_run=_as_bool(os.getenv("HANDOFF_DRY_RUN"), True),
            enable_customer_reconnect=_as_bool(os.getenv("ENABLE_CUSTOMER_RECONNECT"), False),
            customer_reconnect_announcement=os.getenv(
                "CUSTOMER_RECONNECT_ANNOUNCEMENT",
                (
                    "Please stay available. We are reconnecting your call to a human agent now. "
                    "You may receive a callback in a few seconds."
                ),
            ).strip(),
            latency_sample_size=_as_int(os.getenv("LATENCY_SAMPLE_SIZE"), 500),
            estimated_tts_ms_per_turn=_as_float(os.getenv("ESTIMATED_TTS_MS_PER_TURN"), 650.0),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            tts_provider=os.getenv("TTS_PROVIDER", "ElevenLabs").strip(),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def get_runtime_websocket_url(settings: Settings) -> str:
    """Resolve websocket URL from current env so tunnel URL rotations are picked up immediately."""
    base = os.getenv("PUBLIC_BASE_URL", settings.public_base_url)
    return _normalize_ws_url(base, settings.conversation_relay_ws_path)
