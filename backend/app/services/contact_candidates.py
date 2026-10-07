"""Contactos candidatos por regex (v5) y su asociación con lo que decide Claude.

Diseño acordado: la regex saca SIEMPRE los contactos del texto (links, correos, @handles y
teléfonos) y Claude solo los asocia al invitado, indica la relación y marca los dudosos; no
inventa ni omite contactos. Así el recall de contactos no depende de la variación del modelo
entre corridas. Ver `docs/PHASE3_PLAN.md` (adenda de contactos) y la Propuesta.

Los enlaces de la lista de ignorados (`contact_filters`) nunca llegan a candidatos. Los valores
de los contactos no se escriben en los logs, solo conteos.
"""
import logging
import re
from dataclasses import dataclass

from app.schemas.claude_extraction import ContactCandidate, VideoExtraction
from app.services import contact_filters, regex_rules

logger = logging.getLogger(__name__)

EVIDENCE_MAX_CHARS = 300
_URL_RE = re.compile(r"https?://\S+")
# @usuario que no es parte de un correo ni de una ruta (el lookbehind descarta `a@b.com` y `/@x`).
_HANDLE_RE = re.compile(r"(?<![\w.@/])@([A-Za-z0-9_][A-Za-z0-9_.]{2,29})")
# Teléfono de 10 dígitos (México) con separadores opcionales y lada +52/52 opcional. Se busca sin
# las URLs para no confundir ids ni fechas.
_PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+?52[\s.-]?)?(?:\d{2}[\s.-]?\d{4}[\s.-]?\d{4}|\d{3}[\s.-]?\d{3}[\s.-]?\d{4}|\d{10})(?!\w)"
)


@dataclass
class Candidate:
    """Contacto encontrado por regex en un video, con un id local (`c1`, `c2`…)."""

    id: str
    type: str
    value: str
    evidence: str

    def as_prompt_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "value": self.value, "evidence": self.evidence}


def _evidence_line(text: str, value: str) -> str:
    for line in text.splitlines():
        if value in line:
            return " ".join(line.split())[:EVIDENCE_MAX_CHARS]
    return value[:EVIDENCE_MAX_CHARS]


def extract_candidates(title: str, description: str | None, ignored: list[str] | None = None) -> list[Candidate]:
    """Contactos candidatos del título y la descripción, sin repetir y sin los ignorados."""
    text = f"{title}\n{description or ''}"
    ignored = ignored or []
    found: list[tuple[str, str]] = [(m.type_hint, m.value) for m in regex_rules.extract_contacts(text)]

    without_urls = _URL_RE.sub(" ", text)
    for match in _PHONE_RE.finditer(without_urls):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) in (10, 12) and len(set(digits)) > 1:
            found.append(("telefono", match.group(0).strip()))
    for handle in _HANDLE_RE.finditer(without_urls):
        value = "@" + handle.group(1).rstrip(".")
        if any(ch.isalpha() for ch in value):
            found.append(("handle", value))

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for kind, value in found:
        key = contact_filters.normalize_contact(value)
        if not key or key in seen or contact_filters.is_ignored(value, ignored):
            continue
        # Un @handle que ya aparece dentro de otro candidato (p. ej. su URL de Instagram) es el mismo.
        if kind == "handle" and any(key.lstrip("@") in other for other in seen):
            continue
        seen.add(key)
        candidates.append(Candidate(id=f"c{len(candidates) + 1}", type=kind, value=value,
                                    evidence=_evidence_line(text, value)))
    return candidates


def resolve_contacts(video: VideoExtraction, candidates: list[Candidate]) -> dict[str, int]:
    """Arma `contacts` y `unassigned_contacts` del video a partir de los candidatos de la regex y
    de las decisiones de Claude (`contact_links`). Reemplaza lo que haya en esos dos campos.

    Un candidato sin decisión de Claude queda sin asignar y dudoso ("no evaluado por Claude"); uno
    con `discard` se descarta (contacto de un conductor o cuenta ajena); un id desconocido se
    ignora. Devuelve conteos, nunca valores.
    """
    by_id = {c.id: c for c in candidates}
    links = {}
    unknown = 0
    for link in video.contact_links:
        if link.candidate_id in by_id:
            links.setdefault(link.candidate_id, link)
        else:
            unknown += 1

    contacts: list[ContactCandidate] = []
    unassigned: list[ContactCandidate] = []
    discarded = not_evaluated = 0
    for candidate in candidates:
        link = links.get(candidate.id)
        if link is not None and link.discard:
            discarded += 1
            continue
        base = {"type": candidate.type, "value": candidate.value, "evidence": candidate.evidence}
        if link is None:
            not_evaluated += 1
            item = ContactCandidate(**base, doubtful=True, doubtful_reason="no evaluado por Claude")
        else:
            item = ContactCandidate(
                **base, relationship=link.relationship, guest=link.guest, doubtful=link.doubtful,
                doubtful_reason=link.doubtful_reason, possible_guest=link.possible_guest,
            )
        (contacts if item.guest else unassigned).append(item)
    video.contacts, video.unassigned_contacts = contacts, unassigned
    if unknown or not_evaluated:
        logger.warning(
            "[app.services.contact_candidates.resolve_contacts] video %s: %d id(s) desconocido(s), %d sin evaluar",
            video.video_id, unknown, not_evaluated,
        )
    return {"discarded": discarded, "unknown_links": unknown, "not_evaluated": not_evaluated}
