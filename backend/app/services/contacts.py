"""Lógica de contactos: CRUD anidado bajo un invitado."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.catalogs import ContactType
from app.models.contact import Contact, normalize_contact_value
from app.schemas.contacts import ContactCreate, ContactUpdate
from app.services.guests import InvalidReferenceError, get_guest

logger = logging.getLogger(__name__)


class ContactNotFoundError(LookupError):
    pass


class ContactDuplicateError(ValueError):
    """El invitado ya tiene un contacto igual (mismo tipo y mismo valor, sin importar mayúsculas)."""


def _ensure_not_duplicate(
    db: Session, guest_id: int, type_id: int, value: str, exclude_id: int | None = None,
) -> None:
    stmt = select(Contact.id).where(
        Contact.guest_id == guest_id, Contact.contact_type_id == type_id,
        Contact.normalized_value == normalize_contact_value(value),
    )
    if exclude_id is not None:
        stmt = stmt.where(Contact.id != exclude_id)
    with db.no_autoflush:  # el contacto en edición ya trae el valor nuevo: no guardarlo antes de revisar
        exists = db.scalar(stmt) is not None
    if exists:
        msg = f"El invitado {guest_id} ya tiene un contacto igual de ese tipo"
        logger.warning("[app.services.contacts._ensure_not_duplicate] %s", msg)
        raise ContactDuplicateError(msg)


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
    _ensure_not_duplicate(db, guest_id, data.contact_type_id, data.value)
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
        if "contact_type_id" in sent or "value" in sent:
            _ensure_not_duplicate(
                db, guest_id, contact.contact_type_id, contact.value, exclude_id=contact.id,
            )
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
