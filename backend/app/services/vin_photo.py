"""
Read a VIN from a photo: the Lebanese registration card ("أوصاف المركبة الآلية" / dafter, field
"رقم الهيكل"), the windshield plate or the door-frame sticker. Uses the configured vision LLM.
"""

import re

from .llm import ChatTurn, get_llm

VIN_PROMPT = (
    "You are a VIN reader. The image is a vehicle document or plate, often the Lebanese registration "
    "card \"أوصاف المركبة الآلية\" (photo may be rotated or reflective). The VIN is the 17-character "
    "chassis number, labelled \"رقم الهيكل\" on that card, \"VIN\" or \"Chassis No.\" elsewhere. Do NOT "
    "return the engine number (\"رقم المحرك\", e.g. 2ZR2020180) or the plate number.\n"
    "Reply with the VIN only, no spaces, nothing else. If no VIN is readable, reply NONE."
)

VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")
# VINs never contain I, O or Q: these are always misreads of 1 and 0
_FIX = str.maketrans({"I": "1", "O": "0", "Q": "0"})

_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
_VALUES = {**{str(d): d for d in range(10)},
           **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
           **dict(zip("STUVWXYZ", range(2, 10)))}


def check_digit_ok(vin: str) -> bool:
    """North-American VINs carry a check digit in position 9 (European ones usually do not)."""
    total = sum(_VALUES[c] * w for c, w in zip(vin, _WEIGHTS))
    return vin[8] == ("X" if total % 11 == 10 else str(total % 11))


def parse_vin(text: str) -> str | None:
    """Best VIN candidate in an LLM answer, preferring one with a valid check digit."""
    cleaned = re.sub(r"[\s\-.]", "", text.upper()).translate(_FIX)
    candidates = VIN_RE.findall(cleaned)
    if not candidates:
        return None
    return next((v for v in candidates if check_digit_ok(v)), candidates[0])


async def read_vin(image: bytes, mime: str) -> str | None:
    """VIN read from the photo, or None. Raises LLMError when the provider fails."""
    answer = await get_llm().complete(VIN_PROMPT, [ChatTurn(role="user", text="Read the VIN.", image=image, image_mime=mime)])
    return parse_vin(answer)
