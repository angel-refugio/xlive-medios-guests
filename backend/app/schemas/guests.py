"""Esquemas de invitados. Solo el nombre es obligatorio; el resto es opcional."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.catalogs import CatalogOut, _clean_name

MAX_AGE = 120  # tope de cordura para la edad aproximada


def _clean_optional_text(value: str | None) -> str | None:
    """Recorta espacios; un texto vacío equivale a "sin dato" (None)."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    if not value:
        raise ValueError("El nombre del invitado no puede estar vacío")
    if len(value) > 255:
        raise ValueError("El nombre del invitado no puede superar 255 caracteres")
    return value


def _clean_category_names(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [_clean_name(v) for v in values]


class GuestBase(BaseModel):
    organization: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    approx_age: int | None = Field(default=None, ge=0, le=MAX_AGE)
    borough_id: int | None = None

    _clean_texts = field_validator("organization", "role", "notes")(_clean_optional_text)


class GuestCreate(GuestBase):
    full_name: str
    # Categorías existentes por id y/o nombres nuevos (se crean al vuelo si no existen).
    category_ids: list[int] = []
    new_categories: list[str] = []

    _validate_full_name = field_validator("full_name")(_clean_full_name)
    _validate_new_categories = field_validator("new_categories")(_clean_category_names)


class GuestUpdate(GuestBase):
    """Edición parcial: solo cambian los campos enviados (enviar null borra el dato).

    Si se envía `category_ids` o `new_categories`, la lista de categorías del invitado
    se reemplaza por el resultado; si se omiten ambos, las categorías no cambian.
    """

    full_name: str | None = None
    category_ids: list[int] | None = None
    new_categories: list[str] | None = None

    _validate_full_name = field_validator("full_name")(_clean_full_name)
    _validate_new_categories = field_validator("new_categories")(_clean_category_names)


class GuestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    organization: str | None
    role: str | None
    notes: str | None
    approx_age: int | None
    borough: CatalogOut | None
    categories: list[CatalogOut]


class GuestPage(BaseModel):
    items: list[GuestOut]
    total: int
    page: int
    page_size: int
