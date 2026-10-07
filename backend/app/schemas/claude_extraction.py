"""Contrato de salida del extractor con Claude (Claude Code o API), un JSON por lote de videos.

Es el mismo esquema para las dos formas de ejecutar el extractor (ver
`docs/Propuesta_extracción_invitados_Claude.md`). Todo es candidato hasta la revisión humana.
Las instrucciones que producen este JSON están en `app/prompts/extraction_instructions_v1.md`.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _clean_required(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("El texto no puede estar vacío")
    return value


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None


class NamedCandidate(BaseModel):
    """Invitado o conductor propuesto, con confianza y fragmento de evidencia."""

    name: str = Field(max_length=255)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=500)

    _clean_name = field_validator("name")(_clean_required)


class DoubtfulName(BaseModel):
    """Nombre que Claude no pudo clasificar; lo decide una persona."""

    name: str = Field(max_length=255)
    reason: str = Field(default="", max_length=300)

    _clean_name = field_validator("name")(_clean_required)


class ContactCandidate(BaseModel):
    """Contacto escrito en el título o la descripción, asociado (o no) a un invitado."""

    type: str = Field(max_length=150)
    value: str = Field(max_length=500)
    relationship: Literal["propio", "manager", "patrocinador"] | None = None
    guest: str | None = Field(default=None, max_length=255)
    evidence: str = Field(default="", max_length=500)
    doubtful: bool = False
    doubtful_reason: str | None = Field(default=None, max_length=300)
    possible_guest: str | None = Field(default=None, max_length=255)

    _clean_type = field_validator("type")(_clean_required)
    _clean_value = field_validator("value")(_clean_required)
    _clean_guest = field_validator("guest", "possible_guest", "doubtful_reason")(_clean_optional)


class ContactLink(BaseModel):
    """Decisión de Claude sobre un contacto que ya sacó la regex (instrucciones v5): a qué invitado
    pertenece, su relación y si es dudoso. No puede cambiar el tipo ni el valor del contacto."""

    candidate_id: str = Field(max_length=20)
    guest: str | None = Field(default=None, max_length=255)
    relationship: Literal["propio", "manager", "patrocinador"] | None = None
    doubtful: bool = False
    doubtful_reason: str | None = Field(default=None, max_length=300)
    possible_guest: str | None = Field(default=None, max_length=255)
    # Contacto de un conductor o cuenta ajena: se identifica y NO se guarda.
    discard: bool = False

    _clean_optional_fields = field_validator("guest", "possible_guest", "doubtful_reason")(_clean_optional)


class VideoExtraction(BaseModel):
    """Resultado para un video."""

    video_id: str = Field(max_length=50)
    program: str | None = Field(default=None, max_length=255)
    no_guests: bool = False
    guests: list[NamedCandidate] = Field(default_factory=list)
    hosts: list[NamedCandidate] = Field(default_factory=list)
    doubtful: list[DoubtfulName] = Field(default_factory=list)
    contacts: list[ContactCandidate] = Field(default_factory=list)
    unassigned_contacts: list[ContactCandidate] = Field(default_factory=list)
    # Solo v5: asociaciones de Claude; `contacts`/`unassigned_contacts` se arman desde ellas y la regex.
    contact_links: list[ContactLink] = Field(default_factory=list)

    _clean_program = field_validator("program")(_clean_optional)


class BatchExtraction(BaseModel):
    """Salida completa de una llamada: un elemento por video del lote."""

    instructions_version: str = Field(max_length=20)
    videos: list[VideoExtraction]
