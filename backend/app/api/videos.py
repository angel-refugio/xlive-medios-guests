"""Endpoints CRUD de videos cargados a mano (protegidos con require_admin)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.videos import VideoCreate, VideoOut, VideoPage, VideoSource, VideoUpdate
from app.services import videos as service
from app.services.guests import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, InvalidReferenceError

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Depends(require_admin)])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.VideoNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.VideoDuplicateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=VideoPage)
def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    source: VideoSource | None = None,
    db: Session = Depends(get_db),
):
    items, total = service.list_videos(db, page, page_size, source)
    return VideoPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=VideoOut, status_code=201)
def create_video(data: VideoCreate, db: Session = Depends(get_db)):
    try:
        return service.create_video(db, data)
    except (service.VideoDuplicateError, InvalidReferenceError) as exc:
        raise _http_error(exc)


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_video(db, video_id)
    except service.VideoNotFoundError as exc:
        raise _http_error(exc)


@router.patch("/{video_id}", response_model=VideoOut)
def update_video(video_id: int, data: VideoUpdate, db: Session = Depends(get_db)):
    try:
        return service.update_video(db, video_id, data)
    except (service.VideoNotFoundError, service.VideoDuplicateError, InvalidReferenceError) as exc:
        raise _http_error(exc)


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, confirm: bool = False, db: Session = Depends(get_db)):
    """Borra el video y sus participaciones (los invitados no). Exige `?confirm=true`."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Borrar un video elimina también sus participaciones; "
            "envía confirm=true para confirmar",
        )
    try:
        service.delete_video(db, video_id)
    except service.VideoNotFoundError as exc:
        raise _http_error(exc)
