"""Extractor con Claude: armado de lotes, prompt, lectura de la salida y conteo de tokens.

Lógica común para Claude Code (`scripts/run_claude_pilot.py`) y, más adelante, la API. No llama a
ninguno de los dos ni toca la base de datos: así se prueba sin red. Las instrucciones viven en un
solo archivo (`app/prompts/extraction_instructions_v1.md`) y la salida se valida con
`app/schemas/claude_extraction.py`. Ver `docs/Propuesta_extracción_invitados_Claude.md`.
Todo resultado es candidato hasta la revisión humana.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.schemas.claude_extraction import BatchExtraction, VideoExtraction
from app.services import series_profile

logger = logging.getLogger(__name__)

# v1 = piloto sin catálogos (2026-10-07); v2 = con programas y conductores validados como contexto;
# v3 = v2 sin el ejemplo que contradecía la regla de "lo de después de los dos puntos es invitado".
INSTRUCTIONS_VERSIONS = ("v1", "v2", "v3")
INSTRUCTIONS_VERSION = "v3"
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
INSTRUCTIONS_PATH = PROMPTS_DIR / f"extraction_instructions_{INSTRUCTIONS_VERSION}.md"
DEFAULT_BATCH_SIZE = 15

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ClaudeExtractionError(RuntimeError):
    """Fallo al armar, ejecutar o leer una extracción; el mensaje indica módulo y función."""


def _fail(function: str, detail: str, cause: Exception | None = None) -> ClaudeExtractionError:
    msg = f"[app.services.claude_extraction.{function}] {detail}"
    logger.error(msg)
    error = ClaudeExtractionError(msg)
    error.__cause__ = cause
    return error


def load_instructions(path: Path | None = None, version: str = INSTRUCTIONS_VERSION) -> str:
    """Texto de las instrucciones (el mismo archivo para Claude Code y para la API)."""
    if path is None:
        if version not in INSTRUCTIONS_VERSIONS:
            raise _fail("load_instructions", f"Versión de instrucciones desconocida: {version!r}")
        path = PROMPTS_DIR / f"extraction_instructions_{version}.md"
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise _fail("load_instructions", f"No se pudo leer {path}: {exc}", exc) from exc


# --- lotes ---------------------------------------------------------------------------------

def build_batches(videos: dict[str, dict], max_size: int = DEFAULT_BATCH_SIZE) -> list[list[str]]:
    """Agrupa los IDs en lotes de una misma serie (hasta `max_size`); los videos sin serie
    reconocible se agrupan aparte. Orden estable: por serie y, dentro, por fecha de publicación."""
    if max_size < 1:
        raise _fail("build_batches", f"max_size debe ser >= 1 (llegó {max_size})")
    by_series: dict[str, list[str]] = {}
    for video_id, video in videos.items():
        key = series_profile.series_key(video["title"], "")
        by_series.setdefault(key, []).append(video_id)

    def published(video_id: str) -> str:
        return videos[video_id].get("published_at") or ""

    batches: list[list[str]] = []
    loose: list[str] = []
    for key in sorted(by_series, key=lambda k: (k == "", k)):
        ids = sorted(by_series[key], key=published)
        if key and len(ids) > 1:
            batches.extend(ids[i:i + max_size] for i in range(0, len(ids), max_size))
        else:
            loose.extend(ids)
    batches.extend(loose[i:i + max_size] for i in range(0, len(loose), max_size))
    return batches


def build_user_prompt(
    videos: dict[str, dict], batch: list[str], contact_types: list[str] | None = None,
    own_accounts: list[str] | None = None, known_programs: list[str] | None = None,
    known_hosts: list[str] | None = None,
) -> str:
    """Mensaje con el lote: los videos y, si existen, tipos de contacto, cuentas propias y los
    programas y conductores ya validados (contexto de las instrucciones v2)."""
    if not batch:
        raise _fail("build_user_prompt", "El lote está vacío")
    payload = {
        "contact_types": contact_types or [],
        "own_accounts": own_accounts or [],
        "known_programs": known_programs or [],
        "known_hosts": known_hosts or [],
        "videos": [
            {
                "video_id": video_id,
                "title": videos[video_id]["title"],
                "description": videos[video_id].get("description") or "",
                "published_at": videos[video_id].get("published_at"),
            }
            for video_id in batch
        ],
    }
    return (
        "Extrae los datos de este lote siguiendo tus instrucciones. Responde solo con el JSON.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )


# --- salida --------------------------------------------------------------------------------

def extract_json_text(text: str) -> str:
    """Quita bloques de código y texto alrededor: del primer '{' al último '}'."""
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise _fail("extract_json_text", "La respuesta no contiene un objeto JSON")
    return cleaned[start:end + 1]


def parse_batch_output(text: str, expected_ids: list[str]) -> BatchExtraction:
    """Valida la respuesta contra el esquema y exige un resultado por video del lote."""
    try:
        batch = BatchExtraction.model_validate(json.loads(extract_json_text(text)))
    except (ValueError, ValidationError) as exc:
        raise _fail("parse_batch_output", f"JSON inválido o fuera del esquema: {exc}", exc) from exc
    got = [v.video_id for v in batch.videos]
    missing = [i for i in expected_ids if i not in got]
    unexpected = sorted(set(got) - set(expected_ids))
    if missing or unexpected:
        raise _fail(
            "parse_batch_output",
            f"El lote no coincide: faltan {missing or 'ninguno'}; sobran {unexpected or 'ninguno'}",
        )
    return batch


def to_eval_entry(video: VideoExtraction) -> dict:
    """Entrada de caché para `scripts/eval_extraction.py` (invitados, conductores y programa)."""
    return {
        "guests": [g.name for g in video.guests],
        "hosts": [h.name for h in video.hosts],
        "program": video.program or "",
    }


def count_contacts(video: VideoExtraction) -> tuple[int, int]:
    """(contactos asignados, contactos sin asignar); solo cuenta, no expone valores."""
    return len(video.contacts), len(video.unassigned_contacts)


# --- tokens y costo ------------------------------------------------------------------------

@dataclass
class Usage:
    """Tokens de una o varias llamadas, tal como los reporta `claude -p --output-format json`."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reported_cost_usd: float = 0.0
    calls: int = 0
    # Modelos que respondieron (`modelUsage` de la respuesta), p. ej. ["claude-sonnet-5-5"].
    models: list[str] = field(default_factory=list)

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.reported_cost_usd += other.reported_cost_usd
        self.calls += other.calls
        self.models = sorted({*self.models, *other.models})

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    def estimated_api_cost_usd(self, price_in_per_mtok: float, price_out_per_mtok: float) -> float:
        """Costo equivalente en API: TODOS los tokens de entrada (también los de caché) al precio
        de entrada, a propósito, para que la estimación quede al alza."""
        return (
            self.total_input_tokens * price_in_per_mtok + self.output_tokens * price_out_per_mtok
        ) / 1_000_000


def parse_cli_envelope(stdout: str) -> tuple[str, Usage]:
    """Texto de la respuesta y tokens a partir del JSON que imprime `claude -p`."""
    try:
        envelope = json.loads(stdout)
    except ValueError as exc:
        raise _fail("parse_cli_envelope", f"La salida de claude no es JSON: {exc}", exc) from exc
    if not isinstance(envelope, dict):
        raise _fail("parse_cli_envelope", "La salida de claude no es un objeto JSON")
    if envelope.get("is_error"):
        raise _fail("parse_cli_envelope", f"claude reportó un error: {str(envelope.get('result'))[:300]}")
    result = envelope.get("result")
    if not isinstance(result, str):
        raise _fail("parse_cli_envelope", "La salida de claude no trae 'result' de texto")
    raw = envelope.get("usage") or {}
    usage = Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cache_creation_tokens=int(raw.get("cache_creation_input_tokens") or 0),
        cache_read_tokens=int(raw.get("cache_read_input_tokens") or 0),
        reported_cost_usd=float(envelope.get("total_cost_usd") or 0.0),
        calls=1,
        models=sorted(envelope.get("modelUsage") or {}),
    )
    return result, usage
