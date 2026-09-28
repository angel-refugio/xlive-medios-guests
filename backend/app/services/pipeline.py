"""Fase 3, paso 6: orquestador idempotente (reglas de regex + LLM -> candidatos en staging).

`process_video` procesa un video a la vez: regex (paso 4) -> LLM (paso 5) -> filas en staging
(paso 2). `run_batch` lo aplica a un lote de videos nuevos del canal, sin detenerse si uno
falla (`IngestionRunError`) y sin reprocesar lo ya hecho (`Video.last_ingested_at`). Se dispara
a demanda desde la app o por script (todavía sin ninguno de los dos).

Todo lo que este módulo guarda en staging sigue siendo candidato: nada se vuelve invitado,
contacto o participación final sin pasar por Staging Review (paso 7, todavía sin implementar).
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalogs import Borough, GuestCategory, Host, Program, VideoType
from app.models.ingestion import (
    IngestionRun, IngestionRunError, StagingContactCandidate, StagingGuestCandidate,
)
from app.models.video import Video
from app.services import ollama_client, regex_rules
from app.services.catalogs import normalize_name
from app.services.ingestion import sync_videos
from app.services.youtube_client import YouTubeError, get_uploads_playlist_id, list_video_ids

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 30

# Duplicados reales: minutos a una semana de diferencia; episodios distintos de un programa
# recurrente con descripción idéntica: meses (evidencia real de 150 videos, ver
# docs/PHASE3_PLAN.md). 14 días separa ambos casos con margen.
DUPLICATE_MAX_TIMEDELTA = timedelta(days=14)

# Ajuste de confianza (regla del pipeline: título+descripción a favor, solo descripción
# neutro, ambigüedad persona/banda en contra). Valores iniciales, ajustables tras validar
# con resultados reales del modelo.
_CONFIDENCE_BOTH_BONUS = 0.15
_CONFIDENCE_TITLE_ONLY_BONUS = 0.10
_CONFIDENCE_GROUP_PENALTY = 0.20

# Confianza de los 3 patrones de nombre por formato (paso 4): "confianza baja/media" según
# PHASE3_PLAN.md; valores iniciales, ajustables igual que los de arriba.
_REGEX_NAME_CONFIDENCE = {"after_colon": 0.35, "con_nombre": 0.40, "uppercase_parens": 0.30}
# Los contactos por regex son patrones explícitos (URL, ETIQUETA:, correo), no ambiguos como
# los nombres por formato; confianza inicial más alta que la de esos 3 patrones.
_REGEX_CONTACT_CONFIDENCE = 0.7


def _adjust_confidence(
    raw: float, found_in_title: bool, found_in_description: bool, is_possible_group: bool
) -> float:
    adjustment = 0.0
    if found_in_title and found_in_description:
        adjustment += _CONFIDENCE_BOTH_BONUS
    elif found_in_title:
        adjustment += _CONFIDENCE_TITLE_ONLY_BONUS
    if is_possible_group:
        adjustment -= _CONFIDENCE_GROUP_PENALTY
    return max(0.0, min(1.0, raw + adjustment))


def _active_names(db: Session, model) -> list[str]:
    return list(db.scalars(select(model.name).where(model.is_active.is_(True))))


def _name_found_where(name: str, title: str, description: str | None) -> tuple[bool, bool]:
    normalized = normalize_name(name)
    return normalized in normalize_name(title), normalized in normalize_name(description or "")


def _find_possible_duplicate(db: Session, video: Video) -> Video | None:
    """Otro video con título+descripción normalizados iguales y published_at cercano."""
    if video.published_at is None:
        return None
    title_key = normalize_name(video.title)
    description_key = normalize_name(video.description or "")
    window_start = video.published_at - DUPLICATE_MAX_TIMEDELTA
    window_end = video.published_at + DUPLICATE_MAX_TIMEDELTA
    candidates = db.scalars(
        select(Video)
        .where(
            Video.id != video.id,
            Video.published_at.is_not(None),
            Video.published_at >= window_start,
            Video.published_at <= window_end,
        )
        .order_by(Video.published_at)
    )
    for other in candidates:
        if (
            normalize_name(other.title) == title_key
            and normalize_name(other.description or "") == description_key
        ):
            return other
    return None


def process_video(
    db: Session,
    ollama_http_client: httpx.Client,
    ollama_base_url: str,
    ollama_model: str,
    video: Video,
    ingestion_run: IngestionRun | None = None,
) -> None:
    """Analiza un video (regex + LLM) y guarda sus candidatos en staging. Hace commit.

    Idempotente: si el video ya se procesó (`last_ingested_at`), no hace nada.
    """
    if video.last_ingested_at is not None:
        logger.info(
            "[app.services.pipeline.process_video] Video %s ya procesado, se omite",
            video.youtube_video_id,
        )
        return

    run_id = ingestion_run.id if ingestion_run else None

    analysis = ollama_client.analyze_video(
        ollama_http_client, ollama_base_url, ollama_model, video.title, video.description,
        existing_categories=_active_names(db, GuestCategory),
        existing_video_types=_active_names(db, VideoType),
        existing_boroughs=_active_names(db, Borough),
        existing_hosts=_active_names(db, Host),
        existing_programs=_active_names(db, Program),
    )

    for name_match in regex_rules.extract_name_candidates(video.title, video.description):
        found_in_title, found_in_description = _name_found_where(
            name_match.name, video.title, video.description
        )
        raw = _REGEX_NAME_CONFIDENCE[name_match.pattern]
        db.add(StagingGuestCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            extracted_name=name_match.name, found_in_title=found_in_title,
            found_in_description=found_in_description, is_possible_group=False,
            raw_confidence=raw,
            adjusted_confidence=_adjust_confidence(raw, found_in_title, found_in_description, False),
            evidence=name_match.evidence, extraction_method="regex",
        ))

    for guest in analysis.guests:
        db.add(StagingGuestCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            extracted_name=guest.name, found_in_title=guest.found_in_title,
            found_in_description=guest.found_in_description,
            is_possible_group=guest.is_possible_group,
            category_match=guest.category_match,
            category_is_new_suggestion=guest.category_is_new_suggestion,
            raw_confidence=guest.raw_confidence,
            adjusted_confidence=_adjust_confidence(
                guest.raw_confidence, guest.found_in_title, guest.found_in_description,
                guest.is_possible_group,
            ),
            evidence=guest.evidence, extraction_method="llm",
        ))

    for contact in regex_rules.extract_contacts(video.description):
        db.add(StagingContactCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            type_hint=contact.type_hint, value=contact.value,
            raw_confidence=_REGEX_CONTACT_CONFIDENCE, extraction_method="regex",
        ))

    for contact in analysis.contacts:
        db.add(StagingContactCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            type_hint=contact.type_hint, value=contact.value,
            raw_confidence=contact.raw_confidence, extraction_method="llm",
        ))

    # "Sin invitados" (FR-014): candidato automático de la regla de regex (CLAUDE.md: "la IA lo
    # marca 'sin invitados', reclasificable por un humano"). La opinión del LLM no se persiste
    # aparte: es solo una señal adicional para Staging Review, no reemplaza esta regla.
    if regex_rules.is_no_guests_candidate(video.title, video.description):
        video.guest_status = "no_guests"

    duplicate = _find_possible_duplicate(db, video)
    if duplicate is not None:
        video.possible_duplicate_of_video_id = duplicate.id

    video.last_ingested_at = datetime.now(timezone.utc)
    db.commit()


def run_batch(
    db: Session,
    youtube_http_client: httpx.Client,
    youtube_api_key: str,
    ollama_http_client: httpx.Client,
    ollama_base_url: str,
    ollama_model: str,
    handle: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    trigger: str = "manual",
) -> IngestionRun:
    """Corre el pipeline completo sobre hasta `batch_size` videos nuevos del canal.

    No detiene el lote si un video falla: registra el error (`IngestionRunError`) y sigue con
    el siguiente. Nunca reprocesa un video que ya tenga `last_ingested_at`.
    """
    run = IngestionRun(trigger=trigger, requested_batch_size=batch_size)
    db.add(run)
    db.commit()

    try:
        playlist_id = get_uploads_playlist_id(youtube_http_client, youtube_api_key, handle)
        all_video_ids = list_video_ids(youtube_http_client, youtube_api_key, playlist_id)
    except YouTubeError as exc:
        return _fail_run(db, run, "(canal)", exc)

    already_ingested = set(db.scalars(
        select(Video.youtube_video_id).where(
            Video.youtube_video_id.in_(all_video_ids), Video.last_ingested_at.is_not(None)
        )
    ))
    pending_ids = [vid for vid in all_video_ids if vid not in already_ingested][:batch_size]

    if pending_ids:
        try:
            sync_videos(db, youtube_http_client, youtube_api_key, pending_ids)
        except YouTubeError as exc:
            return _fail_run(db, run, "(lote)", exc)

    videos = list(db.scalars(select(Video).where(Video.youtube_video_id.in_(pending_ids))))

    for video in videos:
        try:
            process_video(db, ollama_http_client, ollama_base_url, ollama_model, video, ingestion_run=run)
            run.success_count += 1
        except Exception as exc:  # noqa: BLE001 - resiliencia por video, a propósito (paso 6)
            db.rollback()
            db.add(IngestionRunError(
                ingestion_run_id=run.id, youtube_video_id=video.youtube_video_id,
                error_message=str(exc),
            ))
            run.error_count += 1
            logger.warning(
                "[app.services.pipeline.run_batch] Error en %s: %s",
                video.youtube_video_id, exc,
            )
        run.processed_count += 1
        db.commit()

    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run


def _fail_run(db: Session, run: IngestionRun, where: str, exc: Exception) -> IngestionRun:
    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    db.add(IngestionRunError(ingestion_run_id=run.id, youtube_video_id=where, error_message=str(exc)))
    db.commit()
    logger.error("[app.services.pipeline.run_batch] %s", exc)
    return run
