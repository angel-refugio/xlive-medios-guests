"""Contrato de datos del pipeline de ingesta con IA (Fase 3, paso 1).

Fija la forma (tipos y validación) de lo que produce el LLM local (Ollama) para un video, a
partir solo de título y descripción, sin transcripción. Todo esto es candidato: nada se guarda
como dato final sin pasar por Staging Review (paso 7). La lógica de extracción en sí (prompt,
reglas de regex previas) es de los pasos 4 y 5, todavía sin implementar.

Reglas de contenido acordadas con el usuario: ver docs/PHASE3_PLAN.md, sección
"Reglas del pipeline".
"""
from pydantic import BaseModel, Field, field_validator


def _clean_required_text(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("El texto no puede estar vacío")
    return value


def _clean_optional_catalog_text(value: str | None) -> str | None:
    """Para los *_match contra catálogo: recorta espacios; vacío equivale a "sin coincidencia"."""
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class GuestCandidate(BaseModel):
    """Un invitado propuesto por el LLM a partir del título y la descripción."""

    name: str = Field(max_length=255)
    # Señales objetivas para el ajuste de confianza (regla del pipeline: título+descripción
    # a favor, solo descripción neutro). Se registran junto con el candidato porque dependen
    # de dónde encontró el nombre el propio LLM, no se pueden recalcular después.
    found_in_title: bool
    found_in_description: bool
    # Bandas/colectivos: "posible grupo, no persona". No se descarta el candidato, se marca
    # la ambigüedad para que Staging Review decida.
    is_possible_group: bool = False
    # Nombre de una categoría existente en el catálogo `guest_categories`, o una sugerencia de
    # categoría nueva (texto libre); None si el texto no la sustenta.
    category_match: str | None = Field(default=None, max_length=150)
    category_is_new_suggestion: bool = False
    # Confianza cruda del LLM (0-1). Staging Review ordena por el ajuste calculado aparte de
    # este contrato (el modelo de 3B calibra mal), no por este valor directo.
    raw_confidence: float = Field(ge=0.0, le=1.0)
    # Fragmento de título/descripción que sustenta el candidato, para que la revisión humana
    # no tenga que releer todo el video.
    evidence: str = Field(max_length=500)

    _clean_name = field_validator("name")(_clean_required_text)
    _clean_evidence = field_validator("evidence")(_clean_required_text)
    _clean_category_match = field_validator("category_match")(_clean_optional_catalog_text)


class ContactCandidate(BaseModel):
    """Un contacto propuesto por el LLM en prosa (complementa, no sustituye, al regex).

    Los contactos por regex (URLs, `ETIQUETA:` + usuario, correos) se extraen aparte, en el
    paso 4, con `source='video_description'` y sin pasar por el LLM.
    """

    # Pista de tipo en texto libre (p. ej. "instagram", "celular", "patrocinador"); se
    # empareja contra el catálogo `contact_types` en Staging Review, no en este contrato.
    type_hint: str = Field(max_length=150)
    value: str = Field(max_length=500)
    # Siempre baja por regla del pipeline: el LLM solo complementa lo que el regex ya
    # encontró con patrones explícitos, nunca lo reemplaza.
    raw_confidence: float = Field(ge=0.0, le=1.0)

    _clean_type_hint = field_validator("type_hint")(_clean_required_text)
    _clean_value = field_validator("value")(_clean_required_text)


class VideoAnalysis(BaseModel):
    """Salida completa del LLM para un video.

    `host_match`, `program_match`, `video_type_match` y `event_borough_match` nunca crean
    catálogo nuevo: solo señalan una coincidencia contra `hosts`, `programs`, `video_types` y
    `boroughs` existentes (comparando con `normalize_name`, ver `app.services.catalogs`).
    """

    # Opinión del LLM sobre si el video no tiene invitados. No reemplaza la regla de regex
    # obligatoria del paso 4 (4 condiciones simultáneas, la única que clasifica "sin invitados"
    # de forma automática): es una señal más para Staging Review cuando el regex no clasificó
    # el video por sí solo.
    no_guests_opinion: bool = False
    guests: list[GuestCandidate] = []
    contacts: list[ContactCandidate] = []
    # Alcaldía del evento: solo si el texto nombra una alcaldía oficial de CDMX literalmente
    # (colonias/zonas o fuera de CDMX no cuentan). Tipo de video: solo con palabra clave
    # explícita. None/cadena vacía = sin coincidencia.
    video_type_match: str | None = Field(default=None, max_length=150)
    event_borough_match: str | None = Field(default=None, max_length=150)
    host_match: str | None = Field(default=None, max_length=150)
    program_match: str | None = Field(default=None, max_length=150)

    _clean_video_type_match = field_validator("video_type_match")(_clean_optional_catalog_text)
    _clean_event_borough_match = field_validator("event_borough_match")(
        _clean_optional_catalog_text
    )
    _clean_host_match = field_validator("host_match")(_clean_optional_catalog_text)
    _clean_program_match = field_validator("program_match")(_clean_optional_catalog_text)
