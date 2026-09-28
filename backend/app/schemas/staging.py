"""Fase 3, paso 7: esquemas de Staging Review (candidatos pendientes de revisión humana)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.guests import _clean_optional_text
from app.schemas.videos import VideoSummary

CandidateStatus = Literal["pending", "accepted", "rejected"]


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("El valor no puede estar vacío")
    return value


# --- Invitados candidatos -----------------------------------------------------

class GuestCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video: VideoSummary
    extracted_name: str
    found_in_title: bool
    found_in_description: bool
    is_possible_group: bool
    category_match: str | None
    category_is_new_suggestion: bool
    raw_confidence: float
    adjusted_confidence: float
    evidence: str
    extraction_method: str
    status: CandidateStatus
    linked_guest_id: int | None
    reviewed_at: datetime | None
    created_at: datetime


class GuestCandidatePage(BaseModel):
    items: list[GuestCandidateOut]
    total: int
    page: int
    page_size: int


class GuestCandidateAccept(BaseModel):
    """Vincula a un invitado existente (`existing_guest_id`) o crea uno nuevo.

    Si se omite `full_name` al crear uno nuevo, se usa `extracted_name` del candidato.
    """

    existing_guest_id: int | None = None
    full_name: str | None = None
    organization: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    approx_age: int | None = Field(default=None, ge=0, le=120)
    borough_id: int | None = None
    category_ids: list[int] = []
    new_categories: list[str] = []

    _clean_texts = field_validator("organization", "role", "notes")(_clean_optional_text)
    _clean_full_name = field_validator("full_name")(_clean_optional_text)


class GuestSuggestion(BaseModel):
    """Invitado existente con nombre parecido, para no duplicar (FR-001)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


# --- Contactos candidatos ------------------------------------------------------

class ContactCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video: VideoSummary
    guest_candidate_id: int | None
    type_hint: str
    value: str
    raw_confidence: float
    extraction_method: str
    status: CandidateStatus
    linked_contact_id: int | None
    reviewed_at: datetime | None
    created_at: datetime


class ContactCandidatePage(BaseModel):
    items: list[ContactCandidateOut]
    total: int
    page: int
    page_size: int


class ContactCandidateAccept(BaseModel):
    """El invitado al que se le atribuye el contacto es explícito: nunca se infiere solo."""

    guest_id: int
    contact_type_id: int
    value: str | None = None
    note: str | None = Field(default=None, max_length=500)

    _clean_value = field_validator("value")(_clean_value)
    _clean_note = field_validator("note")(_clean_optional_text)
