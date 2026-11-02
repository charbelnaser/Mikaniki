from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Conversation, Message, User
from ..schemas import ChatReply, ConversationDetail, ConversationOut, MessageOut
from ..services.diagnosis import ALLOWED_IMAGE_TYPES, reply_to_user
from ..services.llm import LLMError
from .vehicles import get_owned_vehicle

router = APIRouter(prefix="/api", tags=["chat"])


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id, role=m.role, content=m.content, created_at=m.created_at,
        image_url=f"/uploads/{m.image_path}" if m.image_path else None,
    )


def get_owned_conversation(conversation_id: int, user: User, db: Session) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/vehicles/{vehicle_id}/conversations", response_model=list[ConversationOut])
def list_conversations(vehicle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned_vehicle(vehicle_id, user, db)
    return db.scalars(
        select(Conversation)
        .where(Conversation.vehicle_id == vehicle_id)
        .order_by(Conversation.updated_at.desc())
    ).all()


@router.post("/vehicles/{vehicle_id}/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(vehicle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vehicle = get_owned_vehicle(vehicle_id, user, db)
    conv = Conversation(vehicle_id=vehicle.id, user_id=user.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = get_owned_conversation(conversation_id, user, db)
    return ConversationDetail(
        **ConversationOut.model_validate(conv).model_dump(),
        messages=[message_out(m) for m in conv.messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(get_owned_conversation(conversation_id, user, db))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatReply)
async def send_message(
    conversation_id: int,
    text: str = Form(default="", max_length=4000),
    image: UploadFile | None = File(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_owned_conversation(conversation_id, user, db)

    image_bytes, image_mime = None, None
    if image is not None and image.filename:
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Only JPEG, PNG, WEBP or GIF images are supported")
        image_bytes = await image.read()
        if len(image_bytes) > get_settings().max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Image too large (max {get_settings().max_upload_mb} MB)")
        image_mime = image.content_type

    if not text.strip() and not image_bytes:
        raise HTTPException(status_code=422, detail="Send a message or a photo")

    try:
        user_msg, assistant_msg = await reply_to_user(db, user, conv, text, image_bytes, image_mime)
    except LLMError:
        raise HTTPException(status_code=502, detail="The AI mechanic is unavailable right now, please try again")

    return ChatReply(
        conversation=ConversationOut.model_validate(conv),
        user_message=message_out(user_msg),
        assistant_message=message_out(assistant_msg),
    )
