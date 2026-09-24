"""Configuración de la aplicación, leída desde variables de entorno."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Carga el .env de la raíz del proyecto (backend/app/core/config.py -> 3 niveles arriba).
# Sin override: las variables ya definidas en la terminal tienen prioridad.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


def get_jwt_secret() -> str:
    """Secreto para firmar los JWT. Lanza RuntimeError si no está configurado."""
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        msg = "[app.core.config.get_jwt_secret] Falta la variable de entorno JWT_SECRET"
        logger.error(msg)
        raise RuntimeError(msg)
    return secret


def get_jwt_expire_minutes() -> int:
    """Duración del token en minutos (JWT_EXPIRE_MINUTES, por defecto 60)."""
    raw = os.environ.get("JWT_EXPIRE_MINUTES", "60")
    try:
        return int(raw)
    except ValueError:
        msg = f"[app.core.config.get_jwt_expire_minutes] JWT_EXPIRE_MINUTES inválido: {raw!r}"
        logger.error(msg)
        raise RuntimeError(msg)


def get_database_url() -> str:
    """Construye la URL de conexión a PostgreSQL desde variables de entorno.

    Si existe DATABASE_URL se usa tal cual (útil para pruebas o CI).
    Lanza RuntimeError con el módulo/función si faltan variables obligatorias.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    missing = [
        name for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not os.environ.get(name)
    ]
    if missing:
        msg = (
            "[app.core.config.get_database_url] Faltan variables de entorno: "
            + ", ".join(missing)
        )
        logger.error(msg)
        raise RuntimeError(msg)

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return (
        f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@{host}:{port}/{os.environ['POSTGRES_DB']}"
    )
