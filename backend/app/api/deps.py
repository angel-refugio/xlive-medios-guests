"""Dependencias de autenticación/autorización para proteger rutas."""
import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, User

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Devuelve el usuario activo del token; 401 si falta, es inválido o expiró."""
    unauthorized = HTTPException(
        status_code=401,
        detail="Credenciales inválidas o sesión expirada",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized

    user = db.execute(select(User).where(User.username == payload.get("sub"))).scalar_one_or_none()
    if user is None or not user.is_active:
        logger.warning("[app.api.deps.get_current_user] Usuario inexistente o inactivo: %r", payload.get("sub"))
        raise unauthorized
    return user


def require_roles(*roles: str):
    """Fábrica de dependencias por rol; permite agregar roles sin tocar las rutas."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            logger.warning("[app.api.deps.require_roles] Rol %r sin permiso", user.role)
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return user

    return checker


# Protege todas las rutas de CRUD (por ahora el administrador tiene todos los permisos).
require_admin = require_roles(ROLE_ADMIN)
