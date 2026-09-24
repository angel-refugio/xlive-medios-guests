"""Endpoints CRUD de invitados (protegidos con require_admin)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.guests import GuestCreate, GuestOut, GuestPage, GuestUpdate
from app.services import guests as service

router = APIRouter(prefix="/guests", tags=["guests"], dependencies=[Depends(require_admin)])


@router.get("", response_model=GuestPage)
def list_guests(
    page: int = Query(1, ge=1),
    page_size: int = Query(service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    items, total = service.list_guests(db, page, page_size)
    return GuestPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=GuestOut, status_code=201)
def create_guest(data: GuestCreate, db: Session = Depends(get_db)):
    try:
        return service.create_guest(db, data)
    except service.InvalidReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{guest_id}", response_model=GuestOut)
def get_guest(guest_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_guest(db, guest_id)
    except service.GuestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{guest_id}", response_model=GuestOut)
def update_guest(guest_id: int, data: GuestUpdate, db: Session = Depends(get_db)):
    try:
        return service.update_guest(db, guest_id, data)
    except service.GuestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.InvalidReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{guest_id}", status_code=204)
def delete_guest(guest_id: int, confirm: bool = False, db: Session = Depends(get_db)):
    """Borra el invitado con sus contactos y participaciones. Exige `?confirm=true`."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Borrar un invitado elimina también sus contactos y participaciones; "
            "envía confirm=true para confirmar",
        )
    try:
        service.delete_guest(db, guest_id)
    except service.GuestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
