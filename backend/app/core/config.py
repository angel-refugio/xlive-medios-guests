"""Configuración de la aplicación, leída desde variables de entorno."""
import logging
import os

logger = logging.getLogger(__name__)


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
