from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any

class PrescriptionExtraction(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Core meta fields
    transcription: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    urgency: Optional[str] = "normal"
    estimated_value: Optional[float] = None
    confidence: float = 0.0
    explanation: str = ""
    raw_input_type: str = "text"  # text, voice, photo
    
    # Optical fields (for optical blueprint)
    od_sph: Optional[str] = None
    od_cyl: Optional[str] = None
    od_axis: Optional[str] = None
    od_add: Optional[str] = None
    os_sph: Optional[str] = None
    os_cyl: Optional[str] = None
    os_axis: Optional[str] = None
    os_add: Optional[str] = None
    pd: Optional[str] = None
    lens_type: Optional[str] = None
    frame_info: Optional[str] = None

    # Dental fields
    tooth_numbers: Optional[str] = None
    restoration_type: Optional[str] = None
    material: Optional[str] = None
    shade: Optional[str] = None
    occlusal_clearance: Optional[str] = None

    # Auto repair fields
    vehicle_info: Optional[str] = None
    registration_number: Optional[str] = None
    service_category: Optional[str] = None
    parts_required: Optional[str] = None
    reported_issue: Optional[str] = None

    # Custom tailoring fields
    garment_type: Optional[str] = None
    measurements_summary: Optional[str] = None
    fabric_details: Optional[str] = None
    delivery_deadline: Optional[str] = None

    def get_field_value(self, field_name: str) -> Any:
        """Get any field value, either from defined attributes or extra attributes."""
        if hasattr(self, field_name):
            return getattr(self, field_name)
        return getattr(self, "__pydantic_extra__", {}).get(field_name)

class VerificationResult(BaseModel):
    has_mismatches: bool = False
    mismatch_details: List[str] = []
    revised_confidence: float = 0.0

class OrderData(BaseModel):
    """Internal representation of a complete order for processing."""
    order_id: str
    telegram_chat_id: int
    telegram_username: Optional[str] = None
    telegram_first_name: Optional[str] = None
    raw_input: str
    input_type: str  # text, voice, photo
    extraction: PrescriptionExtraction
    verification: Optional[VerificationResult] = None
    status: str  # Needs Human, Auto-Approved, Needs Approval
    notion_page_id: Optional[str] = None
    created_at: str  # ISO 8601

# === Telegram Update Models ===

class TelegramUser(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None

class TelegramChat(BaseModel):
    id: int
    type: str
    username: Optional[str] = None
    first_name: Optional[str] = None

class TelegramPhotoSize(BaseModel):
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: Optional[int] = None

class TelegramVoice(BaseModel):
    file_id: str
    file_unique_id: str
    duration: int
    mime_type: Optional[str] = "audio/ogg"
    file_size: Optional[int] = None

class TelegramMessage(BaseModel):
    message_id: int
    from_user: Optional[TelegramUser] = Field(None, alias="from")
    chat: TelegramChat
    date: int
    text: Optional[str] = None
    voice: Optional[TelegramVoice] = None
    photo: Optional[List[TelegramPhotoSize]] = None
    caption: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)

class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
