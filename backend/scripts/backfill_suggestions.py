"""Crea la sugerencia de programa y conductores de los videos ya ingeridos que aún no la tienen.

Solo usa reglas (sin LLM, sin red) y es idempotente: se puede correr las veces que haga falta,
por ejemplo después de capturar programas o conductores en los catálogos. Ejecutar desde backend/
(venv activo, variables de .env cargadas):
    python -m scripts.backfill_suggestions
"""
import logging
import sys

from app.db.session import make_engine, make_session_factory
from app.services import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def main() -> int:
    with make_session_factory(make_engine())() as db:
        created = pipeline.backfill_video_suggestions(db)
    print(f"Sugerencias creadas: {created}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
