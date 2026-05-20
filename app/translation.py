from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import Settings


class Translator(Protocol):
    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        call_sid: str | None = None,
    ) -> str: ...


@dataclass
class MockTranslator:
    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        call_sid: str | None = None,
    ) -> str:
        if not text.strip():
            return ""
        return f"[{source_language}->{target_language}] {text}"


@dataclass
class OpenAITranslator:
    api_key: str
    model: str

    def __post_init__(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self.api_key)

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        call_sid: str | None = None,
    ) -> str:
        if not text.strip():
            return ""

        normalized_source = (source_language or "").strip()
        normalized_target = (target_language or "").strip()
        source_hint = normalized_source if normalized_source else "auto"
        if source_hint.lower() in {"auto", "und", "unknown"}:
            source_instruction = "Auto-detect from text"
        else:
            source_instruction = source_hint
        target_instruction = normalized_target or normalized_source or "auto"

        response = await self._client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Translate spoken-call text for near-real-time relay. "
                                "If source language is auto-detect, infer it from text. "
                                "Output only the translated text, no commentary."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"Source language: {source_instruction}\n"
                                f"Target language: {target_instruction}\n"
                                f"Text: {text}"
                            ),
                        }
                    ],
                },
            ],
            temperature=0,
        )
        return (response.output_text or "").strip()


def create_translator(settings: Settings) -> Translator:
    provider = settings.translation_provider
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "TRANSLATION_PROVIDER=openai requires OPENAI_API_KEY in the environment."
            )
        return OpenAITranslator(
            api_key=settings.openai_api_key,
            model=settings.openai_translation_model,
        )
    return MockTranslator()
