"""Motor y sesión de base de datos."""
import logging
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_database_url

logger = logging.getLogger(__name__)


def make_engine(url: str | None = None):
    """Crea un engine. Sin argumento usa la configuración de entorno."""
    try:
        return create_engine(url or get_database_url(), pool_pre_ping=True)
    except Exception:
        logger.exception("[app.db.session.make_engine] No se pudo crear el engine")
        raise


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache(maxsize=1)
def _default_session_factory() -> sessionmaker:
    return make_session_factory(make_engine())


def get_db():
    """Dependencia de FastAPI: entrega una sesión y la cierra al terminar."""
    session = _default_session_factory()()
    try:
        yield session
    finally:
        session.close()
