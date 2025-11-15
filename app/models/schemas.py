from typing import Literal
from enum import Enum
from pydantic import BaseModel

# --- Enums ---
class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    FAILED_GENERATION = "FAILED_GENERATION"

# --- Request Models ---
class ChatHistoryItem(BaseModel):
    role: Literal["user", "ai"]
    content: str

class ReportRequest(BaseModel):
    pass

# --- Response Models ---
class ReportResponse(BaseModel):
    pass