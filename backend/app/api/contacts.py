"""Endpoints de contactos, anidados bajo /guests/{guest_id}/contacts."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.contacts import ContactCreate, ContactOut, ContactUpdate
from app.services import contacts as service
from app.services.guests import GuestNotFoundError, InvalidReferenceError

router = APIRouter(
    prefix="/guests/{guest_id}/contacts",
    tags=["contacts"],
    dependencies=[Depends(require_admin)],
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (GuestNotFoundError, service.ContactNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=list[ContactOut])
def list_contacts(guest_id: int, db: Session = Depends(get_db)):
    try:
        return service.list_contacts(db, guest_id)
    except GuestNotFoundError as exc:
        raise _http_error(exc)


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(guest_id: int, data: ContactCreate, db: Session = Depends(get_db)):
    try:
        return service.create_contact(db, guest_id, data)
    except (GuestNotFoundError, InvalidReferenceError) as exc:
        raise _http_error(exc)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(guest_id: int, contact_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_contact(db, guest_id, contact_id)
    except (GuestNotFoundError, service.ContactNotFoundError) as exc:
        raise _http_error(exc)


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    guest_id: int, contact_id: int, data: ContactUpdate, db: Session = Depends(get_db)
):
    try:
        return service.update_contact(db, guest_id, contact_id, data)
    except (GuestNotFoundError, service.ContactNotFoundError, InvalidReferenceError) as exc:
        raise _http_error(exc)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    guest_id: int, contact_id: int, confirm: bool = False, db: Session = Depends(get_db)
):
    """Borra el contacto. Exige `?confirm=true`."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Borrar un contacto es definitivo; envía confirm=true para confirmar",
        )
    try:
        service.delete_contact(db, guest_id, contact_id)
    except (GuestNotFoundError, service.ContactNotFoundError) as exc:
        raise _http_error(exc)
