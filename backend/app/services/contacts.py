"""Lógica de contactos: CRUD anidado bajo un invitado."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.catalogs import ContactType
from app.models.contact import Contact
from app.schemas.contacts import ContactCreate, ContactUpdate
from app.services.guests import InvalidReferenceError, get_guest

logger = logging.getLogger(__name__)


class ContactNotFoundError(LookupError):
    pass


def _check_contact_type(db: Session, type_id: int, current_id: int | None) -> None:
    """El tipo debe existir y estar activo (salvo que el contacto ya lo tuviera)."""
    contact_type = db.get(ContactType, type_id)
    if contact_type is None or (not contact_type.is_active and type_id != current_id):
        msg = f"El tipo de contacto {type_id} no existe o está desactivado"
        logger.warning("[app.services.contacts._check_contact_type] %s", msg)
        raise InvalidReferenceError(msg)


def list_contacts(db: Session, guest_id: int) -> list[Contact]:
    get_guest(db, guest_id)  # 404 si el invitado no existe
    stmt = (
        select(Contact)
        .where(Contact.guest_id == guest_id)
        .options(selectinload(Contact.contact_type))
        .order_by(Contact.id)
    )
    return list(db.execute(stmt).scalars())


def get_contact(db: Session, guest_id: int, contact_id: int) -> Contact:
    get_guest(db, guest_id)
    contact = db.get(Contact, contact_id)
    # Un contacto de otro invitado se trata como inexistente en esta ruta.
    if contact is None or contact.guest_id != guest_id:
        msg = f"No existe el contacto {contact_id} del invitado {guest_id}"
        logger.warning("[app.services.contacts.get_contact] %s", msg)
        raise ContactNotFoundError(msg)
    return contact


def create_contact(db: Session, guest_id: int, data: ContactCreate) -> Contact:
    get_guest(db, guest_id)
    _check_contact_type(db, data.contact_type_id, current_id=None)
    contact = Contact(
        guest_id=guest_id,
        contact_type_id=data.contact_type_id,
        value=data.value,
        note=data.note,
        source=data.source,
        verified=data.verified,
    )
    try:
        db.add(contact)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return contact


def update_contact(db: Session, guest_id: int, contact_id: int, data: ContactUpdate) -> Contact:
    contact = get_contact(db, guest_id, contact_id)
    sent = data.model_fields_set
    try:
        if "contact_type_id" in sent:
            if data.contact_type_id is None:
                raise InvalidReferenceError("El tipo de contacto no puede ser null")
            _check_contact_type(db, data.contact_type_id, current_id=contact.contact_type_id)
            contact.contact_type_id = data.contact_type_id
        if "value" in sent:
            if data.value is None:
                raise InvalidReferenceError("El valor del contacto no puede ser null")
            contact.value = data.value
        for field in ("source", "verified"):
            if field in sent:
                if getattr(data, field) is None:
                    raise InvalidReferenceError(f"El campo {field} no puede ser null")
                setattr(contact, field, getattr(data, field))
        if "note" in sent:
            contact.note = data.note
        db.commit()
    except Exception:
        db.rollback()
        raise
    return contact


def delete_contact(db: Session, guest_id: int, contact_id: int) -> None:
    contact = get_contact(db, guest_id, contact_id)
    db.delete(contact)
    db.commit()
    logger.info("[app.services.contacts.delete_contact] Contacto %s eliminado", contact_id)
