"""Esquemas de los catálogos configurables (mismos campos para los 5)."""
from pydantic import BaseModel, ConfigDict, field_validator


def _clean_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())  # recorta y colapsa espacios internos
    if not value:
        raise ValueError("El nombre no puede estar vacío")
    if len(value) > 150:
        raise ValueError("El nombre no puede superar 150 caracteres")
    return value


class CatalogCreate(BaseModel):
    name: str

    _validate_name = field_validator("name")(_clean_name)


class CatalogUpdate(BaseModel):
    """Renombrar y/o activar/desactivar; los campos omitidos no cambian."""

    name: str | None = None
    is_active: bool | None = None

    _validate_name = field_validator("name")(_clean_name)


class CatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
