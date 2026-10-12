"""Marca los videos duplicados (📱) que la ingesta no marcó y pasa lo ya revisado al que se conserva.

Sirve para los videos que entraron antes de que el importador de Claude detectara duplicados. Por
cada par (mismo título sin emoji, misma descripción, duración parecida y fecha cercana):
- deja a los dos marcados entre sí;
- se conserva el que NO tiene 📱 (si empatan, el de menor id) y el otro queda como copia oculta;
- si la copia ya estaba revisada (invitados, contactos, programa…), el que se conserva hereda esa
  revisión y no vuelve a pedirla.
Es seguro repetirlo: lo ya reconciliado no cambia. No borra videos.

Ejecutar desde backend/ (venv activo, `.env` cargado):
    python -m scripts.reconcile_duplicates            # solo muestra qué cambiaría
    python -m scripts.reconcile_duplicates --yes      # lo aplica
"""
import argparse
import logging
import sys

from sqlalchemy import select

from app.db.session import make_engine, make_session_factory
from app.models.video import Video
from app.services import duplicates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def reconcile_all(db) -> list[duplicates.ReconcileResult]:
    """Reconcilia todos los videos ya ingeridos; devuelve solo los pares que cambiaron."""
    changes: list[duplicates.ReconcileResult] = []
    ids = list(db.scalars(select(Video.id).where(Video.last_ingested_at.is_not(None)).order_by(Video.id)))
    for video_id in ids:
        try:
            with db.begin_nested():     # un video con error deshace solo lo suyo
                result = duplicates.reconcile(db, db.get(Video, video_id))
        except Exception as exc:  # noqa: BLE001 - un video con error no detiene al resto
            logger.error("[scripts.reconcile_duplicates.reconcile_all] Video %s falló: %s", video_id, exc)
            continue
        if result is not None and result.changed:
            changes.append(result)
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marca duplicados 📱 y pasa lo revisado al que se conserva.")
    parser.add_argument("--yes", action="store_true", help="Aplicar los cambios (sin esto solo se simula)")
    args = parser.parse_args(argv)

    with make_session_factory(make_engine())() as db:
        changes = reconcile_all(db)
        print(f"Pares que cambian: {len(changes)}")
        for r in changes:
            detail = (f"hereda {r.participations} participaciones, {r.contacts} contactos y "
                      f"{r.staging_rows} candidatos" if r.inherited else "solo se marca")
            print(f"  se conserva el video {r.keeper_id}; copia oculta: {r.copy_id} ({detail})")
        if not args.yes:
            db.rollback()
            print("Simulación: no se cambió nada. Corre con --yes para aplicarlo.")
            return 0
        db.commit()
        print("Cambios aplicados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
