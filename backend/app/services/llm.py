"""
Provider-agnostic LLM layer.

Every channel (web, WhatsApp, mobile) calls `get_llm().complete(system, turns)`.
Switch provider with LLM_PROVIDER=claude|openai|mock in .env.
"""

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import get_settings


@dataclass
class ChatTurn:
    role: str                     # "user" | "assistant"
    text: str
    image: bytes | None = None
    image_mime: str | None = None


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, turns: list[ChatTurn]) -> str: ...


# --------------------------------------------------------------------------- Claude
class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def complete(self, system: str, turns: list[ChatTurn]) -> str:
        messages = []
        for t in turns:
            content: list[dict] = []
            if t.image and t.role == "user":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": t.image_mime or "image/jpeg",
                        "data": base64.b64encode(t.image).decode(),
                    },
                })
            content.append({"type": "text", "text": t.text or "(photo)"})
            messages.append({"role": t.role, "content": content})
        try:
            resp = await self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system, messages=messages
            )
        except Exception as e:  # anthropic.APIError and network errors
            raise LLMError(str(e)) from e
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()


# --------------------------------------------------------------------------- OpenAI
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def complete(self, system: str, turns: list[ChatTurn]) -> str:
        messages: list[dict] = [{"role": "system", "content": system}]
        for t in turns:
            if t.image and t.role == "user":
                data_url = f"data:{t.image_mime or 'image/jpeg'};base64,{base64.b64encode(t.image).decode()}"
                content = [
                    {"type": "text", "text": t.text or "(photo)"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": t.role, "content": t.text})
        try:
            resp = await self.client.chat.completions.create(
                model=self.model, messages=messages, max_completion_tokens=self.max_tokens
            )
        except Exception as e:
            raise LLMError(str(e)) from e
        return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- Mock
class MockProvider(LLMProvider):
    """Canned answers so the UI can be built without an API key."""

    async def complete(self, system: str, turns: list[ChatTurn]) -> str:
        if system.startswith("You are a VIN reader"):  # services/vin_photo.py
            return "1HGCM82633A004352"
        car = next((line.split(": ", 1)[1] for line in system.splitlines() if line.startswith("- Model: ")), "your car")
        last = turns[-1].text if turns else ""
        photo = " I can see the photo you sent." if turns and turns[-1].image else ""
        if any(w in last.lower() for w in ("parts", "pièces", "pieces", "قطع")):
            return (
                f"(demo mode) Here is the original parts catalog of your {car}: open a section to see the "
                "diagram and the OE part numbers that fit your VIN.\n"
                '<!-- mikaniki-media {"parts": [], "video": null, "catalog": true} -->'
            )
        if len(turns) <= 1:
            return (
                f"(demo mode) Thanks!{photo} To diagnose your {car} I need a bit more detail:\n"
                "1. When does it happen — cold start, while driving, when braking?\n"
                "2. Is any warning light on? If you have an OBD code (e.g. P0300), send it.\n"
                "3. Current mileage?"
            )
        return (
            f"(demo mode) Based on \"{last[:80]}\" for your {car}:\n\n"
            "**Likely causes**\n1. Worn spark plugs (60%)\n2. Faulty ignition coil (30%)\n3. Vacuum leak (10%)\n\n"
            "**Severity:** medium\n**Safe to drive?** With caution, short distances only\n"
            "**DIY difficulty:** easy\n**Estimated cost in Lebanon:** $25–60 parts + $15–30 labor\n\n"
            "**What to do next**\n1. Read the OBD codes\n2. Inspect plugs and coils\n3. Replace worn plugs\n\n"
            "Set LLM_PROVIDER=claude or openai in .env for real answers.\n"
            f'<!-- mikaniki-media {{"parts": ["spark plug", "ignition coil"], "video": "{car} spark plug replacement"}} -->'
        )


def get_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "claude":
        if not s.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        return ClaudeProvider(s.anthropic_api_key, s.anthropic_model, s.llm_max_tokens)
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        return OpenAIProvider(s.openai_api_key, s.openai_model, s.llm_max_tokens)
    return MockProvider()
