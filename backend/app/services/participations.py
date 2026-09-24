"""Lógica de participaciones: vínculo invitado ↔ video (único por par)."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.participation import Participation
from app.models.video import Video
from app.schemas.participations import ParticipationCreate, ParticipationUpdate
from app.services.guests import InvalidReferenceError, get_guest
from app.services.videos import get_video

logger = logging.getLogger(__name__)


class ParticipationNotFoundError(LookupError):
    pass


class ParticipationDuplicateError(ValueError):
    pass


def _with_relations():
    return (selectinload(Participation.guest), selectinload(Participation.video))


def list_by_guest(db: Session, guest_id: int) -> list[Participation]:
    get_guest(db, guest_id)  # 404 si no existe
    stmt = (
        select(Participation)
        .join(Video, Participation.video_id == Video.id)
        .where(Participation.guest_id == guest_id)
        .options(*_with_relations())
        .order_by(Video.published_at.is_(None), Video.published_at.desc(), Participation.id)
    )
    return list(db.execute(stmt).scalars())


def list_by_video(db: Session, video_id: int) -> list[Participation]:
    get_video(db, video_id)  # 404 si no existe
    stmt = (
        select(Participation)
        .where(Participation.video_id == video_id)
        .options(*_with_relations())
        .order_by(Participation.id)
    )
    return list(db.execute(stmt).scalars())


def get_participation(db: Session, guest_id: int, participation_id: int) -> Participation:
    get_guest(db, guest_id)
    participation = db.get(Participation, participation_id)
    # Una participación de otro invitado se trata como inexistente en esta ruta.
    if participation is None or participation.guest_id != guest_id:
        msg = f"No existe la participación {participation_id} del invitado {guest_id}"
        logger.warning("[app.services.participations.get_participation] %s", msg)
        raise ParticipationNotFoundError(msg)
    return participation


def create_participation(db: Session, guest_id: int, data: ParticipationCreate) -> Participation:
    get_guest(db, guest_id)
    if db.get(Video, data.video_id) is None:
        msg = f"El video {data.video_id} no existe"
        logger.warning("[app.services.participations.create_participation] %s", msg)
        raise InvalidReferenceError(msg)
    already = db.execute(
        select(func.count(Participation.id)).where(
            Participation.guest_id == guest_id, Participation.video_id == data.video_id
        )
    ).scalar_one()
    if already:
        msg = f"El invitado {guest_id} ya participa en el video {data.video_id}"
        logger.warning("[app.services.participations.create_participation] %s", msg)
        raise ParticipationDuplicateError(msg)

    participation = Participation(guest_id=guest_id, video_id=data.video_id, notes=data.notes)
    try:
        db.add(participation)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return participation


def update_participation(
    db: Session, guest_id: int, participation_id: int, data: ParticipationUpdate
) -> Participation:
    participation = get_participation(db, guest_id, participation_id)
    if "notes" in data.model_fields_set:
        participation.notes = data.notes
    db.commit()
    return participation


def delete_participation(db: Session, guest_id: int, participation_id: int) -> None:
    participation = get_participation(db, guest_id, participation_id)
    db.delete(participation)
    db.commit()
    logger.info(
        "[app.services.participations.delete_participation] Participación %s eliminada",
        participation_id,
    )
