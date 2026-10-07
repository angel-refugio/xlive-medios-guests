"""Lista de enlaces y cuentas a ignorar al extraer contactos.

Son enlaces fijos del canal (cuentas propias, herramientas de transmisión, enlaces de afiliado)
que aparecen en muchas descripciones pero no son contactos de un invitado. Se aplica en código
sobre lo que devuelve Claude, aunque el modelo también reciba la lista, para no depender de que
el modelo la respete. Ver `docs/PHASE3_PLAN.md` (adenda de contactos). Los valores de los
contactos no se escriben en los logs: solo cuántos se descartaron.
"""
import json
import logging
import re
from pathlib import Path

from app.schemas.claude_extraction import BatchExtraction, VideoExtraction

logger = logging.getLogger(__name__)

DEFAULT_IGNORED_PATH = Path(__file__).resolve().parents[1] / "config" / "ignored_contacts.json"
_SCHEME_WWW_RE = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)


class ContactFilterError(RuntimeError):
    """Lista de ignorados ilegible o mal formada; el mensaje indica módulo y función."""


def normalize_contact(value: str) -> str:
    """Minúsculas, sin espacios sobrantes, sin `http(s)://` ni `www.` al inicio."""
    return _SCHEME_WWW_RE.sub("", " ".join(value.split()).lower())


def load_ignored_patterns(path: Path = DEFAULT_IGNORED_PATH) -> list[str]:
    """Patrones normalizados y sin repetir, en el orden del archivo."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        patterns = data["patterns"]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise TypeError("'patterns' debe ser una lista de textos")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"[app.services.contact_filters.load_ignored_patterns] No se pudo leer {path}: {exc}"
        logger.error(msg)
        raise ContactFilterError(msg) from exc
    normalized = [normalize_contact(p) for p in patterns]
    return list(dict.fromkeys(p for p in normalized if p))


def is_ignored(value: str, patterns: list[str]) -> bool:
    """True si el valor contiene alguno de los patrones (ya normalizados)."""
    normalized = normalize_contact(value)
    return any(pattern in normalized for pattern in patterns)


def filter_video(video: VideoExtraction, patterns: list[str]) -> int:
    """Quita de `video` los contactos ignorados (asignados y sin asignar). Devuelve cuántos."""
    removed = 0
    for field in ("contacts", "unassigned_contacts"):
        kept = [c for c in getattr(video, field) if not is_ignored(c.value, patterns)]
        removed += len(getattr(video, field)) - len(kept)
        setattr(video, field, kept)
    return removed


def filter_batch(batch: BatchExtraction, patterns: list[str]) -> int:
    """Aplica `filter_video` a todo el lote. Devuelve cuántos contactos se descartaron."""
    removed = sum(filter_video(video, patterns) for video in batch.videos)
    if removed:
        logger.info("[app.services.contact_filters.filter_batch] %d contacto(s) ignorado(s) por la lista", removed)
    return removed
