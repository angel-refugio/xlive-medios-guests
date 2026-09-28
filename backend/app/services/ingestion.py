"""Fase 3, paso 3: guarda los videos del canal de YouTube en `videos` sin duplicar.

Solo sincroniza metadatos crudos (source='youtube'); no crea invitados, contactos ni
participaciones — eso decide un humano en Staging Review (pasos 4-7, todavía sin implementar).
Idempotente por `youtube_video_id`: reprocesar actualiza en lugar de duplicar.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.video import Video
from app.services import youtube_client

logger = logging.getLogger(__name__)


@dataclass
class VideoSyncResult:
    video: Video
    created: bool
    # True si el video ya existía como 'manual' y este sync lo reemplazó por el real
    # (regla acordada con el usuario: el real gana prioridad total, ver PHASE3_PLAN.md).
    replaced_manual: bool


def _parse_timestamp(value: str | None) -> datetime | None:
    """'2024-01-01T00:00:00Z' (formato de la API) -> datetime con zona horaria."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        msg = f"[app.services.ingestion._parse_timestamp] Fecha no reconocida: {value!r}"
        logger.error(msg)
        raise ValueError(msg) from exc


def _video_fields(raw: dict) -> dict:
    """Convierte un dict de youtube_client.get_video_details a los campos de Video.

    Solo metadatos crudos: el resto de Video (catálogos, guest_status, part_of_video_id,
    possible_duplicate_of_video_id) lo decide Staging Review o el usuario, nunca este sync.
    """
    return {
        "title": raw["title"],
        "description": raw.get("description") or None,
        "published_at": _parse_timestamp(raw.get("published_at")),
        "channel_id": raw.get("channel_id"),
        "channel_title": raw.get("channel_title"),
        "thumbnail_url": raw.get("thumbnail_url"),
        "duration_seconds": youtube_client.parse_duration(raw.get("duration")),
    }


def upsert_video(db: Session, raw: dict) -> VideoSyncResult:
    """Crea o actualiza el `Video` correspondiente a un video de YouTube. No hace commit."""
    youtube_id = raw["id"]
    video = db.execute(
        select(Video).where(Video.youtube_video_id == youtube_id)
    ).scalar_one_or_none()
    fields = _video_fields(raw)

    if video is None:
        video = Video(youtube_video_id=youtube_id, source="youtube", **fields)
        db.add(video)
        logger.info("[app.services.ingestion.upsert_video] Nuevo video %s", youtube_id)
        return VideoSyncResult(video, created=True, replaced_manual=False)

    replaced_manual = video.source == "manual"
    for field, value in fields.items():
        setattr(video, field, value)
    video.source = "youtube"
    if replaced_manual:
        logger.info(
            "[app.services.ingestion.upsert_video] Video manual %s reemplazado por el real",
            youtube_id,
        )
    return VideoSyncResult(video, created=False, replaced_manual=replaced_manual)


def sync_videos(
    db: Session, client: httpx.Client, api_key: str, video_ids: list[str]
) -> list[VideoSyncResult]:
    """Trae de YouTube los videos pedidos y los guarda/actualiza en `videos`.

    Un solo commit al final: si algo falla, no queda un lote a medias. El manejo de errores
    por video (para no detener el resto del lote) es del orquestador (paso 6).
    """
    raw_videos = youtube_client.get_video_details(client, api_key, video_ids)
    results = [upsert_video(db, raw) for raw in raw_videos]
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return results


def sync_channel(
    db: Session, client: httpx.Client, api_key: str, handle: str
) -> list[VideoSyncResult]:
    """Trae y guarda todos los videos subidos del canal identificado por su @handle."""
    playlist_id = youtube_client.get_uploads_playlist_id(client, api_key, handle)
    video_ids = youtube_client.list_video_ids(client, api_key, playlist_id)
    return sync_videos(db, client, api_key, video_ids)
