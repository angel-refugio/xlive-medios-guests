"""Importa a Staging Review lo que extrajo Claude Code (carpeta de lotes de `run_claude_pilot`).

Todo entra como CANDIDATO (invitados, conductores, programa y contactos con sus dudosos); nada pasa
a las tablas finales sin revisión humana. Es la misma importación que usará el extractor por API
(`app/services/claude_import.py`): solo cambia de dónde vienen los resultados.

Los videos deben existir en la BD (sincroniza el canal primero). Para cargar los 150 videos de
muestra del piloto, usa `--create-missing`: los crea con los metadatos de `data/samples` (los
mismos que entregó la API de YouTube). Reimportar es seguro: se reemplazan los candidatos
pendientes de cada video y se conservan los ya aceptados o rechazados.

Ejecutar desde backend/ (venv activo, `.env` cargado):
    python -m scripts.import_claude_results --dry-run                # simula y no guarda nada
    python -m scripts.import_claude_results --create-missing
    python -m scripts.import_claude_results data/pilot_v5 --extractor claude_code
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import make_engine, make_session_factory
from app.services import claude_extraction, claude_import
from app.services.claude_import import ClaudeImportError

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_SAMPLES_DIR = DATA_DIR / "samples"


def load_video_metadata(samples_dir: Path) -> dict[str, dict]:
    """{youtube_video_id: metadatos crudos} de los JSON de muestras (formato de la API de YouTube)."""
    metadata: dict[str, dict] = {}
    for path in sorted(Path(samples_dir).glob("sample_*.json")):
        try:
            for video in json.loads(path.read_text(encoding="utf-8"))["videos"]:
                metadata.setdefault(video["id"], video)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = f"[scripts.import_claude_results.load_video_metadata] No se pudo leer {path.name}: {exc}"
            logger.error(msg)
            raise ClaudeImportError(msg) from exc
    return metadata


def run(args: argparse.Namespace, db: Session) -> int:
    batch = claude_import.load_claude_code_results(args.pilot_dir)
    metadata = load_video_metadata(args.samples_dir) if args.create_missing else None
    summary = claude_import.import_batch(
        db, batch, extractor=args.extractor, video_metadata=metadata,
        create_missing=args.create_missing, commit=not args.dry_run,
    )
    mode = "SIMULACIÓN (no se guardó nada)" if args.dry_run else "Importación terminada"
    print(f"{mode} · instrucciones {batch.instructions_version} · origen {args.extractor}")
    print(f"Videos importados: {summary.videos} (creados en la BD: {summary.created_videos})")
    print(f"Candidatos de invitado: {summary.guests} · sugerencias de programa/conductores: {summary.suggestions}")
    print(
        f"Contactos candidatos: {summary.contacts} (dudosos: {summary.doubtful_contacts}, "
        f"sin asignar: {summary.unassigned_contacts})"
    )
    print(f"Pendientes reemplazados: {summary.replaced_pending} · ya revisados y respetados: {summary.skipped_reviewed}")
    print(f"Videos que forman un par duplicado (📱): {summary.duplicates} · heredaron lo ya revisado de su copia: {summary.inherited_reviews}")
    if summary.missing_videos:
        print(
            f"{len(summary.missing_videos)} video(s) no están en la BD y se omitieron "
            "(sincroniza el canal o usa --create-missing)."
        )
    for youtube_id, message in summary.errors:
        print(f"ERROR en {youtube_id}: {message}", file=sys.stderr)
    return 1 if summary.errors else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Importa a staging los resultados de Claude Code.")
    p.add_argument("pilot_dir", type=Path, nargs="?", default=None,
                   help="Carpeta de lotes (por defecto data/pilot_<versión por defecto>)")
    p.add_argument("--extractor", choices=claude_import.EXTRACTORS, default="claude_code")
    p.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR)
    p.add_argument("--create-missing", action="store_true",
                   help="Crear los videos que no estén en la BD con los metadatos de --samples-dir")
    p.add_argument("--dry-run", action="store_true", help="Simular: no guarda nada")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = build_parser().parse_args(argv)
    args.pilot_dir = args.pilot_dir or DATA_DIR / f"pilot_{claude_extraction.INSTRUCTIONS_VERSION}"
    try:
        with make_session_factory(make_engine())() as db:
            return run(args, db)
    except ClaudeImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
