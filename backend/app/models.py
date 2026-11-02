from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(120))
    # Future WhatsApp linking: the user's wa_id (phone number)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    language: Mapped[str] = mapped_column(String(5), default="ar")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    year: Mapped[int] = mapped_column(Integer)
    trim: Mapped[str | None] = mapped_column(String(120))
    engine: Mapped[str | None] = mapped_column(String(120))        # e.g. "2.0L I4 turbo"
    fuel_type: Mapped[str | None] = mapped_column(String(40))      # gasoline, diesel, hybrid, electric
    transmission: Mapped[str | None] = mapped_column(String(40))   # automatic, manual, CVT
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    vin: Mapped[str | None] = mapped_column(String(17), index=True)
    nickname: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # catalog | vin | manual
    vin_data: Mapped[dict | None] = mapped_column(JSON)            # raw decoded VIN fields
    specs: Mapped[dict | None] = mapped_column(JSON)               # exact version from FuelEconomy.gov (services/epa.py)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="vehicles")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    obd_readings: Mapped[list["ObdReading"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan", order_by="ObdReading.id"
    )

    @property
    def display_name(self) -> str:
        return " ".join(str(p) for p in (self.year, self.make, self.model, self.trim) if p)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New diagnosis")
    channel: Mapped[str] = mapped_column(String(20), default="web")  # web | whatsapp | mobile
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    vehicle: Mapped[Vehicle] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(255))
    image_mime: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ObdReading(Base):
    """An OBD-II code reported for a car, so later conversations know its code history."""

    __tablename__ = "obd_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    # Kept when the conversation is deleted: the code history belongs to the car
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    code: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    vehicle: Mapped[Vehicle] = relationship(back_populates="obd_readings")
