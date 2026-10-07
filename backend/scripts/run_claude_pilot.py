"""Piloto de extracción con Claude Code: corre los videos de la referencia por lotes y mide tokens.

Llama a `claude -p` (Claude Code, con tu suscripción) una vez por lote de una misma serie, con las
instrucciones de `app/prompts/extraction_instructions_v1.md`, y guarda la respuesta y los tokens de
cada lote en `backend/data/pilot/`. Al final escribe las predicciones en el caché de la evaluación
para medirlas con:
    python -m scripts.eval_extraction --extractor claude_code
No toca la base de datos ni YouTube. Los lotes ya guardados se saltan, así que una corrida
interrumpida se reanuda donde se quedó. Consume cuota de la suscripción; empieza con `--limit 15`.

Ejecutar desde backend/:
    python -m scripts.run_claude_pilot --limit 15
    python -m scripts.run_claude_pilot                      # los 150 videos
    python -m scripts.run_claude_pilot --overhead           # mide los tokens fijos de Claude Code
    python -m scripts.run_claude_pilot --summary-only --price-in 3 --price-out 15
(`--price-in/--price-out` = USD por millón de tokens del modelo que quieras comparar, tomados de la
página de precios de Anthropic; no se guardan precios en el código.)

Los tokens que reporta Claude Code incluyen instrucciones del sistema que la API directa no
envía, así que el costo equivalente sale al alza; `--overhead` mide esa parte fija.
Los contactos del video no se imprimen ni se escriben en los logs: solo se guardan en los
archivos de `data/pilot/` (carpeta fuera de Git).
"""
import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.services import claude_extraction, extraction_eval
from app.services.claude_extraction import ClaudeExtractionError, Usage

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_GOLD = DATA_DIR / "gold" / "guests_gold.json"
DEFAULT_SAMPLES_DIR = DATA_DIR / "samples"
DEFAULT_OUT_DIR = DATA_DIR / "pilot"
DEFAULT_EVAL_DIR = DATA_DIR / "eval"
DEFAULT_MODEL = "sonnet"
TIMEOUT_SECONDS = 900


def claude_command(model: str, instructions: str) -> list[str]:
    """Comando de Claude Code: sin herramientas, sin sesión guardada y con nuestras instrucciones."""
    executable = shutil.which("claude")
    if not executable:
        msg = "[scripts.run_claude_pilot.claude_command] No se encontró el comando 'claude' en el PATH"
        logger.error(msg)
        raise ClaudeExtractionError(msg)
    return [
        executable, "-p", "--output-format", "json", "--model", model,
        "--system-prompt", instructions, "--tools", "",
        "--no-session-persistence", "--disable-slash-commands",
    ]


def run_claude(command: list[str], prompt: str, runner=subprocess.run) -> tuple[str, Usage]:
    """Una llamada a Claude Code; devuelve el texto de la respuesta y sus tokens.

    Se ejecuta desde una carpeta temporal para que no cargue el CLAUDE.md ni la configuración de
    este proyecto (las instrucciones del extractor son solo las del archivo).
    """
    with tempfile.TemporaryDirectory() as workdir:
        try:
            proc = runner(
                command, input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS, cwd=workdir,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"[scripts.run_claude_pilot.run_claude] No se pudo ejecutar claude: {exc}"
            logger.error(msg)
            raise ClaudeExtractionError(msg) from exc
    if proc.returncode != 0:
        msg = (
            f"[scripts.run_claude_pilot.run_claude] claude terminó con código {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '')[:300]}"
        )
        logger.error(msg)
        raise ClaudeExtractionError(msg)
    return claude_extraction.parse_cli_envelope(proc.stdout)


def _usage_dict(usage: Usage) -> dict:
    return {
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "reported_cost_usd": usage.reported_cost_usd, "calls": usage.calls, "models": usage.models,
    }


def _usage_from_dict(data: dict) -> Usage:
    numbers = {k: data.get(k, 0) for k in _usage_dict(Usage()) if k != "models"}
    return Usage(**numbers, models=list(data.get("models") or []))


def batch_path(out_dir: Path, index: int, batch: list[str]) -> Path:
    """Un archivo por lote; el sufijo depende de sus videos, así un lote distinto con el mismo
    número (por ejemplo, tras cambiar --limit) nunca se confunde con uno ya guardado."""
    digest = hashlib.sha1(",".join(batch).encode("utf-8")).hexdigest()[:8]
    return out_dir / f"batch_{index:04d}_{digest}.json"


def saved_batches(out_dir: Path) -> set[tuple[str, ...]]:
    """Listas de videos de los lotes ya guardados (un archivo ilegible se ignora aquí)."""
    saved: set[tuple[str, ...]] = set()
    for path in Path(out_dir).glob("batch_*.json"):
        try:
            saved.add(tuple(json.loads(path.read_text(encoding="utf-8"))["video_ids"]))
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[scripts.run_claude_pilot.saved_batches] Se ignora %s (ilegible)", path.name)
    return saved


def eval_cache_path(eval_dir: Path, model: str) -> Path:
    safe_model = re.sub(r"[^\w.-]+", "_", model)
    return eval_dir / f"predictions_claude_code_{safe_model}.json"


def process_batches(
    videos: dict[str, dict], batches: list[list[str]], args: argparse.Namespace, runner=subprocess.run,
) -> int:
    """Corre los lotes pendientes y guarda cada resultado. Devuelve cuántos fallaron."""
    args.out_dir.mkdir(parents=True, exist_ok=True)
    instructions = claude_extraction.load_instructions()
    command = claude_command(args.model, instructions)
    failures = 0
    done = saved_batches(args.out_dir)
    for index, batch in enumerate(batches, start=1):
        if tuple(batch) in done:
            continue
        path = batch_path(args.out_dir, index, batch)
        started = time.monotonic()
        try:
            prompt = claude_extraction.build_user_prompt(videos, batch)
            text, usage = run_claude(command, prompt, runner)
            result = claude_extraction.parse_batch_output(text, batch)
        except ClaudeExtractionError as exc:
            failures += 1
            logger.warning("[scripts.run_claude_pilot.process_batches] Lote %d falló: %s", index, exc)
            continue
        path.write_text(json.dumps({
            "model": args.model, "instructions_version": claude_extraction.INSTRUCTIONS_VERSION,
            "video_ids": batch, "usage": _usage_dict(usage),
            "result": result.model_dump(),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info(
            "[lote %d/%d] %d videos, %d tokens de entrada, %d de salida (%.0f s)",
            index, len(batches), len(batch), usage.total_input_tokens, usage.output_tokens,
            time.monotonic() - started,
        )
    return failures


def load_results(out_dir: Path) -> tuple[dict[str, dict], dict[str, tuple[int, int]], Usage]:
    """Lee los lotes guardados: predicciones por video, conteo de contactos y tokens totales."""
    predictions: dict[str, dict] = {}
    contacts: dict[str, tuple[int, int]] = {}
    total = Usage()
    for path in sorted(Path(out_dir).glob("batch_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            total.add(_usage_from_dict(data["usage"]))
            for raw in data["result"]["videos"]:
                video = claude_extraction.VideoExtraction.model_validate(raw)
                predictions[video.video_id] = claude_extraction.to_eval_entry(video)
                contacts[video.video_id] = claude_extraction.count_contacts(video)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = f"[scripts.run_claude_pilot.load_results] Lote ilegible {path.name}: {exc}"
            logger.error(msg)
            raise ClaudeExtractionError(msg) from exc
    return predictions, contacts, total


def measure_overhead(args: argparse.Namespace, runner=subprocess.run) -> Usage:
    """Una llamada mínima con las mismas instrucciones: los tokens fijos de Claude Code."""
    command = claude_command(args.model, claude_extraction.load_instructions())
    _, usage = run_claude(command, 'Responde solo con {"instructions_version": "v1", "videos": []}', runner)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "overhead.json").write_text(json.dumps(_usage_dict(usage), indent=1), encoding="utf-8")
    return usage


def print_summary(args: argparse.Namespace, total: Usage, videos_done: int, contacts: dict[str, tuple[int, int]]) -> None:
    overhead_path = args.out_dir / "overhead.json"
    overhead = _usage_from_dict(json.loads(overhead_path.read_text(encoding="utf-8"))) if overhead_path.exists() else None
    print(f"Videos con resultado: {videos_done} | llamadas: {total.calls}")
    print(f"Modelo(s) que respondieron: {', '.join(total.models) or 'no registrado (lotes anteriores)'}")
    print(
        f"Tokens: entrada {total.total_input_tokens:,} (nuevos {total.input_tokens:,}, "
        f"caché {total.cache_creation_tokens + total.cache_read_tokens:,}), salida {total.output_tokens:,}"
    )
    print(f"Costo que reporta Claude Code (referencia, sin cobro por la suscripción): {total.reported_cost_usd:.4f} USD")
    print(f"Contactos asignados: {sum(a for a, _ in contacts.values())}; sin asignar: {sum(u for _, u in contacts.values())}")
    if overhead:
        print(f"Tokens fijos de Claude Code por llamada (--overhead): entrada {overhead.total_input_tokens:,}")
    if args.price_in is not None and args.price_out is not None and videos_done:
        gross = total.estimated_api_cost_usd(args.price_in, args.price_out)
        print(f"Costo equivalente en API (al alza): {gross:.4f} USD = {gross / videos_done * 1000:.2f} USD por 1,000 videos")
        if overhead:
            net_in = max(total.total_input_tokens - overhead.total_input_tokens * total.calls, 0)
            net = (net_in * args.price_in + total.output_tokens * args.price_out) / 1_000_000
            print(f"Sin los tokens fijos de Claude Code: {net:.4f} USD = {net / videos_done * 1000:.2f} USD por 1,000 videos")
    print("Mide la calidad con: python -m scripts.eval_extraction --extractor claude_code")


def run(args: argparse.Namespace, runner=subprocess.run) -> int:
    try:
        if args.overhead:
            usage = measure_overhead(args, runner)
            print(f"Tokens fijos por llamada: entrada {usage.total_input_tokens:,}, salida {usage.output_tokens:,}")
            return 0
        if not args.summary_only:
            gold = extraction_eval.load_gold(args.gold)
            samples = extraction_eval.load_sample_videos(args.samples_dir)
            ids = [i for i in gold if i in samples]
            ids = ids[:args.limit] if args.limit else ids
            if not ids:
                logger.error("[scripts.run_claude_pilot.run] Ningún video (revisa --gold y --samples-dir)")
                return 1
            videos = {i: samples[i] for i in ids}
            batches = claude_extraction.build_batches(videos, args.batch_size)
            failures = process_batches(videos, batches, args, runner)
            if failures:
                print(f"{failures} lote(s) fallaron; vuelve a correr el comando para reintentarlos.")
        predictions, contacts, total = load_results(args.out_dir)
        if not predictions:
            print("Todavía no hay lotes guardados.")
            return 1
        if not args.summary_only and len(predictions) < len(ids):
            print(f"Faltan {len(ids) - len(predictions)} de {len(ids)} videos sin resultado; vuelve a correr el comando.")
        path = eval_cache_path(args.eval_dir, args.model)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(predictions, ensure_ascii=False, indent=1), encoding="utf-8")
        print_summary(args, total, len(predictions), contacts)
        return 0
    except (ClaudeExtractionError, extraction_eval.EvalError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Piloto de extracción con Claude Code.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Alias o nombre del modelo de Claude Code")
    p.add_argument("--limit", type=int, default=None, help="Solo los primeros N videos de la referencia")
    p.add_argument("--batch-size", type=int, default=claude_extraction.DEFAULT_BATCH_SIZE)
    p.add_argument("--summary-only", action="store_true", help="No llamar a Claude; resumir lo ya guardado")
    p.add_argument("--overhead", action="store_true", help="Medir los tokens fijos de una llamada vacía")
    p.add_argument("--price-in", type=float, default=None, help="USD por millón de tokens de entrada")
    p.add_argument("--price-out", type=float, default=None, help="USD por millón de tokens de salida")
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
