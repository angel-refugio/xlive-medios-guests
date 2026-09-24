"""Lógica de videos cargados a mano: CRUD con referencias a catálogos y filtro por origen."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.catalogs import Borough, Program, VideoType
from app.models.video import Video
from app.schemas.videos import VideoCreate, VideoUpdate
from app.services.guests import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, InvalidReferenceError

logger = logging.getLogger(__name__)

# (campo, modelo, etiqueta para el mensaje de error)
_CATALOG_FIELDS = (
    ("video_type_id", VideoType, "El tipo de video"),
    ("program_id", Program, "El programa"),
    ("event_borough_id", Borough, "La alcaldía del evento"),
)


class VideoNotFoundError(LookupError):
    pass


class VideoDuplicateError(ValueError):
    pass


def _check_catalog(db: Session, model, item_id: int, current_id: int | None, label: str) -> None:
    item = db.get(model, item_id)
    if item is None or (not item.is_active and item_id != current_id):
        msg = f"{label} {item_id} no existe o está desactivado"
        logger.warning("[app.services.videos._check_catalog] %s", msg)
        raise InvalidReferenceError(msg)


def _check_part_of(db: Session, part_of_id: int, video_id: int | None) -> None:
    if video_id is not None and part_of_id == video_id:
        msg = "Un video no puede ser parte de sí mismo"
        logger.warning("[app.services.videos._check_part_of] %s", msg)
        raise InvalidReferenceError(msg)
    if db.get(Video, part_of_id) is None:
        msg = f"El video original {part_of_id} no existe"
        logger.warning("[app.services.videos._check_part_of] %s", msg)
        raise InvalidReferenceError(msg)


def _ensure_unique_youtube_id(db: Session, youtube_id: str, exclude_id: int | None = None) -> None:
    stmt = select(Video.id).where(Video.youtube_video_id == youtube_id)
    if exclude_id is not None:
        stmt = stmt.where(Video.id != exclude_id)
    if db.execute(stmt).first() is not None:
        msg = f"Ya existe un video con el id de YouTube {youtube_id!r}"
        logger.warning("[app.services.videos._ensure_unique_youtube_id] %s", msg)
        raise VideoDuplicateError(msg)


def list_videos(
    db: Session, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, source: str | None = None
) -> tuple[list[Video], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    filters = [Video.source == source] if source else []
    total = db.execute(select(func.count(Video.id)).where(*filters)).scalar_one()
    stmt = (
        select(Video)
        .where(*filters)
        .options(
            selectinload(Video.video_type),
            selectinload(Video.program),
            selectinload(Video.event_borough),
        )
        # Más recientes primero; los que no tienen fecha, al final.
        .order_by(Video.published_at.is_(None), Video.published_at.desc(), Video.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(db.execute(stmt).scalars()), total


def get_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        msg = f"No existe el video {video_id}"
        logger.warning("[app.services.videos.get_video] %s", msg)
        raise VideoNotFoundError(msg)
    return video


def create_video(db: Session, data: VideoCreate) -> Video:
    _ensure_unique_youtube_id(db, data.youtube_video_id)
    for field, model, label in _CATALOG_FIELDS:
        value = getattr(data, field)
        if value is not None:
            _check_catalog(db, model, value, None, label)
    if data.part_of_video_id is not None:
        _check_part_of(db, data.part_of_video_id, None)

    video = Video(**data.model_dump(), source="manual")
    try:
        db.add(video)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return video


def update_video(db: Session, video_id: int, data: VideoUpdate) -> Video:
    video = get_video(db, video_id)
    sent = data.model_fields_set
    try:
        for required in ("youtube_video_id", "title", "guest_status"):
            if required in sent and getattr(data, required) is None:
                raise InvalidReferenceError(f"El campo {required} no puede ser null")
        if "youtube_video_id" in sent and data.youtube_video_id != video.youtube_video_id:
            _ensure_unique_youtube_id(db, data.youtube_video_id, exclude_id=video.id)
        for field, model, label in _CATALOG_FIELDS:
            value = getattr(data, field)
            if field in sent and value is not None:
                _check_catalog(db, model, value, getattr(video, field), label)
        if "part_of_video_id" in sent and data.part_of_video_id is not None:
            _check_part_of(db, data.part_of_video_id, video.id)

        for field in sent:
            setattr(video, field, getattr(data, field))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return video


def delete_video(db: Session, video_id: int) -> None:
    """Borra el video; sus participaciones se borran en cascada y las partes quedan sueltas."""
    video = get_video(db, video_id)
    db.delete(video)
    db.commit()
    logger.info("[app.services.videos.delete_video] Video %s eliminado", video_id)
