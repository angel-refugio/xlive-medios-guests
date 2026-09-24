"""Lógica genérica de catálogos: listar, crear, renombrar y activar/desactivar."""
import logging
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.catalogs import CatalogCreate, CatalogUpdate

logger = logging.getLogger(__name__)


class CatalogNotFoundError(LookupError):
    pass


class CatalogDuplicateError(ValueError):
    pass


def normalize_name(name: str) -> str:
    """Clave de comparación: sin acentos, sin mayúsculas y con espacios colapsados.

    "Música", "musica" y "  MÚSICA " dan la misma clave. Solo sirve para detectar
    duplicados; el nombre se guarda tal como lo escribió el usuario.
    """
    decomposed = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.casefold().split())


def _ensure_unique(db: Session, model, name: str, exclude_id: int | None = None) -> None:
    """Lanza CatalogDuplicateError si otro registro tiene el mismo nombre normalizado.

    Los catálogos son listas cortas, así que se compara en Python (funciona igual
    en PostgreSQL y SQLite, sin depender de extensiones como unaccent).
    """
    key = normalize_name(name)
    stmt = select(model.id, model.name)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    for _id, existing in db.execute(stmt):
        if normalize_name(existing) == key:
            msg = (
                f"Ya existe un registro parecido a {name!r} en {model.__tablename__}: "
                f"{existing!r} (se ignoran mayúsculas, acentos y espacios extra)"
            )
            logger.warning("[app.services.catalogs._ensure_unique] %s", msg)
            raise CatalogDuplicateError(msg)


def list_items(db: Session, model, include_inactive: bool = False) -> list:
    stmt = select(model).order_by(func.lower(model.name))
    if not include_inactive:
        stmt = stmt.where(model.is_active.is_(True))
    return list(db.execute(stmt).scalars())


def get_item(db: Session, model, item_id: int):
    item = db.get(model, item_id)
    if item is None:
        msg = f"No existe el registro {item_id} en {model.__tablename__}"
        logger.warning("[app.services.catalogs.get_item] %s", msg)
        raise CatalogNotFoundError(msg)
    return item


def create_item(db: Session, model, data: CatalogCreate):
    _ensure_unique(db, model, data.name)
    item = model(name=data.name)
    db.add(item)
    db.commit()
    return item


def update_item(db: Session, model, item_id: int, data: CatalogUpdate):
    item = get_item(db, model, item_id)
    if data.name is not None and data.name != item.name:
        _ensure_unique(db, model, data.name, exclude_id=item.id)
        item.name = data.name
    if data.is_active is not None:
        item.is_active = data.is_active
    db.commit()
    return item
