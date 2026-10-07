"""Mide el extractor de invitados/conductores/programa contra la referencia (gold set).

Corre el extractor actual ("baseline": reglas de regex + LLM local, igual que la ingesta) sobre
los videos de `backend/data/gold/guests_gold.json`, compara con la referencia y escribe un
reporte. No escribe en la base de datos ni en YouTube; solo llama a Ollama.

Cada predicción se guarda en un caché (`backend/data/eval/`), así que una corrida interrumpida
se reanuda donde se quedó, y `--rescore-only` recalcula el reporte sin llamar al LLM. Con el
LLM en CPU cada video tarda de decenas de segundos a minutos: empieza con `--limit 10`.
Ejecutar desde backend/ (venv activo, Ollama corriendo):
    python -m scripts.eval_extraction --limit 10
    python -m scripts.eval_extraction --only-reviewed
    python -m scripts.eval_extraction            # los 150 videos
    python -m scripts.eval_extraction --rescore-only
    python -m scripts.eval_extraction --extractor profile   # etapa 1 sin LLM (instantáneo)
    python -m scripts.eval_extraction --extractor profile_llm --limit 10   # etapas 1 + 2 (LLM)
    python -m scripts.eval_extraction --extractor profile_llm_simple      # + invitados del LLM (prompt simple)
    python -m scripts.eval_extraction --extractor claude_code --model sonnet   # piloto v1: lee lo que dejó run_claude_pilot
    python -m scripts.eval_extraction --extractor claude_code_v2 --model sonnet   # piloto con instrucciones v2

Catálogos: por defecto se simulan con los programas y conductores de la referencia (como si el
usuario ya los hubiera capturado en la app); `--no-catalog` los deja vacíos.
"""
import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import httpx

from app.core.config import get_ollama_base_url, get_ollama_model
from app.services import candidate_classifier, extraction_eval, ollama_client, regex_rules, series_profile
from app.services.extraction_eval import EvalError, Prediction

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_GOLD = DATA_DIR / "gold" / "guests_gold.json"
DEFAULT_SAMPLES_DIR = DATA_DIR / "samples"
DEFAULT_OUT_DIR = DATA_DIR / "eval"
EXTRACTORS = ("baseline", "profile", "profile_llm", "profile_llm_guests", "profile_llm_simple", "claude_code", "claude_code_v2")
# Extractores que suman los invitados del LLM como segunda opinión (con evidencia literal).
SECOND_OPINION = ("profile_llm_guests", "profile_llm_simple")


def gold_catalogs(gold: dict[str, dict]) -> dict[str, list[str]]:
    """Catálogos simulados: programas y conductores distintos de la referencia."""
    programs = sorted({e["program"] for e in gold.values() if e.get("program")})
    hosts = sorted({h for e in gold.values() for h in e["hosts"]})
    return {"programs": programs, "hosts": hosts}


def baseline_predict(
    client: httpx.Client, base_url: str, model: str, title: str, description: str,
    catalogs: dict[str, list[str]],
) -> Prediction:
    """Lo mismo que hace `pipeline.process_video` con los nombres: regex + LLM.

    Invitados = candidatos de regex + invitados del LLM; conductor = `host_match`; programa =
    `program_match` (el LLM solo puede señalar uno de los catálogos).
    """
    analysis = ollama_client.analyze_video(
        client, base_url, model, title, description,
        existing_hosts=catalogs["hosts"], existing_programs=catalogs["programs"],
    )
    regex_names = [m.name for m in regex_rules.extract_name_candidates(title, description)]
    return Prediction(
        guests=[*regex_names, *(g.name for g in analysis.guests)],
        hosts=[analysis.host_match] if analysis.host_match else [],
        program=analysis.program_match or "",
    )


def _profile_hints(video: dict, catalogs: dict[str, list[str]], profile) -> series_profile.VideoHints:
    return series_profile.extract_hints(
        video["title"], video["description"], catalogs["programs"], profile, catalogs["hosts"],
    )


def profile_llm_verdicts(
    client: httpx.Client, base_url: str, model: str, video: dict, catalogs: dict[str, list[str]],
    profile: series_profile.SeriesProfile | None,
) -> list[dict]:
    """Etapa 2: llama al LLM solo si hay candidatos dudosos y devuelve sus veredictos CRUDOS.

    Se guardan los veredictos (no la predicción final) para poder cambiar la política con la que
    se aplican y volver a puntuar con `--rescore-only`, sin repetir las llamadas al LLM.
    """
    hints = _profile_hints(video, catalogs, profile)
    candidates = candidate_classifier.doubtful_candidates(hints)
    if not candidates:
        return []
    classification = candidate_classifier.classify(
        client, base_url, model, video["title"], video["description"], hints.program,
        list(profile.hosts.values()) if profile else [], [c.name for c in candidates],
    )
    return [v.model_dump() for v in classification.verdicts]


def profile_llm_prediction(
    video: dict, catalogs: dict[str, list[str]], profile: series_profile.SeriesProfile | None,
    verdicts: list[dict], policy: dict[str, bool],
) -> dict:
    """Etapa 1 + los veredictos guardados aplicados con la política indicada (sin red)."""
    refined = candidate_classifier.apply_verdicts(
        _profile_hints(video, catalogs, profile),
        candidate_classifier.CandidateClassification.model_validate({"verdicts": verdicts}),
        video["description"], **policy,
    )
    return {
        "guests": [g.name for g in refined.guests], "hosts": [h.name for h in refined.hosts],
        "program": refined.program,
    }


def llm_guests_entry(
    client: httpx.Client, base_url: str, model: str, video: dict, catalogs: dict[str, list[str]],
) -> list[dict]:
    """Lo que `analyze_video` (el LLM solo, sin reglas) propone como invitados de un video."""
    analysis = ollama_client.analyze_video(
        client, base_url, model, video["title"], video["description"],
        existing_hosts=catalogs["hosts"], existing_programs=catalogs["programs"],
    )
    return [
        {"name": g.name, "is_possible_group": g.is_possible_group, "raw_confidence": g.raw_confidence}
        for g in analysis.guests
    ]


def simple_guests_entry(
    client: httpx.Client, base_url: str, model: str, video: dict,
) -> list[dict]:
    """Invitados que el LLM da con el prompt simple (una sola pregunta)."""
    names = candidate_classifier.simple_guest_names(
        client, base_url, model, video["title"], video["description"],
    )
    return [{"name": n} for n in names]


def second_opinion_prediction(
    base: dict, video: dict, llm_guests: list[dict], catalogs: dict[str, list[str]], mode: str,
) -> dict:
    """Predicción de `base` (perfil + LLM que descarta) más los invitados que el LLM agrega con
    evidencia literal en el texto (`candidate_classifier.second_opinion_guests`)."""
    extra = candidate_classifier.second_opinion_guests(
        base["guests"], [g["name"] for g in llm_guests], f"{video['title']}\n{video['description']}",
        excluded=[*base["hosts"], *catalogs["hosts"], *catalogs["programs"], base["program"]],
        mode=mode,
    )
    return {**base, "guests": [*base["guests"], *extra]}


def profile_predictions(
    samples: dict[str, dict], ids: list[str], catalogs: dict[str, list[str]],
) -> dict[str, dict]:
    """Etapa 1 sola (perfil por serie, sin LLM): se calcula al vuelo, no necesita caché.

    Los perfiles se arman con TODAS las muestras (la recurrencia necesita ver la serie
    completa), aunque solo se evalúen `ids`.
    """
    video_series, profiles = series_profile.build_profiles(samples, catalogs["programs"], catalogs["hosts"])
    predictions: dict[str, dict] = {}
    for video_id in ids:
        video = samples[video_id]
        guests, hosts, program = series_profile.predict(
            video["title"], video["description"], catalogs["programs"],
            profiles.get(video_series.get(video_id, "")), catalogs["hosts"],
        )
        predictions[video_id] = {"guests": guests, "hosts": hosts, "program": program}
    return predictions


def cache_path(out_dir: Path, extractor: str, model: str) -> Path:
    safe_model = re.sub(r"[^\w.-]+", "_", model)
    return out_dir / f"predictions_{extractor}_{safe_model}.json"


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"[scripts.eval_extraction.load_cache] Caché ilegible {path.name}: {exc}. Bórralo para empezar de cero."
        logger.error(msg)
        raise EvalError(msg) from exc


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def select_video_ids(
    gold: dict[str, dict], samples: dict[str, dict], limit: int | None, only_reviewed: bool,
) -> list[str]:
    """IDs a evaluar: están en la referencia y en las muestras (con su texto), en orden estable."""
    ids = [i for i in gold if i in samples and (not only_reviewed or gold[i].get("reviewed"))]
    return ids[:limit] if limit else ids


def run(args: argparse.Namespace, client: httpx.Client | None = None) -> int:
    """Corre la evaluación. Devuelve 0 si terminó (aunque algún video haya fallado)."""
    gold = extraction_eval.load_gold(args.gold)
    samples = extraction_eval.load_sample_videos(args.samples_dir)
    ids = select_video_ids(gold, samples, args.limit, args.only_reviewed)
    if not ids:
        logger.error("[scripts.eval_extraction.run] Ningún video para evaluar (revisa --gold y --samples-dir)")
        return 1

    if args.extractor in ("claude_code", "claude_code_v2"):
        # Solo lee las predicciones que dejó `scripts.run_claude_pilot`; nunca llama a ningún LLM.
        args.rescore_only = True
        model = args.model or "sonnet"
    else:
        model = args.model or get_ollama_model()
    # profile_llm_guests guarda aparte lo que propone el LLM (`llm_guests_*.json`) y reutiliza los
    # veredictos de profile_llm (solo lectura), así cada variante se re-puntúa sin repetir llamadas.
    cache_name = {"profile_llm_guests": "llm_guests", "profile_llm_simple": "simple_guests"}.get(
        args.extractor, args.extractor,
    )
    path = cache_path(args.out_dir, cache_name, model)
    catalogs = {"programs": [], "hosts": []} if args.no_catalog else gold_catalogs(gold)
    if args.extractor == "profile":
        cache = profile_predictions(samples, ids, catalogs)
        model = "(sin LLM)"
    else:
        cache = load_cache(path)
    video_series: dict[str, str] = {}
    profiles: dict[str, series_profile.SeriesProfile] = {}
    verdict_cache: dict[str, dict] = {}
    if args.extractor in ("profile_llm", *SECOND_OPINION):
        video_series, profiles = series_profile.build_profiles(
            samples, catalogs["programs"], catalogs["hosts"],
        )
    if args.extractor in SECOND_OPINION:
        verdict_cache = load_cache(cache_path(args.out_dir, "profile_llm", model))

    def is_done(video_id: str) -> bool:
        entry = cache.get(video_id)
        if entry is None:
            return False
        # Una entrada de profile_llm guardada con la predicción final (versión anterior) se rehace.
        if args.extractor in SECOND_OPINION:
            return "llm_guests" in entry or "error" in entry
        return args.extractor != "profile_llm" or "verdicts" in entry or "error" in entry

    pending = [i for i in ids if not is_done(i)]
    if pending and not args.rescore_only:
        base_url = args.base_url or get_ollama_base_url()
        own_client = client is None
        client = client or httpx.Client()
        try:
            for n, video_id in enumerate(pending, start=1):
                started = time.monotonic()
                video = samples[video_id]
                try:
                    if args.extractor == "profile_llm":
                        cache[video_id] = {"verdicts": profile_llm_verdicts(
                            client, base_url, model, video, catalogs,
                            profiles.get(video_series.get(video_id, "")),
                        )}
                    elif args.extractor == "profile_llm_guests":
                        cache[video_id] = {"llm_guests": llm_guests_entry(client, base_url, model, video, catalogs)}
                    elif args.extractor == "profile_llm_simple":
                        cache[video_id] = {"llm_guests": simple_guests_entry(client, base_url, model, video)}
                    else:
                        pred = baseline_predict(
                            client, base_url, model, video["title"], video["description"], catalogs,
                        )
                        cache[video_id] = {"guests": pred.guests, "hosts": pred.hosts, "program": pred.program}
                except Exception as exc:  # noqa: BLE001 - un video fallido no detiene la evaluación
                    logger.warning("[scripts.eval_extraction.run] %s falló: %s", video_id, exc)
                    cache[video_id] = {"guests": [], "hosts": [], "program": "", "error": str(exc)}
                save_cache(path, cache)
                logger.info("[%d/%d] %s (%.0f s)", n, len(pending), video_id, time.monotonic() - started)
        finally:
            if own_client:
                client.close()

    evaluated = [i for i in ids if is_done(i)]
    policy = {
        "promote_hashtags": args.promote_hashtags, "allow_host_verdict": args.llm_host_verdict,
    }

    def prediction_for(video_id: str) -> Prediction:
        entry = cache[video_id]
        if args.extractor == "profile_llm":
            entry = profile_llm_prediction(
                samples[video_id], catalogs, profiles.get(video_series.get(video_id, "")),
                entry.get("verdicts", []), policy,
            )
        elif args.extractor in SECOND_OPINION:
            base = profile_llm_prediction(
                samples[video_id], catalogs, profiles.get(video_series.get(video_id, "")),
                verdict_cache.get(video_id, {}).get("verdicts", []), policy,
            )
            entry = second_opinion_prediction(
                base, samples[video_id], entry.get("llm_guests", []), catalogs, args.second_opinion_mode,
            )
        return Prediction(entry["guests"], entry["hosts"], entry.get("program", ""))

    scores = [extraction_eval.score_video(i, gold[i], prediction_for(i)) for i in evaluated]
    errors = [i for i in evaluated if cache[i].get("error")]
    print(f"Extractor: {args.extractor} | modelo: {model} | catálogos simulados: {not args.no_catalog}")
    print(f"Videos evaluados: {len(evaluated)} de {len(ids)} pedidos; con error del LLM: {len(errors)}")
    if args.extractor in ("profile_llm", *SECOND_OPINION):
        print(f"Política del LLM: {policy} (por defecto solo puede descartar lo que no es persona)")
    if args.extractor in SECOND_OPINION:
        print(f"Segunda opinión de invitados del LLM: modo {args.second_opinion_mode} (con evidencia literal en el texto)")
    if len(evaluated) < len(ids):
        print("(faltan videos: corre otra vez sin --rescore-only para completarlos)")
    print()
    print(extraction_eval.format_report(scores))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evalúa el extractor contra la referencia de invitados.")
    p.add_argument("--extractor", choices=EXTRACTORS, default="baseline")
    p.add_argument("--limit", type=int, default=None, help="Evaluar solo los primeros N videos")
    p.add_argument("--only-reviewed", action="store_true", help="Solo videos revisados por el usuario")
    p.add_argument("--rescore-only", action="store_true", help="No llamar al LLM; usar solo el caché")
    p.add_argument("--promote-hashtags", action="store_true",
                   help="profile_llm: el LLM puede subir hashtags sin rol a invitado")
    p.add_argument("--llm-host-verdict", action="store_true",
                   help="profile_llm: el LLM puede mover nombres a conductores")
    p.add_argument("--second-opinion-mode", choices=("union", "fallback"), default="union",
                   help="profile_llm_guests / profile_llm_simple: union = siempre suma lo que el LLM encontró; "
                        "fallback = solo si las reglas no encontraron a nadie")
    p.add_argument("--no-catalog", action="store_true", help="Catálogos de conductores/programas vacíos")
    p.add_argument("--model", default=None, help="Modelo de Ollama (por defecto OLLAMA_MODEL); con claude_code, el alias usado en el piloto")
    p.add_argument("--base-url", default=None, help="URL de Ollama (por defecto OLLAMA_BASE_URL)")
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except EvalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
