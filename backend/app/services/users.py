"""Lógica de usuarios: creación del administrador inicial."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import ROLE_ADMIN, User

logger = logging.getLogger(__name__)


def create_admin(db: Session, username: str, password: str) -> User:
    """Crea el usuario administrador. Lanza ValueError si faltan datos o el usuario ya existe."""
    if not username or not password:
        msg = "[app.services.users.create_admin] Usuario y contraseña son obligatorios"
        logger.error(msg)
        raise ValueError(msg)
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        msg = f"[app.services.users.create_admin] El usuario {username!r} ya existe"
        logger.error(msg)
        raise ValueError(msg)

    user = User(username=username, password_hash=hash_password(password), role=ROLE_ADMIN)
    db.add(user)
    db.commit()
    logger.info("[app.services.users.create_admin] Administrador %r creado", username)
    return user
