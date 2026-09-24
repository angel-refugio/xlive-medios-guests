"""Crea el administrador inicial con ADMIN_USERNAME / ADMIN_PASSWORD del entorno.

Ejecutar desde backend/ (venv activo, variables de .env cargadas):
    python -m scripts.create_admin
"""
import logging
import os
import sys

from app.db.session import make_engine, make_session_factory
from app.services.users import create_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def main() -> int:
    username = os.environ.get("ADMIN_USERNAME", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    with make_session_factory(make_engine())() as db:
        try:
            create_admin(db, username, password)
        except ValueError as exc:
            print(exc)
            return 1
    print(f"Administrador {username!r} creado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
