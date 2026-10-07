"""Fase 3, mejora de extracción (etapa 2): el LLM solo CLASIFICA candidatos, no descubre nombres.

La etapa 1 (`series_profile`) ya extrajo nombres con reglas y les puso un rol según la serie. Aquí
se le pide al modelo local (qwen2.5:3b) un veredicto solo para los candidatos dudosos:
- los que salieron de "lo que sigue a los dos puntos" o de la descripción (¿es persona o es el
  título del episodio, un tema, una frase?);
- los hashtags sin rol conocido (¿es un invitado o un tema?).
Lo que la etapa 1 ya sabe con evidencia explícita (`conduce X`, `invitado X`, conductor de la
serie) no se manda al modelo. Un video sin candidatos dudosos no llama al LLM.

El modelo nunca agrega nombres: un veredicto sobre un nombre que no se le pidió se ignora. Todo es
candidato hasta la validación humana en Staging Review.
"""
import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.services import ollama_client
from app.services.ollama_client import OllamaError
from app.services.series_profile import NameHint, VideoHints, compact

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_DESCRIPTION_CHARS = 1500
# Fuentes cuyo rol "guest" es solo una suposición por posición en el título: el LLM las confirma.
_DOUBTFUL_GUEST_SOURCES = frozenset({"title_after_colon", "description_guest"})

_PROMPT_TEMPLATE = """\
Eres un asistente que revisa nombres candidatos de un video del canal de YouTube "X Live Medios". \
Tienes SOLO el título y la descripción. Para cada nombre candidato de la lista, responde con su \
rol. Responde ÚNICAMENTE JSON que cumpla el esquema.

Roles:
- guest: una persona o artista invitado al programa (entrevistado, músico, luchador, etc.).
- group: una banda, colectivo o grupo invitado.
- host: quien conduce o presenta el programa de forma recurrente.
- topic: NO es una persona ni un grupo: tema del episodio, frase, título, lugar, empresa, \
etiqueta o nombre del programa.

Reglas:
- Devuelve un veredicto por cada nombre candidato, escrito EXACTAMENTE como aparece en la lista.
- No agregues nombres que no estén en la lista.
- Los conductores conocidos de este programa son: {known_hosts}. Si un candidato es uno de ellos, \
su rol es host.
- Si no hay evidencia de que sea una persona o un grupo, usa topic.

Programa: {program}
Título: {title}
Descripción: {description}

Nombres candidatos: {candidates}
"""


class ClassifierError(RuntimeError):
    """Fallo al clasificar candidatos con el LLM; el mensaje indica módulo, función y causa."""


class CandidateVerdict(BaseModel):
    name: str
    role: Literal["guest", "host", "group", "topic"]


class CandidateClassification(BaseModel):
    verdicts: list[CandidateVerdict] = []


def doubtful_candidates(hints: VideoHints) -> list[NameHint]:
    """Candidatos de `hints` que el LLM debe juzgar (los demás ya tienen evidencia explícita)."""
    doubtful = [g for g in hints.guests if g.source in _DOUBTFUL_GUEST_SOURCES]
    return [*doubtful, *hints.unknown]


def build_prompt(
    title: str, description: str | None, program: str, known_hosts: Sequence[str],
    candidates: Sequence[str],
) -> str:
    text = (description or "").strip()
    if len(text) > MAX_DESCRIPTION_CHARS:
        text = text[:MAX_DESCRIPTION_CHARS] + "…"
    return _PROMPT_TEMPLATE.format(
        known_hosts=", ".join(known_hosts) if known_hosts else "(ninguno conocido)",
        program=program or "(desconocido)",
        title=title,
        description=text or "(sin descripción)",
        candidates=json.dumps(list(candidates), ensure_ascii=False),
    )


def classify(
    client: httpx.Client, base_url: str, model: str, title: str, description: str | None,
    program: str, known_hosts: Sequence[str], candidates: Sequence[str],
    max_attempts: int = MAX_ATTEMPTS,
) -> CandidateClassification:
    """Pide al LLM un veredicto por candidato; reintenta si la salida no es válida."""
    prompt = build_prompt(title, description, program, known_hosts, candidates)
    schema = CandidateClassification.model_json_schema()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = ollama_client._call_ollama(client, base_url, model, prompt, schema=schema)
            return CandidateClassification.model_validate(json.loads(raw))
        except OllamaError as exc:
            last_error = exc
            logger.warning("[app.services.candidate_classifier.classify] %s (intento %d/%d)",
                           exc, attempt, max_attempts)
        except (ValueError, TypeError) as exc:  # JSON inválido (ValidationError es ValueError)
            last_error = exc
            logger.warning(
                "[app.services.candidate_classifier.classify] Salida inválida (intento %d/%d): %s",
                attempt, max_attempts, exc.error_count() if isinstance(exc, ValidationError) else exc,
            )
    msg = (
        f"[app.services.candidate_classifier.classify] Sin salida válida tras {max_attempts} "
        f"intento(s): {last_error}"
    )
    logger.error(msg)
    raise ClassifierError(msg) from last_error


def _is_corroborated(hint: NameHint, description: str | None) -> bool:
    """El nombre tras los dos puntos del título también aparece en la descripción.

    Corrección del usuario (2026-09-30): el texto tras los dos puntos es invitado aunque suene a
    banda o tema ("Viaje a Marte", "Los Ovnis"). Con esa evidencia doble, un veredicto `topic` del
    modelo de 3B no puede descartarlo; sin ella ("Novedades", "Especial Drama") sí.
    """
    return hint.source == "title_after_colon" and compact(hint.name) in compact(description or "")


def apply_verdicts(
    hints: VideoHints, classification: CandidateClassification, description: str | None = None,
    *, promote_hashtags: bool = False, allow_host_verdict: bool = False,
) -> VideoHints:
    """Aplica los veredictos del LLM sobre las pistas de la etapa 1 y devuelve unas nuevas.

    Por defecto el LLM solo puede DESCARTAR (medición del 2026-10-02 en 150 videos: dejarlo
    promover hashtags a invitado y mover nombres entre invitado y conductor bajó la precisión
    de invitados de 89 % a 79 % y causó 13 roles cambiados):
    - Invitado dudoso (tras los dos puntos / descripción): se queda salvo que el LLM diga `topic`
      (se descarta, a menos que el nombre también esté en la descripción). Sin veredicto, se queda.
    - Hashtag sin rol: NO se decide; queda en `unknown` como "dudoso" para que lo clasifique el
      humano (salvo que el LLM diga `topic`: se descarta). Con `promote_hashtags=True`, pasa a
      invitado si el LLM dice `guest`/`group`.
    - Con `allow_host_verdict=True`, un veredicto `host` mueve el nombre a conductores.
    """
    verdicts = {compact(v.name): v.role for v in classification.verdicts}
    guests: list[NameHint] = []
    hosts = list(hints.hosts)
    for hint in hints.guests:
        role = verdicts.get(compact(hint.name)) if hint.source in _DOUBTFUL_GUEST_SOURCES else None
        if role == "topic" and not _is_corroborated(hint, description):
            continue
        if role == "host" and allow_host_verdict:
            hosts.append(replace(hint, role="host", source="llm_host"))
        else:
            guests.append(hint)
    doubtful: list[NameHint] = []
    for hint in hints.unknown:
        role = verdicts.get(compact(hint.name))
        if role in ("guest", "group") and promote_hashtags:
            guests.append(replace(hint, role="guest", source="llm_guest"))
        elif role == "host" and allow_host_verdict:
            hosts.append(replace(hint, role="host", source="llm_host"))
        elif role != "topic":
            # Dudoso: no se decide solo, se le muestra al humano ("→ invitado" / "→ conductor")
            # con la opinión del LLM como pista. Lo que el LLM llamó `topic` es ruido y se descarta.
            guess = {"guest": "guest", "group": "guest", "host": "host"}.get(role or "", "unknown")
            doubtful.append(replace(hint, role=guess))
    return VideoHints(program=hints.program, hosts=hosts, guests=guests, unknown=doubtful)


def refine(
    client: httpx.Client, base_url: str, model: str, title: str, description: str | None,
    hints: VideoHints, known_hosts: Sequence[str], **policy: bool,
) -> VideoHints:
    """Etapa 2 completa: si hay candidatos dudosos, los clasifica; si no, no llama al LLM.

    `policy` son los interruptores de `apply_verdicts` (`promote_hashtags`, `allow_host_verdict`).
    """
    candidates = doubtful_candidates(hints)
    if not candidates:
        return VideoHints(program=hints.program, hosts=list(hints.hosts), guests=list(hints.guests))
    classification = classify(
        client, base_url, model, title, description, hints.program, known_hosts,
        [c.name for c in candidates],
    )
    return apply_verdicts(hints, classification, description, **policy)


# --- segunda opinión del LLM para invitados --------------------------------------------------

_MIN_CONTAINED_KEY = 4


def _same_person(a: str, b: str) -> bool:
    """Mismo nombre, o uno contenido en el otro (por letras, con al menos 4)."""
    ka, kb = compact(a), compact(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long_ = sorted((ka, kb), key=len)
    return len(short) >= _MIN_CONTAINED_KEY and short in long_


def second_opinion_guests(
    rule_guests: Sequence[str], llm_names: Sequence[str], text: str,
    excluded: Sequence[str] = (), mode: str = "union",
) -> list[str]:
    """Invitados que el LLM encontró y las reglas no, aceptados solo con evidencia literal.

    - El nombre debe aparecer TAL CUAL en `text` (título + descripción): es la defensa contra las
      invenciones del modelo de 3B ("Especial Drama" no se vuelve persona por decirlo el modelo,
      pero un nombre que no está en el texto nunca entra).
    - No se repiten los que ya sacaron las reglas ni los de `excluded` (conductores, programas).
    - `mode="fallback"`: solo si las reglas no encontraron a nadie; `"union"`: siempre.
    """
    if mode not in ("union", "fallback"):
        raise ValueError(f"[app.services.candidate_classifier.second_opinion_guests] modo desconocido: {mode!r}")
    if mode == "fallback" and rule_guests:
        return []
    text_key = compact(text)
    accepted: list[str] = []
    for name in llm_names:
        key = compact(name)
        if len(key) < 3 or key not in text_key:
            continue
        if any(_same_person(name, other) for other in (*rule_guests, *excluded, *accepted)):
            continue
        accepted.append(name)
    return accepted


# --- extracción enfocada de invitados (una sola pregunta) ----------------------------------

_SIMPLE_GUESTS_PROMPT = """\
Del siguiente video de YouTube (título y descripción) dime los nombres de las personas, artistas \
o grupos que son INVITADOS al programa. No incluyas al programa mismo ni a quien lo conduce. \
Responde solo JSON: {{"invitados": ["nombre1", "nombre2"]}}. Si no hay invitados, {{"invitados": []}}.

Título: {title}
Descripción: {description}
"""


class SimpleGuests(BaseModel):
    invitados: list[str] = []


def simple_guest_names(
    client: httpx.Client, base_url: str, model: str, title: str, description: str | None,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[str]:
    """Invitados según el LLM con UNA sola pregunta (sin los demás campos del análisis completo).

    El prompt de `ollama_client.analyze_video` pide ocho cosas a la vez y el modelo de 3B devolvía
    listas vacías incluso en casos obvios; con una pregunta enfocada acierta mucho más. Quien use
    esto debe verificar que los nombres aparezcan literales en el texto (`second_opinion_guests`).
    """
    text = (description or "").strip()
    if len(text) > MAX_DESCRIPTION_CHARS:
        text = text[:MAX_DESCRIPTION_CHARS] + "…"
    prompt = _SIMPLE_GUESTS_PROMPT.format(title=title, description=text or "(sin descripción)")
    schema = SimpleGuests.model_json_schema()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = ollama_client._call_ollama(client, base_url, model, prompt, schema=schema)
            names = SimpleGuests.model_validate(json.loads(raw)).invitados
            return [" ".join(n.split()) for n in names if n and n.strip()]
        except OllamaError as exc:
            last_error = exc
            logger.warning("[app.services.candidate_classifier.simple_guest_names] %s (intento %d/%d)",
                           exc, attempt, max_attempts)
        except (ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "[app.services.candidate_classifier.simple_guest_names] Salida inválida (intento %d/%d): %s",
                attempt, max_attempts, exc.error_count() if isinstance(exc, ValidationError) else exc,
            )
    msg = (
        f"[app.services.candidate_classifier.simple_guest_names] Sin salida válida tras {max_attempts} "
        f"intento(s): {last_error}"
    )
    logger.error(msg)
    raise ClassifierError(msg) from last_error
