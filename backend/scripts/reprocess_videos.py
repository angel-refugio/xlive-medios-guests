"""Vuelve a procesar con el extractor actual los videos que nadie ha revisado todavía.

Sirve cuando mejoran las reglas (por ejemplo "con nosotros X y Y") y quieres que los videos ya
ingeridos, aún sin revisar, se vuelvan a analizar. Lo ya aceptado o rechazado por una persona no se
toca; solo se rehacen los candidatos pendientes (son regenerables). Usa Ollama: ~10 s por video.

Ejecutar desde backend/ (venv activo, Ollama corriendo, variables de .env cargadas):
    python -m scripts.reprocess_videos            # solo muestra qué videos se reprocesarían
    python -m scripts.reprocess_videos --yes      # los reprocesa
"""
import argparse
import logging
import sys

import httpx

from app.core.config import get_ollama_base_url, get_ollama_model
from app.db.session import make_engine, make_session_factory
from app.services import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reprocesa los videos ingeridos y aún sin revisar.")
    parser.add_argument("--yes", action="store_true", help="Hacerlo de verdad (sin esto solo se simula)")
    args = parser.parse_args(argv)

    with make_session_factory(make_engine())() as db, httpx.Client() as client:
        result = pipeline.reprocess_unreviewed_videos(
            db, client, get_ollama_base_url(), get_ollama_model(), dry_run=not args.yes,
        )
    print(f"Videos sin revisar: {len(result['videos'])}")
    if not args.yes:
        print("Simulación: no se cambió nada. Corre con --yes para reprocesarlos.")
        return 0
    print(f"Reprocesados: {result['reprocessed']}; con error: {len(result['errors'])}")
    for error in result["errors"]:
        print(f"  {error['video']}: {error['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
