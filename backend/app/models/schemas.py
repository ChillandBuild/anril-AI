from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID

# --- Enums as Literals ---
SourceType = Literal["whatsapp", "instagram", "facebook", "telegram", "upload", "csv", "manual", "indiamart", "justdial", "website", "api", "store", "meta_form"]
SegmentType = Literal["A", "B", "C", "D"]
DirectionType = Literal["inbound", "outbound"]
PlatformType = Literal["instagram", "facebook", "google"]

# --- Lead Models ---
class LeadBase(BaseModel):
    phone: Optional[str] = None
    name: Optional[str] = None
    source: SourceType
    score: int = 5
    segment: SegmentType = "C"
    notes: Optional[str] = None
    ai_enabled: bool = True
    needs_human_intervention: bool = False
    converted_at: Optional[datetime] = None

    @field_validator("score")
    @classmethod
    def score_must_be_0_to_10(cls, v):
        # 0 is a valid score: it's the "Not Interested" (segment D) floor
        # introduced by migration 164. The DB CHECK is score >= 0 AND <= 10.
        if not 0 <= v <= 10:
            raise ValueError("score must be between 0 and 10")
        return v

class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    score: Optional[int] = None
    segment: Optional[SegmentType] = None
    notes: Optional[str] = None
    needs_human_intervention: Optional[bool] = None

class Lead(LeadBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    pinned_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    broadcast_id: Optional[str] = None
    template_name: Optional[str] = None
    tag_name: Optional[str] = None
    ad_campaign_name: Optional[str] = None
    channel: Optional[str] = None
    model_config = {"from_attributes": True}

# --- Message Models ---
class MessageBase(BaseModel):
    content: str
    direction: DirectionType
    channel: str = "whatsapp"
    is_ai_generated: bool = False

class MessageCreate(MessageBase):
    lead_id: UUID
    conversation_id: Optional[UUID] = None

class Message(MessageBase):
    id: UUID
    lead_id: UUID
    conversation_id: Optional[UUID] = None
    created_at: datetime
    model_config = {"from_attributes": True}

# --- Conversation Models ---
class ConversationBase(BaseModel):
    channel: str = "whatsapp"
    status: Literal["active", "closed"] = "active"

class ConversationCreate(ConversationBase):
    lead_id: UUID

class Conversation(ConversationBase):
    id: UUID
    lead_id: UUID
    opened_at: datetime
    closed_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# --- API Response wrappers ---
class SuccessResponse(BaseModel):
    success: bool = True
    message: str = "ok"

class ErrorResponse(BaseModel):
    error: str
    code: str

class PaginatedResponse(BaseModel):
    data: list
    total: int
    page: int
    limit: int

# --- Lead with messages (for conversation view) ---
class LeadWithMessages(Lead):
    messages: list[Message] = []

# --- Employee Todo Models ---
from datetime import date as date_type

class TodoBase(BaseModel):
    todo_date: date_type
    content: str
    is_completed: bool = False

class TodoCreate(TodoBase):
    pass

class Todo(TodoBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
