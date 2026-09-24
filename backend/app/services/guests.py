"""Lógica de invitados: CRUD con categorías N↔N (creación al vuelo) y alcaldía."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.catalogs import Borough, GuestCategory
from app.models.guest import Guest
from app.schemas.guests import GuestCreate, GuestUpdate
from app.services.catalogs import normalize_name

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class GuestNotFoundError(LookupError):
    pass


class InvalidReferenceError(ValueError):
    """Una categoría o alcaldía indicada no existe o está desactivada."""


def _check_borough(db: Session, borough_id: int, current_id: int | None) -> None:
    borough = db.get(Borough, borough_id)
    if borough is None or (not borough.is_active and borough_id != current_id):
        msg = f"La alcaldía {borough_id} no existe o está desactivada"
        logger.warning("[app.services.guests._check_borough] %s", msg)
        raise InvalidReferenceError(msg)


def _resolve_categories(
    db: Session,
    category_ids: list[int],
    new_names: list[str],
    already_assigned: set[int],
) -> list[GuestCategory]:
    """Devuelve las categorías finales: las indicadas por id + las nombradas (creadas si faltan)."""
    resolved: dict[int, GuestCategory] = {}

    for cat_id in category_ids:
        category = db.get(GuestCategory, cat_id)
        if category is None or (not category.is_active and cat_id not in already_assigned):
            msg = f"La categoría {cat_id} no existe o está desactivada"
            logger.warning("[app.services.guests._resolve_categories] %s", msg)
            raise InvalidReferenceError(msg)
        resolved[category.id] = category

    if new_names:
        existing = {normalize_name(c.name): c for c in db.execute(select(GuestCategory)).scalars()}
        for name in new_names:
            key = normalize_name(name)
            category = existing.get(key)
            if category is None:
                category = GuestCategory(name=name)
                db.add(category)
                db.flush()  # asigna id
                existing[key] = category
                logger.info("[app.services.guests._resolve_categories] Categoría creada: %r", name)
            elif not category.is_active and category.id not in already_assigned:
                msg = f"La categoría {category.name!r} existe pero está desactivada; actívala primero"
                logger.warning("[app.services.guests._resolve_categories] %s", msg)
                raise InvalidReferenceError(msg)
            resolved[category.id] = category

    return list(resolved.values())


def list_guests(db: Session, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[list[Guest], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total = db.execute(select(func.count(Guest.id))).scalar_one()
    stmt = (
        select(Guest)
        .options(selectinload(Guest.categories), selectinload(Guest.borough))
        .order_by(func.lower(Guest.full_name), Guest.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(db.execute(stmt).scalars()), total


def get_guest(db: Session, guest_id: int) -> Guest:
    guest = db.get(Guest, guest_id)
    if guest is None:
        msg = f"No existe el invitado {guest_id}"
        logger.warning("[app.services.guests.get_guest] %s", msg)
        raise GuestNotFoundError(msg)
    return guest


def create_guest(db: Session, data: GuestCreate) -> Guest:
    if data.borough_id is not None:
        _check_borough(db, data.borough_id, current_id=None)
    try:
        categories = _resolve_categories(db, data.category_ids, data.new_categories, set())
        guest = Guest(
            full_name=data.full_name,
            organization=data.organization,
            role=data.role,
            notes=data.notes,
            approx_age=data.approx_age,
            borough_id=data.borough_id,
            categories=categories,
        )
        db.add(guest)
        db.commit()
    except Exception:
        db.rollback()  # deshace también las categorías creadas al vuelo
        raise
    return guest


def update_guest(db: Session, guest_id: int, data: GuestUpdate) -> Guest:
    guest = get_guest(db, guest_id)
    sent = data.model_fields_set
    try:
        if "full_name" in sent:
            if data.full_name is None:
                raise InvalidReferenceError("El nombre del invitado no puede ser null")
            guest.full_name = data.full_name
        for field in ("organization", "role", "notes", "approx_age"):
            if field in sent:
                setattr(guest, field, getattr(data, field))
        if "borough_id" in sent:
            if data.borough_id is not None:
                _check_borough(db, data.borough_id, current_id=guest.borough_id)
            guest.borough_id = data.borough_id
        if "category_ids" in sent or "new_categories" in sent:
            guest.categories = _resolve_categories(
                db,
                data.category_ids or [],
                data.new_categories or [],
                already_assigned={c.id for c in guest.categories},
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return guest


def delete_guest(db: Session, guest_id: int) -> None:
    """Borra el invitado; sus contactos y participaciones se borran en cascada (FK)."""
    guest = get_guest(db, guest_id)
    db.delete(guest)
    db.commit()
    logger.info("[app.services.guests.delete_guest] Invitado %s eliminado", guest_id)
