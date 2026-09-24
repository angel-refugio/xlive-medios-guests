"""Endpoints de participaciones: por invitado (CRUD) y por video (consulta)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.participations import (
    ParticipationCreate,
    ParticipationOut,
    ParticipationUpdate,
)
from app.services import participations as service
from app.services.guests import GuestNotFoundError, InvalidReferenceError
from app.services.videos import VideoNotFoundError

guest_router = APIRouter(
    prefix="/guests/{guest_id}/participations",
    tags=["participations"],
    dependencies=[Depends(require_admin)],
)
video_router = APIRouter(
    prefix="/videos/{video_id}/participations",
    tags=["participations"],
    dependencies=[Depends(require_admin)],
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (GuestNotFoundError, VideoNotFoundError, service.ParticipationNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.ParticipationDuplicateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@guest_router.get("", response_model=list[ParticipationOut])
def list_by_guest(guest_id: int, db: Session = Depends(get_db)):
    try:
        return service.list_by_guest(db, guest_id)
    except GuestNotFoundError as exc:
        raise _http_error(exc)


@guest_router.post("", response_model=ParticipationOut, status_code=201)
def create_participation(guest_id: int, data: ParticipationCreate, db: Session = Depends(get_db)):
    try:
        return service.create_participation(db, guest_id, data)
    except (GuestNotFoundError, InvalidReferenceError, service.ParticipationDuplicateError) as exc:
        raise _http_error(exc)


@guest_router.get("/{participation_id}", response_model=ParticipationOut)
def get_participation(guest_id: int, participation_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_participation(db, guest_id, participation_id)
    except (GuestNotFoundError, service.ParticipationNotFoundError) as exc:
        raise _http_error(exc)


@guest_router.patch("/{participation_id}", response_model=ParticipationOut)
def update_participation(
    guest_id: int,
    participation_id: int,
    data: ParticipationUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_participation(db, guest_id, participation_id, data)
    except (GuestNotFoundError, service.ParticipationNotFoundError) as exc:
        raise _http_error(exc)


@guest_router.delete("/{participation_id}", status_code=204)
def delete_participation(
    guest_id: int, participation_id: int, confirm: bool = False, db: Session = Depends(get_db)
):
    """Quita al invitado de ese video. Exige `?confirm=true`."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Borrar una participación es definitivo; envía confirm=true para confirmar",
        )
    try:
        service.delete_participation(db, guest_id, participation_id)
    except (GuestNotFoundError, service.ParticipationNotFoundError) as exc:
        raise _http_error(exc)


@video_router.get("", response_model=list[ParticipationOut])
def list_by_video(video_id: int, db: Session = Depends(get_db)):
    try:
        return service.list_by_video(db, video_id)
    except VideoNotFoundError as exc:
        raise _http_error(exc)
