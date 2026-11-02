"""
English part name -> Chinese parts-catalog terms, for 17VIN's name search (its part names are Chinese only).

One short LLM call per new part name ("crankshaft position sensor" -> 曲轴位置传感器), cached in memory.
Returns nothing with the mock provider or when the LLM fails: the chat then falls back to a photo.
"""

import re

from ..config import get_settings
from .llm import ChatTurn, LLMError, get_llm

PROMPT = (
    "You translate car part names into the standard Simplified Chinese terms used in OEM parts catalogs "
    "(EPC), e.g. 'crankshaft position sensor' -> 曲轴位置传感器, 'brake pad' -> 制动衬块, 盘式制动器衬块. "
    "Reply with 1 to 3 candidate terms, most likely first, separated by commas. Chinese only, nothing else."
)

_cache: dict[str, list[str]] = {}


async def chinese_terms(part: str) -> list[str]:
    key = part.strip().lower()
    if key in _cache:
        return _cache[key]
    if get_settings().llm_provider == "mock":
        return []
    try:
        answer = await get_llm().complete(PROMPT, [ChatTurn(role="user", text=part.strip())])
    except LLMError:
        return []  # not cached: retried next time
    terms = [t.strip() for t in re.split(r"[,，、;；\n]", answer) if t.strip() and not t.strip().isascii()][:3]
    _cache[key] = terms
    return terms
