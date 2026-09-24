"""Esquemas de participaciones (invitado ↔ video)."""
from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.guests import _clean_optional_text
from app.schemas.videos import VideoSummary


class GuestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class ParticipationCreate(BaseModel):
    video_id: int
    notes: str | None = None

    _clean_notes = field_validator("notes")(_clean_optional_text)


class ParticipationUpdate(BaseModel):
    """Solo se editan las notas (para cambiar de video, se borra y se crea otra)."""

    notes: str | None = None

    _clean_notes = field_validator("notes")(_clean_optional_text)


class ParticipationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guest: GuestSummary
    video: VideoSummary
    notes: str | None
