"""Fase 3, paso 4: reglas de regex previas al LLM (sin red, sin modelo).

Tres cosas, según la sección "Reglas del pipeline" de docs/PHASE3_PLAN.md:
1. `extract_contacts`: contactos candidatos en la descripción (URLs, `ETIQUETA:` + usuario,
   correos), siempre con `source='video_description'` una vez aceptados en Staging Review.
2. `extract_name_candidates`: los 3 "patrones regex adicionales" de nombre por formato
   (confianza baja/media: después de dos puntos, `con Nombre`, MAYÚSCULAS entre paréntesis),
   para cubrir nombres sin palabra clave explícita.
3. `is_no_guests_candidate`: detecta "sin invitados" (FR-014) con una regla conservadora de
   4 condiciones simultáneas — si falta cualquiera, el video va a la cola normal, nunca se
   auto-clasifica "sin invitados" por default.

Todo lo que produce este módulo es candidato, igual que lo del LLM (paso 5).
"""
import re
from dataclasses import dataclass

# --- Contactos ----------------------------------------------------------------

_LABEL_RE = re.compile(r"(?im)^[ \t]*(FACEBOOK|INSTAGRAM|IG|YOUTUBE|TIKTOK)[ \t]*:[ \t]*(\S.*)$")
_LABEL_TYPE_HINTS = {
    "FACEBOOK": "facebook", "INSTAGRAM": "instagram", "IG": "instagram",
    "YOUTUBE": "youtube", "TIKTOK": "tiktok",
}
_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_DOMAIN_TYPE_HINTS = (
    ("facebook.com", "facebook"), ("fb.com", "facebook"),
    ("instagram.com", "instagram"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"), ("youtu.be", "youtube"),
    ("wa.me", "whatsapp"), ("whatsapp.com", "whatsapp"),
)
_TRAILING_PUNCTUATION = ").,;:|• \t"


@dataclass
class ContactMatch:
    """Un contacto candidato encontrado por regex en la descripción."""

    type_hint: str
    value: str
    evidence: str


def _url_type_hint(url: str) -> str:
    lowered = url.lower()
    for domain, hint in _URL_DOMAIN_TYPE_HINTS:
        if domain in lowered:
            return hint
    return "url"


def extract_contacts(description: str | None) -> list[ContactMatch]:
    """Contactos candidatos por regex: URLs, `ETIQUETA:` + usuario y correos.

    Deduplica por valor (una URL puesta como `INSTAGRAM: https://instagram.com/x` no se
    repite al volver a coincidir con el patrón genérico de URL).
    """
    if not description:
        return []

    matches: list[ContactMatch] = []
    seen_values: set[str] = set()

    def add(type_hint: str, raw_value: str, evidence: str) -> None:
        value = raw_value.strip().rstrip(_TRAILING_PUNCTUATION)
        if not value or value in seen_values:
            return
        seen_values.add(value)
        matches.append(ContactMatch(type_hint=type_hint, value=value, evidence=evidence.strip()))

    for label, value in _LABEL_RE.findall(description):
        add(_LABEL_TYPE_HINTS[label.upper()], value, f"{label}: {value}")
    for url in _URL_RE.findall(description):
        add(_url_type_hint(url), url, url)
    for email in _EMAIL_RE.findall(description):
        add("email", email, email)

    return matches


# --- Candidatos de nombre por formato (confianza baja/media) --------------------

_TITLE_CASE_NAME = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3}"
# (1) Después de dos puntos, Título Caso hasta 4 palabras. Separador [ \t], no \s: una
# descripción real tiene varias líneas y \s también matchea el salto de línea, lo que "cruzaba"
# el nombre hacia la línea siguiente si esta también empezaba con mayúscula.
_AFTER_COLON_RE = re.compile(rf":[ \t]*({_TITLE_CASE_NAME})")
# (2) "con [Nombre Apellido]" en Título Caso. Solo "con" es insensible a mayúsculas: el resto
# del patrón debe seguir exigiendo Título Caso, si no deja de servir para distinguir nombres.
_CON_NOMBRE_RE = re.compile(rf"\b[Cc]on[ \t]+({_TITLE_CASE_NAME})\b")
# (3) Texto en MAYÚSCULAS dentro de paréntesis.
_UPPERCASE_PARENS_RE = re.compile(r"\(([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ]{2,})\)")

_NAME_PATTERNS = (
    ("after_colon", _AFTER_COLON_RE),
    ("con_nombre", _CON_NOMBRE_RE),
    ("uppercase_parens", _UPPERCASE_PARENS_RE),
)


@dataclass
class NameCandidateMatch:
    """Un nombre candidato encontrado por formato, no por palabra clave explícita."""

    name: str
    pattern: str
    evidence: str


def extract_name_candidates(title: str, description: str | None) -> list[NameCandidateMatch]:
    """Nombres candidatos por los 3 patrones de formato (confianza baja/media).

    A diferencia de las palabras clave de alta señal (`Invitado:`, `presenta a`...), estos
    patrones también pueden matchear nombres de programa o frases genéricas, así que su
    confianza numérica la decide el orquestador (paso 6), no este módulo.
    """
    combined = f"{title}\n{description or ''}"
    matches: list[NameCandidateMatch] = []
    seen_names: set[str] = set()
    for pattern_name, regex in _NAME_PATTERNS:
        for raw_name in regex.findall(combined):
            name = " ".join(raw_name.split())
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            matches.append(NameCandidateMatch(name=name, pattern=pattern_name, evidence=name))
    return matches


def _has_recognizable_name(text: str) -> bool:
    """Cualquiera de los 3 patrones de formato de arriba, sin distinguir cuál."""
    return any(regex.search(text) for _, regex in _NAME_PATTERNS)


# --- "Sin invitados" (FR-014) --------------------------------------------------

# Nombre propio "fuerte": palabras clave de alta señal que anuncian un nombre explícito,
# no el formato genérico de arriba (esas son "confianza baja/media", no "fuertes").
_STRONG_NAME_MARKER_RE = re.compile(
    r"(?i)(invitad[ao]\s*:|presenta a|nombre real\s*:|es el seud[oó]nimo(?: art[ií]stico)? de)"
)
_GUEST_KEYWORD_RE = re.compile(
    r"(?i)\b(invitad\w*|presenta a|conduce\w*|entrevista\w*|platicamos con)\b"
)
_GENERIC_EVENT_RE = re.compile(r"(?i)\b(foro\w*|torneo\w*)\b")


def is_no_guests_candidate(title: str, description: str | None) -> bool:
    """Regla conservadora de FR-014: las 4 condiciones deben cumplirse TODAS.

    (1) ningún nombre propio fuerte (palabra clave de alta señal) en título ni descripción;
    (2) ninguna palabra clave de invitado/conducción; (3) descripción vacía y título sin
    nombre reconocible (patrones de formato); (4) vocabulario de evento genérico sin nombre de
    persona. Si falta cualquiera, el video va a la cola normal — este resultado es solo una
    señal más para Staging Review, nunca borra ni descarta nada por sí solo.
    """
    description = description or ""
    combined = f"{title}\n{description}"

    no_strong_name = not _STRONG_NAME_MARKER_RE.search(combined)
    no_guest_keyword = not _GUEST_KEYWORD_RE.search(combined)
    empty_description_and_clean_title = (
        not description.strip() and not _has_recognizable_name(title)
    )
    no_generic_vocab_with_name = not (
        _GENERIC_EVENT_RE.search(combined) and _has_recognizable_name(combined)
    )

    return (
        no_strong_name
        and no_guest_keyword
        and empty_description_and_clean_title
        and no_generic_vocab_with_name
    )
