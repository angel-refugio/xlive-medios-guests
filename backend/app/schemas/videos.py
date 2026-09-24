"""Esquemas de videos cargados a mano. Obligatorios: youtube_video_id y título."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.catalogs import CatalogOut
from app.schemas.guests import _clean_optional_text

GuestStatus = Literal["pending", "has_guests", "no_guests"]
VideoSource = Literal["manual", "youtube"]


def _required_text(label: str):
    def clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError(f"{label} no puede estar vacío")
        return value

    return clean


class VideoBase(BaseModel):
    description: str | None = None
    published_at: datetime | None = None
    video_type_id: int | None = None
    program_id: int | None = None
    event_borough_id: int | None = None
    part_of_video_id: int | None = None

    _clean_description = field_validator("description")(_clean_optional_text)


class VideoCreate(VideoBase):
    youtube_video_id: str = Field(max_length=32)
    title: str = Field(max_length=500)
    guest_status: GuestStatus = "pending"

    _clean_youtube_id = field_validator("youtube_video_id")(_required_text("El id de YouTube"))
    _clean_title = field_validator("title")(_required_text("El título"))


class VideoUpdate(VideoBase):
    """Edición parcial: solo cambian los campos enviados (null borra los opcionales)."""

    youtube_video_id: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=500)
    guest_status: GuestStatus | None = None

    _clean_youtube_id = field_validator("youtube_video_id")(_required_text("El id de YouTube"))
    _clean_title = field_validator("title")(_required_text("El título"))


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    youtube_video_id: str
    title: str
    description: str | None
    published_at: datetime | None
    source: str
    guest_status: str
    video_type: CatalogOut | None
    program: CatalogOut | None
    event_borough: CatalogOut | None
    part_of_video_id: int | None


class VideoSummary(BaseModel):
    """Datos mínimos del video, para mostrarlo dentro de una participación."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    youtube_video_id: str
    title: str
    source: str


class VideoPage(BaseModel):
    items: list[VideoOut]
    total: int
    page: int
    page_size: int
