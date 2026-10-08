"""Importador a staging de lo que extrae Claude, venga de Claude Code o de la API.

Es el único punto de entrada de los resultados de Claude a la base de datos: ni el Staging Review
ni las tablas finales distinguen de dónde vino el resultado. Recibe objetos `VideoExtraction`
(`app/schemas/claude_extraction.py`) ya validados, con los contactos ya resueltos
(`contact_candidates.resolve_contacts` en v5), y los guarda como CANDIDATOS: nada llega a
`guests`, `contacts` ni `participations` sin revisión humana.

- Claude Code: `scripts/import_claude_results.py` lee los archivos que dejó `run_claude_pilot`.
- API: el extractor por API entregará el mismo `BatchExtraction` a `import_batch`.

Reglas:
- Idempotente: reimportar un video reemplaza sus candidatos PENDIENTES; lo ya aceptado o
  rechazado se conserva y no se vuelve a proponer (los rechazados se recuerdan).
- El programa solo se asigna si existe en el catálogo; si no, queda como programa propuesto
  (`new_program_name`) para que el humano decida si lo crea.
- Cada candidato guarda el origen (`extractor`) y la versión de las instrucciones.
- Los valores de los contactos no se escriben en los logs, solo conteos.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.catalogs import ContactType, Program
from app.models.contact import normalize_contact_value
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion
from app.models.video import Video
from app.schemas.claude_extraction import BatchExtraction, ContactCandidate, VideoExtraction
from app.services import claude_extraction, ingestion, series_profile
from app.services.catalogs import normalize_name
from app.services.pipeline import _adjust_confidence, _name_found_where

logger = logging.getLogger(__name__)

EXTRACTORS = ("claude_code", "claude_api")
# Los contactos salen de la regex (patrones explícitos): misma confianza inicial que en el pipeline.
_CONTACT_CONFIDENCE = 0.7
_CONTACT_TYPE_SYNONYMS = {
    "email": {"correo", "email", "e-mail", "correo electronico"},
    "telefono": {"telefono", "celular", "movil", "whatsapp"},
    "url": {"web", "pagina web", "sitio web", "sitio"},
}


class ClaudeImportError(RuntimeError):
    """Fallo al importar; el mensaje indica módulo y función (nunca valores de contactos)."""


@dataclass
class VideoImport:
    """Qué hizo la importación de un video (solo conteos)."""

    guests: int = 0
    contacts: int = 0
    doubtful_contacts: int = 0
    unassigned_contacts: int = 0
    skipped_reviewed: int = 0
    replaced_pending: int = 0
    suggestion: bool = False


@dataclass
class BatchImport:
    videos: int = 0
    guests: int = 0
    contacts: int = 0
    doubtful_contacts: int = 0
    unassigned_contacts: int = 0
    skipped_reviewed: int = 0
    replaced_pending: int = 0
    suggestions: int = 0
    created_videos: int = 0
    missing_videos: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def add(self, one: VideoImport) -> None:
        self.videos += 1
        self.guests += one.guests
        self.contacts += one.contacts
        self.doubtful_contacts += one.doubtful_contacts
        self.unassigned_contacts += one.unassigned_contacts
        self.skipped_reviewed += one.skipped_reviewed
        self.replaced_pending += one.replaced_pending
        self.suggestions += int(one.suggestion)


def _fail(function: str, detail: str, cause: Exception | None = None) -> ClaudeImportError:
    msg = f"[app.services.claude_import.{function}] {detail}"
    logger.error(msg)
    error = ClaudeImportError(msg)
    error.__cause__ = cause
    return error


def type_is_registered(type_hint: str, registered_names: list[str]) -> bool:
    """El tipo del contacto coincide con un tipo activo del catálogo (o con un sinónimo habitual:
    "email" ~ "Correo", "telefono" ~ "Celular", "url" ~ "Web"). Un `handle` (red sin determinar)
    nunca coincide: el administrador decide la red al revisarlo."""
    hint = normalize_name(type_hint)
    registered = {normalize_name(n) for n in registered_names}
    return hint in registered or bool(_CONTACT_TYPE_SYNONYMS.get(hint, set()) & registered)


def _contact_flags(
    contact: ContactCandidate, guest_candidate_id: int | None, registered_types: list[str],
) -> tuple[bool, str | None]:
    """(dudoso, motivo): conserva lo que dijo Claude y suma "tipo no registrado" e "invitado sin
    candidato" cuando corresponde."""
    reasons = [contact.doubtful_reason] if contact.doubtful and contact.doubtful_reason else []
    if not type_is_registered(contact.type, registered_types):
        reasons.append("tipo no registrado")
    if contact.guest and guest_candidate_id is None:
        reasons.append("invitado sin candidato")
    doubtful = contact.doubtful or bool(reasons)
    return doubtful, ("; ".join(dict.fromkeys(reasons)) or None)


def _delete_pending(db: Session, video_id: int) -> int:
    """Borra los candidatos PENDIENTES del video (se regeneran); conserva aceptados y rechazados."""
    removed = 0
    for model in (StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion):
        removed += db.execute(
            delete(model).where(model.video_id == video_id, model.status == "pending")
        ).rowcount or 0
    return removed


def _reviewed_keys(db: Session, video_id: int) -> tuple[set[str], set[str]]:
    guests = {
        series_profile.compact(name) for name in db.scalars(
            select(StagingGuestCandidate.extracted_name).where(
                StagingGuestCandidate.video_id == video_id, StagingGuestCandidate.status != "pending")
        )
    }
    contacts = {
        key for key in db.scalars(
            select(StagingContactCandidate.normalized_value).where(
                StagingContactCandidate.video_id == video_id, StagingContactCandidate.status != "pending")
        ) if key
    }
    return guests, contacts


def _build_suggestion(
    db: Session, video: Video, extraction: VideoExtraction, run_id: int | None,
    extractor: str, instructions_version: str,
) -> StagingVideoSuggestion | None:
    program_name = new_program = None
    if extraction.program:
        by_key = {normalize_name(n): n for n in db.scalars(select(Program.name).where(Program.is_active.is_(True)))}
        program_name = by_key.get(normalize_name(extraction.program))
        new_program = None if program_name else extraction.program
    host_names = list(dict.fromkeys(h.name for h in extraction.hosts))
    doubtful = [{"name": d.name, "guess": "unknown", "reason": d.reason} for d in extraction.doubtful]
    if not (program_name or new_program or host_names or doubtful):
        return None
    return StagingVideoSuggestion(
        video_id=video.id, ingestion_run_id=run_id, program_name=program_name, new_program_name=new_program,
        host_names=host_names, doubtful_names=doubtful, usual_host_names=[],
        extractor=extractor, instructions_version=instructions_version,
    )


def import_video(
    db: Session, video: Video, extraction: VideoExtraction, *, extractor: str,
    instructions_version: str, run_id: int | None = None,
) -> VideoImport:
    """Guarda lo que Claude extrajo de un video como candidatos. No hace commit."""
    if extractor not in EXTRACTORS:
        raise _fail("import_video", f"extractor desconocido {extractor!r}; usa uno de {EXTRACTORS}")
    result = VideoImport(replaced_pending=_delete_pending(db, video.id))
    db.flush()
    reviewed_guests, reviewed_contacts = _reviewed_keys(db, video.id)
    origin = {"extractor": extractor, "instructions_version": instructions_version}

    guest_ids: dict[str, int] = {}
    for guest in extraction.guests:
        key = series_profile.compact(guest.name)
        if key in guest_ids:
            continue
        if key in reviewed_guests:
            result.skipped_reviewed += 1
            continue
        found_title, found_description = _name_found_where(guest.name, video.title, video.description)
        candidate = StagingGuestCandidate(
            video_id=video.id, ingestion_run_id=run_id, extracted_name=guest.name,
            found_in_title=found_title, found_in_description=found_description, is_possible_group=False,
            raw_confidence=guest.confidence,
            adjusted_confidence=_adjust_confidence(guest.confidence, found_title, found_description, False),
            evidence=guest.evidence or guest.name, extraction_method="llm", **origin,
        )
        db.add(candidate)
        db.flush()
        guest_ids[key] = candidate.id
        result.guests += 1

    registered_types = list(db.scalars(select(ContactType.name).where(ContactType.is_active.is_(True))))
    method = "regex" if instructions_version in claude_extraction.REGEX_CONTACT_VERSIONS else "llm"
    seen_contacts: set[str] = set()
    for contact in [*extraction.contacts, *extraction.unassigned_contacts]:
        normalized = normalize_contact_value(contact.value)
        if normalized in seen_contacts:
            continue
        seen_contacts.add(normalized)
        if normalized in reviewed_contacts:      # aceptado o rechazado antes: no se vuelve a proponer
            result.skipped_reviewed += 1
            continue
        guest_candidate_id = guest_ids.get(series_profile.compact(contact.guest)) if contact.guest else None
        doubtful, reason = _contact_flags(contact, guest_candidate_id, registered_types)
        db.add(StagingContactCandidate(
            video_id=video.id, ingestion_run_id=run_id, guest_candidate_id=guest_candidate_id,
            type_hint=contact.type, value=contact.value, normalized_value=normalized,
            raw_confidence=_CONTACT_CONFIDENCE, extraction_method=method,
            relationship_name=contact.relationship, evidence=contact.evidence or None,
            doubtful=doubtful, doubtful_reason=reason, guest_name=contact.guest,
            possible_guest_name=contact.possible_guest, **origin,
        ))
        result.contacts += 1
        result.doubtful_contacts += int(doubtful)
        result.unassigned_contacts += int(guest_candidate_id is None)

    already = db.scalar(select(StagingVideoSuggestion.id).where(StagingVideoSuggestion.video_id == video.id))
    if already is None:
        suggestion = _build_suggestion(db, video, extraction, run_id, extractor, instructions_version)
        if suggestion is not None:
            db.add(suggestion)
            result.suggestion = True

    if extraction.no_guests and not extraction.guests and video.guest_status == "pending":
        video.guest_status = "no_guests"
    if video.last_ingested_at is None:
        video.last_ingested_at = datetime.now(timezone.utc)
    db.flush()
    return result


def import_batch(
    db: Session, batch: BatchExtraction, *, extractor: str, instructions_version: str | None = None,
    video_metadata: dict[str, dict] | None = None, create_missing: bool = False, commit: bool = True,
) -> BatchImport:
    """Importa todos los videos del lote. Un video con error no detiene al resto (se registra).

    `video_metadata` ({youtube_video_id: metadatos como los de la API de YouTube}) permite crear
    los videos que todavía no están en la BD si `create_missing=True`; si no, se reportan como
    faltantes (primero hay que sincronizar el canal). Con `commit=False` solo se simula.
    """
    summary = BatchImport()
    version = instructions_version or batch.instructions_version
    for extraction in batch.videos:
        youtube_id = extraction.video_id
        try:
            video = db.scalar(select(Video).where(Video.youtube_video_id == youtube_id))
            if video is None:
                if not (create_missing and video_metadata and youtube_id in video_metadata):
                    summary.missing_videos.append(youtube_id)
                    continue
                video = ingestion.upsert_video(db, video_metadata[youtube_id]).video
                db.flush()
                summary.created_videos += 1
            summary.add(import_video(db, video, extraction, extractor=extractor, instructions_version=version))
            if commit:
                db.commit()
        except Exception as exc:  # noqa: BLE001 - un video con error no detiene el lote
            db.rollback()
            logger.error("[app.services.claude_import.import_batch] Video %s falló: %s", youtube_id, exc)
            summary.errors.append((youtube_id, str(exc)))
    if not commit:
        db.rollback()
    return summary


def load_claude_code_results(pilot_dir: Path) -> BatchExtraction:
    """Junta los lotes que dejó `run_claude_pilot` (modo Claude Code) en un solo `BatchExtraction`.

    Si un video aparece en varios archivos (corridas repetidas), gana el archivo más reciente.
    La versión de las instrucciones debe ser la misma en todos los archivos.
    """
    files = sorted(Path(pilot_dir).glob("batch_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise _fail("load_claude_code_results", f"No hay lotes en {pilot_dir}")
    videos: dict[str, VideoExtraction] = {}
    versions: set[str] = set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            versions.add(data["instructions_version"])
            for raw in data["result"]["videos"]:
                video = VideoExtraction.model_validate(raw)
                videos[video.video_id] = video
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _fail("load_claude_code_results", f"Lote ilegible {path.name}: {exc}", exc) from exc
    if len(versions) != 1:
        raise _fail("load_claude_code_results", f"La carpeta mezcla versiones de instrucciones: {sorted(versions)}")
    return BatchExtraction(instructions_version=versions.pop(), videos=list(videos.values()))
