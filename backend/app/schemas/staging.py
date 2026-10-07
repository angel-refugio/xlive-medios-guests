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


# --- Revisión por video (Staging Review rediseñado) ----------------------------

ReviewFilter = Literal["pending", "with_contacts", "no_candidates", "no_guests", "duplicates"]


class ReviewGuestCandidate(BaseModel):
    """Un invitado candidato pendiente, tal como se muestra dentro de la tarjeta del video."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    extracted_name: str
    adjusted_confidence: float
    is_possible_group: bool
    category_match: str | None
    category_is_new_suggestion: bool
    found_in_title: bool
    found_in_description: bool
    evidence: str


class ReviewContactCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type_hint: str
    value: str


class ReviewDoubtful(BaseModel):
    """Un nombre que la ingesta no pudo clasificar; `guess` es solo la pista del LLM."""

    name: str
    guess: Literal["guest", "host", "unknown"] = "unknown"


class ReviewVideoOut(BaseModel):
    id: int
    youtube_video_id: str
    title: str
    description: str | None
    published_at: datetime | None
    guest_status: str
    possible_duplicate_of_video_id: int | None
    # Programa ya asignado al video, y lo que propone la ingesta (programa del catálogo y
    # conductores). Los conductores son del programa: `program_host_names` son los que ya tiene.
    program_id: int | None = None
    suggested_program_id: int | None = None
    suggested_host_names: list[str] = []
    program_host_names: list[str] = []
    # Para un clic: nombres dudosos, y conductores habituales de la serie/programa que el texto
    # del video no menciona (sin repetir los ya sugeridos).
    doubtful_names: list[ReviewDoubtful] = []
    usual_host_names: list[str] = []
    guest_candidates: list[ReviewGuestCandidate]
    contact_candidates: list[ReviewContactCandidate]


class ReviewVideoPage(BaseModel):
    items: list[ReviewVideoOut]
    total: int
    page: int
    page_size: int


class ReviewCounts(BaseModel):
    """Cuántos videos hay en cada filtro (los contadores de la barra superior)."""

    pending: int
    with_contacts: int
    no_candidates: int
    no_guests: int
    duplicates: int


class ReviewGuestAccept(BaseModel):
    """Acepta un candidato. `full_name` es el nombre ya corregido por quien revisa; si se omite,
    se usa el extraído. `existing_guest_id` vincula con un invitado que ya existe."""

    candidate_id: int
    full_name: str | None = None
    existing_guest_id: int | None = None

    _clean_full_name = field_validator("full_name")(_clean_optional_text)


class ReviewAddedGuest(BaseModel):
    """Invitado que quien revisa agrega a mano (la extracción no lo encontró)."""

    full_name: str
    existing_guest_id: int | None = None

    @field_validator("full_name")
    @classmethod
    def _required_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("El nombre no puede estar vacío")
        return value


class ReviewResolve(BaseModel):
    """Lo que decide el humano sobre un video: aceptar (con ediciones), quitar y/o agregar
    invitados, o marcarlo "sin invitados"."""

    guests: list[ReviewGuestAccept] = []
    reject_candidate_ids: list[int] = []
    added_guests: list[ReviewAddedGuest] = []
    no_guests: bool = False
    # Programa del video y conductores de ese programa, ya revisados. Los conductores que no
    # existan en el catálogo se crean; se agregan al programa sin quitar los que ya tenía. Al
    # resolver el video se cierra su sugerencia: aceptada si se envió alguno, rechazada si no.
    program_id: int | None = None
    host_names: list[str] = []

    @field_validator("host_names")
    @classmethod
    def _clean_host_names(cls, names: list[str]) -> list[str]:
        cleaned: list[str] = []
        for name in names:
            name = " ".join(name.split())
            if not name:
                raise ValueError("El nombre de un conductor no puede estar vacío")
            if name.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(name)
        return cleaned


class ReviewResolveOut(BaseModel):
    video_id: int
    guest_status: str
    accepted_guest_ids: list[int]
    rejected_count: int
    program_id: int | None = None
    host_ids: list[int] = []
