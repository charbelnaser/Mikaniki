"""
Channel-agnostic diagnosis service.

The web chat uses it today; the WhatsApp webhook and the mobile app will call the
same `reply_to_user()` later, so the "brain" is written once.
"""

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Conversation, Message, ObdReading, User, utcnow
from . import obd, vehicle_reports
from .llm import ChatTurn, LLMError, get_llm
from .prompts import build_system_prompt

HISTORY_LIMIT = 20          # messages sent to the model
IMAGES_IN_CONTEXT = 2       # only re-send the most recent photos (cost control)
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def save_image(data: bytes, mime: str) -> str:
    settings = get_settings()
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[mime]}"
    (folder / name).write_bytes(data)
    return name


def load_image(name: str) -> bytes | None:
    path = Path(get_settings().upload_dir) / name
    return path.read_bytes() if path.is_file() else None


def _history(conversation: Conversation) -> list[ChatTurn]:
    msgs = conversation.messages[-HISTORY_LIMIT:]
    # Anthropic requires the first message to come from the user
    while msgs and msgs[0].role != "user":
        msgs = msgs[1:]

    image_budget = IMAGES_IN_CONTEXT
    turns: list[ChatTurn] = []
    for m in reversed(msgs):
        image = None
        if m.image_path and image_budget > 0:
            image = load_image(m.image_path)
            image_budget -= 1 if image else 0
        text = m.content or ("(photo)" if m.image_path else "")
        turns.append(ChatTurn(role=m.role, text=text, image=image, image_mime=m.image_mime))
    return list(reversed(turns))


def _record_codes(conversation: Conversation, text: str) -> tuple[list[str], list[tuple[str, datetime]]]:
    """Save new OBD codes from the message; return (codes in this conversation, earlier codes on the car)."""
    vehicle = conversation.vehicle
    in_conv = {r.code for r in vehicle.obd_readings if r.conversation_id == conversation.id}
    for code in obd.extract_codes(text):
        if code not in in_conv:
            vehicle.obd_readings.append(ObdReading(conversation_id=conversation.id, code=code))
            in_conv.add(code)

    current = [r.code for r in vehicle.obd_readings if r.conversation_id == conversation.id]
    history: dict[str, datetime] = {}
    for r in vehicle.obd_readings:  # oldest first, so we keep the first time each code was seen
        if r.code not in in_conv and r.code not in history:
            history[r.code] = r.created_at
    return current, list(history.items())


def _title_from(text: str) -> str:
    text = " ".join(text.split())
    return (text[:60] + "…") if len(text) > 60 else (text or "Photo diagnosis")


async def reply_to_user(
    db: Session,
    user: User,
    conversation: Conversation,
    text: str,
    image: bytes | None = None,
    image_mime: str | None = None,
) -> tuple[Message, Message]:
    image_path = save_image(image, image_mime) if image and image_mime else None

    is_first = len(conversation.messages) == 0
    user_msg = Message(
        role="user", content=text.strip(),
        image_path=image_path, image_mime=image_mime if image_path else None,
    )
    conversation.messages.append(user_msg)
    if is_first:
        conversation.title = _title_from(text)
    codes_current, codes_history = _record_codes(conversation, text)
    db.commit()

    v = conversation.vehicle
    reports = await vehicle_reports.get_vehicle_reports(v.make, v.model, v.year)
    system = build_system_prompt(v, user.language, reports, codes_current, codes_history)
    try:
        answer = await get_llm().complete(system, _history(conversation))
    except LLMError:
        # Don't keep a dangling question: the client restores it and lets the user retry
        conversation.messages.remove(user_msg)
        db.delete(user_msg)
        db.commit()
        raise

    assistant_msg = Message(role="assistant", content=answer)
    conversation.messages.append(assistant_msg)
    conversation.updated_at = utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    db.refresh(conversation)
    return user_msg, assistant_msg
