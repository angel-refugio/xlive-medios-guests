"""Entorno de Alembic. La URL de la BD viene de variables de entorno."""
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_database_url
from app.db.base import Base
import app.models  # noqa: F401  (registra los modelos en Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger(__name__)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    try:
        engine = create_engine(get_database_url())
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    except Exception:
        logger.exception("[alembic.env.run_migrations_online] Falló la migración")
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
