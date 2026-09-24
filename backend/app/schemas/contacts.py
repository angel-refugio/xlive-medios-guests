"""Esquemas de contactos del invitado. Obligatorios: tipo y valor; el resto es opcional."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.catalogs import CatalogOut
from app.schemas.guests import _clean_optional_text

ContactSource = Literal["manual", "video_description"]


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("El valor del contacto no puede estar vacío")
    return value


class ContactCreate(BaseModel):
    contact_type_id: int
    value: str = Field(max_length=500)
    note: str | None = Field(default=None, max_length=500)
    source: ContactSource = "manual"
    verified: bool = False

    _validate_value = field_validator("value")(_clean_value)
    _clean_note = field_validator("note")(_clean_optional_text)


class ContactUpdate(BaseModel):
    """Edición parcial: solo cambian los campos enviados (note: null borra la nota)."""

    contact_type_id: int | None = None
    value: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)
    source: ContactSource | None = None
    verified: bool | None = None

    _validate_value = field_validator("value")(_clean_value)
    _clean_note = field_validator("note")(_clean_optional_text)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guest_id: int
    contact_type: CatalogOut
    value: str
    note: str | None
    source: str
    verified: bool
