from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------- Auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    language: str = Field(default="ar", pattern="^(ar|en|fr)$")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None
    language: str


# ---------- Catalog ----------
class MakeOut(BaseModel):
    id: int | None = None
    name: str
    popular: bool = False


class ModelOut(BaseModel):
    id: int | None = None
    name: str


class VinPhotoOut(BaseModel):
    vin: str


class VinDecodeOut(BaseModel):
    vin: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    trim: str | None = None
    engine: str | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    body_class: str | None = None
    plant_country: str | None = None
    raw: dict = {}
    warnings: list[str] = []


# ---------- Vehicles ----------
class VehicleBase(BaseModel):
    make: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    year: int = Field(ge=1950, le=2100)
    trim: str | None = Field(default=None, max_length=120)
    engine: str | None = Field(default=None, max_length=120)
    fuel_type: str | None = Field(default=None, max_length=40)
    transmission: str | None = Field(default=None, max_length=40)
    mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    vin: str | None = Field(default=None, max_length=17)
    nickname: str | None = Field(default=None, max_length=80)

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip().upper()
        if len(v) != 17:
            raise ValueError("VIN must be 17 characters")
        return v


class VehicleCreate(VehicleBase):
    source: str = Field(default="manual", pattern="^(catalog|vin|manual)$")
    vin_data: dict | None = None
    epa_id: int | None = None  # exact version picked from /api/catalog/versions; specs are fetched server-side


class VehicleUpdate(BaseModel):
    trim: str | None = None
    engine: str | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    nickname: str | None = None


class VehicleOut(VehicleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    display_name: str
    specs: dict | None = None
    created_at: datetime


class EpaVersionOut(BaseModel):
    id: int
    text: str    # e.g. "Auto (AV-S7), 4 cyl, 1.8 L"
    model: str   # EPA model name, e.g. "Corolla" or "Camry Hybrid LE"


class SafetyRatingOut(BaseModel):
    description: str
    overall: str | None = None
    frontal: str | None = None
    side: str | None = None
    rollover: str | None = None


class RecallOut(BaseModel):
    """One recall from any market. Texts are in English, as published by the agency."""
    market: Literal["US", "CA", "UK"]
    ref: str                          # NHTSA campaign, Transport Canada number or DVSA reference
    date: str | None = None
    component: str | None = None
    summary: str | None = None
    consequence: str | None = None
    remedy: str | None = None
    park_it: bool = False


class ComplaintComponentOut(BaseModel):
    component: str
    count: int
    examples: list[str] = []


class VehicleReportsOut(BaseModel):
    """Safety data for the car card. `available` is False when the safety services could not be reached."""
    available: bool
    recalls_us: int = 0
    recalls_canada: int = 0
    recalls_uk: int = 0
    complaints: int = 0
    safety: SafetyRatingOut | None = None
    recalls: list[RecallOut] = []
    top_components: list[ComplaintComponentOut] = []
    crashes: int = 0
    fires: int = 0
    injuries: int = 0


# ---------- Parts catalog (17VIN EPC, by VIN) ----------
class PartCategoryOut(BaseModel):
    code: str
    name: str
    name_zh: str | None = None
    remark: str | None = None
    level: int
    is_last: bool  # True: open its part list; False: open its sub-categories
    fits: bool     # False: listed by the EPC but not for this exact VIN
    image: str | None = None


class PartOut(BaseModel):
    callout: str | None = None  # number on the diagram
    number: str                 # OE part number
    name: str
    name_zh: str | None = None
    qty: str | None = None
    remark: str | None = None
    replacement: str | None = None
    begin_date: str | None = None
    end_date: str | None = None
    fits: bool


class HotspotOut(BaseModel):
    callout: str
    x: float  # % of the diagram width, top-left of the callout label
    y: float  # % of the diagram height


class PartListOut(BaseModel):
    image: str | None = None
    hotspots: list[HotspotOut] = []
    parts: list[PartOut]


# ---------- Media ----------
class PartPhotoOut(BaseModel):
    """Wikimedia Commons photo. `author` and `license` must be shown next to it."""
    thumb_url: str
    page_url: str
    author: str | None = None
    license: str | None = None


class VideoOut(BaseModel):
    video_id: str
    title: str
    channel: str | None = None


# ---------- Chat ----------
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: str
    image_url: str | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ChatReply(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut


# ---------- OBD-II ----------
class ObdCauseOut(BaseModel):
    cause: str
    likelihood: str  # high | medium | low | unknown


class ObdCodeOut(BaseModel):
    code: str
    system: str
    subsystem: str | None = None
    generic: bool
    definition: str | None = None
    severity: str | None = None
    description: str | None = None
    causes: list[ObdCauseOut] = []
    symptoms: list[str] = []
    difficulty: str | None = None
    diy_possible: bool | None = None
    limp_mode_possible: bool | None = None
    related: list[str] = []
    source: str | None = None   # obdex | mikaniki | None (decoded from the code's structure only)
    credit: str | None = None   # attribution to show when source is obdex
