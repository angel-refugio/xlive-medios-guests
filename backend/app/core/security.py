"""Hash de contraseñas (argon2) y tokens JWT."""
import logging
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_jwt_expire_minutes, get_jwt_secret

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True si la contraseña coincide; False ante cualquier fallo de verificación."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(username: str, role: str, expires_minutes: int | None = None) -> str:
    minutes = get_jwt_expire_minutes() if expires_minutes is None else expires_minutes
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "role": role, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decodifica y valida el token. Lanza jwt.PyJWTError si es inválido o expiró."""
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.warning("[app.core.security.decode_access_token] Token rechazado: %s", exc)
        raise
