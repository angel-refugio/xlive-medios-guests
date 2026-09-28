"""Fase 3, paso 5: cliente de Ollama para analizar un video (solo título + descripción).

Un video a la vez, sin transcripción (según PROJECT_BRIEF.md). La salida se valida contra el
contrato de `app/schemas/ingestion.py` (`VideoAnalysis`); si el modelo devuelve JSON inválido o
que no cumple el contrato, se reintenta. Todo lo que produce esto es candidato, igual que las
reglas de regex (paso 4): nada se guarda sin pasar por Staging Review (paso 7).
"""
import json
import logging
from collections.abc import Sequence

import httpx
from pydantic import ValidationError

from app.schemas.ingestion import VideoAnalysis

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3

_PROMPT_TEMPLATE = """\
Analiza este video del canal de YouTube "X Live Medios" a partir SOLO de su título y \
descripción (no hay transcripción). Responde ÚNICAMENTE JSON que cumpla el esquema indicado.

Reglas de contenido (síguelas exactamente; todo lo que propongas es candidato, no dato final):
- Invitado: prioriza patrones de alta señal ("Invitado:", "presenta a", "nombre real:", \
"es el seudónimo artístico de"). Si el nombre aparece en el título Y la descripción, \
raw_confidence alta (0.7-1.0); si aparece solo en la descripción, media/baja (0.3-0.6).
- Bandas o colectivos: marca is_possible_group=true, no los propongas como invitado individual.
- category_match: solo con texto biográfico que lo sustente; si no hay categoría existente \
que aplique pero el texto sí sustenta una, usa category_is_new_suggestion=true con el nombre \
propuesto en category_match. Si no hay sustento, deja category_match en null.
- Contactos: propón solo si hay un dato de contacto en prosa (no repitas URLs o \
"ETIQUETA: valor" ya explícitos, esos ya se extraen aparte); siempre raw_confidence baja \
(0.1-0.3).
- video_type_match: solo con palabra clave explícita de tipo de video.
- event_borough_match: solo si el texto nombra una alcaldía OFICIAL de la Ciudad de México de \
forma literal. Colonias, zonas (p. ej. "Zona Rosa") o lugares fuera de la Ciudad de México NO \
cuentan.
- host_match / program_match: SOLO si el texto coincide con uno de los catálogos existentes \
de abajo; nunca inventes un conductor o programa nuevo. Si el título mezcla un conductor y un \
invitado sin distinguir cuál es cuál, no asignes host_match ni marques al conductor como \
invitado: repórtalo solo como invitado (queda a revisión humana).
- no_guests_opinion: true solo si de verdad no ves ninguna señal de invitado.

Catálogo existente de categorías de invitado: {categories}
Catálogo existente de tipos de video: {video_types}
Catálogo existente de alcaldías de la Ciudad de México: {boroughs}
Catálogo existente de conductores: {hosts}
Catálogo existente de programas: {programs}

Título: {title}
Descripción: {description}
"""


class OllamaError(RuntimeError):
    """Fallo al usar el LLM local; el mensaje indica módulo, función y causa."""


def _format_catalog(items: Sequence[str]) -> str:
    return ", ".join(items) if items else "(ninguno todavía)"


def _build_prompt(
    title: str,
    description: str | None,
    *,
    existing_categories: Sequence[str],
    existing_video_types: Sequence[str],
    existing_boroughs: Sequence[str],
    existing_hosts: Sequence[str],
    existing_programs: Sequence[str],
) -> str:
    return _PROMPT_TEMPLATE.format(
        categories=_format_catalog(existing_categories),
        video_types=_format_catalog(existing_video_types),
        boroughs=_format_catalog(existing_boroughs),
        hosts=_format_catalog(existing_hosts),
        programs=_format_catalog(existing_programs),
        title=title,
        description=description or "(sin descripción)",
    )


def _call_ollama(client: httpx.Client, base_url: str, model: str, prompt: str) -> str:
    """POST a /api/generate sin streaming, pidiendo salida conforme al esquema. Texto crudo."""
    try:
        response = client.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": VideoAnalysis.model_json_schema(),
                "stream": False,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        msg = f"[app.services.ollama_client._call_ollama] Error de red: {type(exc).__name__}"
        logger.error(msg)
        raise OllamaError(msg) from exc

    if response.status_code != 200:
        msg = f"[app.services.ollama_client._call_ollama] HTTP {response.status_code} de Ollama"
        logger.error(msg)
        raise OllamaError(msg)

    try:
        return response.json()["response"]
    except (ValueError, KeyError) as exc:
        msg = "[app.services.ollama_client._call_ollama] Respuesta de Ollama sin el campo 'response'"
        logger.error(msg)
        raise OllamaError(msg) from exc


def analyze_video(
    client: httpx.Client,
    base_url: str,
    model: str,
    title: str,
    description: str | None,
    *,
    existing_categories: Sequence[str] = (),
    existing_video_types: Sequence[str] = (),
    existing_boroughs: Sequence[str] = (),
    existing_hosts: Sequence[str] = (),
    existing_programs: Sequence[str] = (),
    max_attempts: int = MAX_ATTEMPTS,
) -> VideoAnalysis:
    """Analiza un video con el LLM local; reintenta si la salida no es válida.

    `existing_*` son los nombres del catálogo actual (para que el modelo solo señale
    coincidencias reales, nunca invente conductor/programa/categoría/tipo/alcaldía nuevos,
    salvo `category_match` que sí admite sugerencia nueva vía `category_is_new_suggestion`).
    """
    prompt = _build_prompt(
        title, description,
        existing_categories=existing_categories, existing_video_types=existing_video_types,
        existing_boroughs=existing_boroughs, existing_hosts=existing_hosts,
        existing_programs=existing_programs,
    )

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_ollama(client, base_url, model, prompt)
            data = json.loads(raw)
            return VideoAnalysis.model_validate(data)
        except OllamaError as exc:
            last_error = exc
            logger.warning(
                "[app.services.ollama_client.analyze_video] %s (intento %d/%d)",
                exc, attempt, max_attempts,
            )
        except (ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "[app.services.ollama_client.analyze_video] JSON inválido del modelo "
                "(intento %d/%d): %s", attempt, max_attempts, exc,
            )
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "[app.services.ollama_client.analyze_video] Salida no cumple el contrato "
                "(intento %d/%d): %d error(es)", attempt, max_attempts, exc.error_count(),
            )

    msg = (
        f"[app.services.ollama_client.analyze_video] Sin salida válida tras {max_attempts} "
        f"intento(s): {last_error}"
    )
    logger.error(msg)
    raise OllamaError(msg) from last_error
