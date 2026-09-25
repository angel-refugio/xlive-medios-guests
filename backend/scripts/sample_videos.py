"""Toma una muestra aleatoria de videos del canal y la guarda en un JSON local.

Sirve para (1) tener datos reales de prueba y (2) estudiar cómo se escriben los títulos y
descripciones antes de definir las reglas del LLM. No escribe en la base de datos.

Cada ejecución excluye los videos de muestras anteriores, así que correrlo 3 veces da
90 videos distintos. Ejecutar desde backend/ (venv activo):
    python -m scripts.sample_videos                 # 30 videos
    python -m scripts.sample_videos --count 30 --seed 7

Salida: backend/data/samples/sample_<fecha>.json (fuera de Git).
"""
import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import get_youtube_api_key
from app.services import youtube_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

DEFAULT_HANDLE = "xlivemedios"
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"


def load_excluded_ids(out_dir: Path) -> set[str]:
    """IDs ya muestreados en corridas anteriores. Un JSON ilegible detiene la corrida."""
    excluded: set[str] = set()
    for path in sorted(out_dir.glob("sample_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            excluded.update(video["id"] for video in data["videos"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = f"[scripts.sample_videos.load_excluded_ids] No se pudo leer {path.name}: {exc}"
            logger.error(msg)
            raise RuntimeError(msg) from exc
    return excluded


def pick_ids(all_ids: list[str], excluded: set[str], count: int, seed: int) -> list[str]:
    """Elige `count` IDs al azar (reproducible con `seed`) que no estén excluidos."""
    candidates = sorted(set(all_ids) - excluded)
    return random.Random(seed).sample(candidates, min(count, len(candidates)))


def run(handle: str, count: int, seed: int, out_dir: Path, client: httpx.Client) -> Path:
    """Ejecuta el muestreo completo y devuelve la ruta del JSON escrito."""
    api_key = get_youtube_api_key()
    out_dir.mkdir(parents=True, exist_ok=True)
    excluded = load_excluded_ids(out_dir)

    playlist_id = youtube_client.get_uploads_playlist_id(client, api_key, handle)
    all_ids = youtube_client.list_video_ids(client, api_key, playlist_id)
    chosen = pick_ids(all_ids, excluded, count, seed)
    if not chosen:
        msg = "[scripts.sample_videos.run] No quedan videos sin muestrear en el canal"
        logger.error(msg)
        raise RuntimeError(msg)
    videos = youtube_client.get_video_details(client, api_key, chosen)

    now = datetime.now(timezone.utc)
    result = {
        "generated_at": now.isoformat(),
        "handle": handle,
        "seed": seed,
        "total_in_channel": len(all_ids),
        "excluded_from_previous": len(excluded),
        "videos": videos,
    }
    # Con microsegundos: dos corridas seguidas nunca comparten archivo ni se sobrescriben.
    path = out_dir / f"sample_{now.strftime('%Y%m%d_%H%M%S_%f')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Muestra guardada: %s (%d videos de %d en el canal)", path, len(videos), len(all_ids))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--count", type=int, default=30, help="videos por corrida (30)")
    parser.add_argument("--seed", type=int, default=int(time.time()), help="semilla del azar")
    parser.add_argument("--handle", default=DEFAULT_HANDLE, help="@handle del canal")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        with httpx.Client() as client:
            run(args.handle, args.count, args.seed, args.out_dir, client)
    except (RuntimeError, youtube_client.YouTubeError) as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
