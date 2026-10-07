"""Fase 3, paso 6: orquestador idempotente (reglas de regex + LLM -> candidatos en staging).

`process_video` procesa un video a la vez: regex (paso 4) -> LLM (paso 5) -> filas en staging
(paso 2). `run_batch` lo aplica a un lote de videos nuevos del canal, sin detenerse si uno
falla (`IngestionRunError`) y sin reprocesar lo ya hecho (`Video.last_ingested_at`). Se dispara
a demanda desde la app o por script (todavía sin ninguno de los dos).

Todo lo que este módulo guarda en staging sigue siendo candidato: nada se vuelve invitado,
contacto o participación final sin pasar por Staging Review (paso 7, todavía sin implementar).
"""
import logging
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_ollama_base_url, get_ollama_model, get_youtube_api_key
from app.models.catalogs import Borough, GuestCategory, Host, Program, VideoType
from app.models.ingestion import (
    IngestionRun, IngestionRunError, StagingContactCandidate, StagingGuestCandidate,
    StagingVideoSuggestion,
)
from app.models.video import Video
from app.services import candidate_classifier, ollama_client, regex_rules, series_profile
from app.services.candidate_classifier import CandidateClassification, ClassifierError
from app.services.catalogs import normalize_name
from app.services.ingestion import sync_videos
from app.services.youtube_client import YouTubeError, get_uploads_playlist_id, list_video_ids

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 30
# Mismo canal que backend/scripts/sample_videos.py; el sistema es de un solo canal, no
# multi-tenant, así que no se guarda como variable de entorno.
CHANNEL_HANDLE = "xlivemedios"

# Duplicados reales: minutos a una semana de diferencia; episodios distintos de un programa
# recurrente con descripción idéntica: meses (evidencia real de 150 videos, ver
# docs/PHASE3_PLAN.md). 14 días separa ambos casos con margen.
DUPLICATE_MAX_TIMEDELTA = timedelta(days=14)

# Ajuste de confianza (regla del pipeline: título+descripción a favor, solo descripción
# neutro, ambigüedad persona/banda en contra). Valores iniciales, ajustables tras validar
# con resultados reales del modelo.
_CONFIDENCE_BOTH_BONUS = 0.15
_CONFIDENCE_TITLE_ONLY_BONUS = 0.10
_CONFIDENCE_GROUP_PENALTY = 0.20

# Confianza de los patrones de nombre por regex (paso 4). Los 3 de formato son "confianza
# baja/media" según PHASE3_PLAN.md; "high_signal" (frase explícita: "Invitado:", "presenta
# a", "es el nombre/seudónimo artístico de"...) es más confiable, similar a la confianza alta
# que el prompt del LLM le pide para esos mismos casos. Valores iniciales, ajustables igual
# que los de arriba.
_REGEX_NAME_CONFIDENCE = {
    "after_colon": 0.35, "con_nombre": 0.40, "uppercase_parens": 0.30, "high_signal": 0.65,
}
# Segunda opinión del LLM (prompt simple; solo si las reglas no encontraron a nadie): el valor más
# bajo que ya existía (`uppercase_parens`), aprobado por el usuario el 2026-10-02. Sus candidatos
# quedan al final de la lista de cada video en Staging Review.
_LLM_SECOND_OPINION_CONFIDENCE = 0.30
# Los contactos por regex son patrones explícitos (URL, ETIQUETA:, correo), no ambiguos como
# los nombres por formato; confianza inicial más alta que la de esos 3 patrones.
_REGEX_CONTACT_CONFIDENCE = 0.7


def _adjust_confidence(
    raw: float, found_in_title: bool, found_in_description: bool, is_possible_group: bool
) -> float:
    adjustment = 0.0
    if found_in_title and found_in_description:
        adjustment += _CONFIDENCE_BOTH_BONUS
    elif found_in_title:
        adjustment += _CONFIDENCE_TITLE_ONLY_BONUS
    if is_possible_group:
        adjustment -= _CONFIDENCE_GROUP_PENALTY
    return max(0.0, min(1.0, raw + adjustment))


def _active_names(db: Session, model) -> list[str]:
    return list(db.scalars(select(model.name).where(model.is_active.is_(True))))


SeriesContext = tuple[dict[int, str], dict[str, series_profile.SeriesProfile]]

# Fuente de cada invitado de `series_profile` -> clave de `_REGEX_NAME_CONFIDENCE`. Se reutilizan
# los valores que ya existían (no se agrega ningún umbral nuevo): lo que el texto anuncia con
# palabras ("invitado X", "presentamos a X") equivale a la alta señal; lo que solo sigue a los dos
# puntos del título, al patrón de formato `after_colon`.
_GUEST_SOURCE_CONFIDENCE_KEY = {
    "title_guest": "high_signal", "description_guest": "high_signal", "title_after_colon": "after_colon",
}


def _build_series(db: Session) -> SeriesContext:
    """Perfiles por serie con TODOS los videos que ya están en la BD (mientras más haya
    sincronizados, mejor detecta la recurrencia de los conductores)."""
    rows = db.execute(select(Video.id, Video.title, Video.description)).all()
    videos = {r.id: {"title": r.title, "description": r.description or ""} for r in rows}
    return series_profile.build_profiles(videos, _active_names(db, Program), _active_names(db, Host))


def _refine_hints(
    ollama_http_client: httpx.Client, base_url: str, model: str, video: Video,
    hints: series_profile.VideoHints, known_hosts: list[str],
) -> series_profile.VideoHints:
    """Etapa 2: el LLM solo descarta lo que no es persona. Si falla, no se pierde el video: se
    conservan los candidatos de las reglas sin filtrar."""
    try:
        return candidate_classifier.refine(
            ollama_http_client, base_url, model, video.title, video.description, hints, known_hosts,
        )
    except ClassifierError as exc:
        logger.warning(
            "[app.services.pipeline._refine_hints] %s: se conservan los candidatos sin filtrar (%s)",
            video.youtube_video_id, exc,
        )
        return candidate_classifier.apply_verdicts(hints, CandidateClassification(), video.description)


def _second_opinion_names(
    ollama_http_client: httpx.Client, base_url: str, model: str, video: Video,
    refined: series_profile.VideoHints, excluded: list[str],
) -> list[str]:
    """Invitados que el LLM encuentra con UNA sola pregunta cuando las reglas no hallaron a nadie
    (modo `fallback`; medido el 2026-10-02 en 150 videos: recall de invitados 84.3 % -> 90.2 %).

    Solo se aceptan nombres que aparecen literales en el texto y que no son conductores ni
    programas. Si el LLM falla no se pierde el video: simplemente no hay segunda opinión.
    """
    if refined.guests:
        return []
    try:
        llm_names = candidate_classifier.simple_guest_names(
            ollama_http_client, base_url, model, video.title, video.description,
        )
    except ClassifierError as exc:
        logger.warning(
            "[app.services.pipeline._second_opinion_names] %s: sin segunda opinión (%s)",
            video.youtube_video_id, exc,
        )
        return []
    return candidate_classifier.second_opinion_guests(
        [], llm_names, f"{video.title}\n{video.description or ''}", excluded=excluded, mode="fallback",
    )


def _suggestion_payload(
    hints: series_profile.VideoHints, profile: series_profile.SeriesProfile | None,
) -> dict:
    """Lo que se propone de un video para revisarlo: programa (solo del catálogo), conductores que
    el texto menciona, nombres dudosos (con la pista del LLM) y los conductores habituales de la
    serie que el texto NO menciona (se ofrecen, nunca se asignan solos)."""
    host_names = [h.name for h in hints.hosts]
    mentioned = {series_profile.compact(n) for n in host_names}
    usual = [name for key, name in (profile.hosts.items() if profile else []) if key not in mentioned]
    doubtful = [
        {"name": u.name, "guess": u.role if u.role in ("guest", "host") else "unknown"}
        for u in hints.unknown
    ]
    return {
        "program_name": hints.program or None, "host_names": host_names,
        "doubtful_names": doubtful, "usual_host_names": usual,
    }


def _save_video_suggestion(
    db: Session, video: Video, run_id: int | None, hints: series_profile.VideoHints,
    profile: series_profile.SeriesProfile | None = None,
) -> bool:
    """Guarda la sugerencia del video para que un humano la revise (Staging Review). No hace
    commit. Devuelve si creó la fila (no crea nada si no hay qué sugerir o ya existe)."""
    payload = _suggestion_payload(hints, profile)
    if not any(payload.values()):
        return False
    if db.scalar(select(StagingVideoSuggestion.id).where(StagingVideoSuggestion.video_id == video.id)) is not None:
        return False
    db.add(StagingVideoSuggestion(video_id=video.id, ingestion_run_id=run_id, **payload))
    return True


def backfill_video_suggestions(db: Session) -> int:
    """Crea (o completa) la sugerencia de los videos que ya se ingirieron, solo con reglas, sin LLM.

    - Videos ingeridos sin sugerencia: se crea.
    - Sugerencias pendientes sin dudosos ni conductores habituales (creadas antes de que esos
      campos existieran): se completan. Los dudosos de este camino no pasan por el filtro del LLM,
      así que pueden incluir etiquetas que no son personas; `reprocess_unreviewed_videos` los rehace
      con el LLM.
    Idempotente. Devuelve cuántas creó o completó.
    """
    video_series, profiles = _build_series(db)
    programs, hosts = _active_names(db, Program), _active_names(db, Host)
    existing = {s.video_id: s for s in db.scalars(select(StagingVideoSuggestion))}
    changed = 0
    for video in db.scalars(select(Video).where(Video.last_ingested_at.is_not(None))).all():
        profile = profiles.get(video_series.get(video.id, ""))
        suggestion = existing.get(video.id)
        if suggestion is not None and (
            suggestion.status != "pending" or suggestion.doubtful_names or suggestion.usual_host_names
        ):
            continue
        hints = series_profile.extract_hints(video.title, video.description, programs, profile, hosts)
        if suggestion is None:
            changed += _save_video_suggestion(db, video, None, hints, profile)
            continue
        payload = _suggestion_payload(hints, profile)
        if payload["doubtful_names"] or payload["usual_host_names"]:
            suggestion.doubtful_names = payload["doubtful_names"]
            suggestion.usual_host_names = payload["usual_host_names"]
            changed += 1
    db.commit()
    logger.info("[app.services.pipeline.backfill_video_suggestions] %d sugerencias creadas o completadas", changed)
    return changed


def reprocess_unreviewed_videos(
    db: Session, ollama_http_client: httpx.Client, ollama_base_url: str, ollama_model: str,
    dry_run: bool = True,
) -> dict:
    """Vuelve a procesar con el extractor actual los videos que NADIE ha revisado todavía.

    Un video entra solo si todos sus candidatos de invitado y de contacto y su sugerencia siguen
    `pending` (o no tiene ninguno), su estado sigue "pendiente" (un video marcado "sin invitados"
    no se toca: podría ser decisión de una persona) y no tiene programa asignado. Se borran esos
    candidatos pendientes
    (son regenerables) y se vuelve a correr `process_video`. Lo ya aceptado o rechazado por una
    persona no se toca. Con `dry_run=True` solo cuenta lo que haría. Devuelve
    {"videos": [...], "reprocessed": n, "errors": [...]}.
    """
    reviewed_video_ids = set(db.scalars(
        select(StagingGuestCandidate.video_id).where(StagingGuestCandidate.status != "pending")
    )) | set(db.scalars(
        select(StagingContactCandidate.video_id).where(StagingContactCandidate.status != "pending")
    )) | set(db.scalars(
        select(StagingVideoSuggestion.video_id).where(StagingVideoSuggestion.status != "pending")
    ))
    videos = [
        v for v in db.scalars(select(Video).where(Video.last_ingested_at.is_not(None))).all()
        if v.id not in reviewed_video_ids and v.guest_status == "pending" and v.program_id is None
    ]
    result: dict = {"videos": [v.youtube_video_id for v in videos], "reprocessed": 0, "errors": []}
    if dry_run or not videos:
        return result

    for video in videos:
        for model in (StagingGuestCandidate, StagingContactCandidate, StagingVideoSuggestion):
            for row in db.scalars(select(model).where(model.video_id == video.id)).all():
                db.delete(row)
        video.last_ingested_at = None
    db.commit()

    series = _build_series(db)
    for video in videos:
        try:
            process_video(db, ollama_http_client, ollama_base_url, ollama_model, video, series=series)
            result["reprocessed"] += 1
        except Exception as exc:  # noqa: BLE001 - un video fallido no detiene el resto
            db.rollback()
            result["errors"].append({"video": video.youtube_video_id, "error": str(exc)})
            logger.warning(
                "[app.services.pipeline.reprocess_unreviewed_videos] Error en %s: %s",
                video.youtube_video_id, exc,
            )
    return result


def _name_found_where(name: str, title: str, description: str | None) -> tuple[bool, bool]:
    normalized = normalize_name(name)
    return normalized in normalize_name(title), normalized in normalize_name(description or "")


def _normalize_for_duplicate_check(text: str) -> str:
    """`normalize_name` + quita emoji/símbolos (categoría Unicode "So").

    Caso real (evidencia de la primera corrida real): el canal sube el mismo video dos veces
    con el único cambio de un emoji al final del título (p. ej. "...Arween Tarot" vs
    "...Arween Tarot 📱"), segundos o minutos aparte y con la descripción idéntica byte por
    byte. `normalize_name` (pensado para nombres de catálogo) no toca emoji, así que sin esto
    esos pares nunca se detectaban como duplicados.
    """
    without_symbols = "".join(c for c in text if unicodedata.category(c) != "So")
    return normalize_name(without_symbols)


def _find_possible_duplicate(db: Session, video: Video) -> Video | None:
    """Otro video con título+descripción normalizados iguales y published_at cercano."""
    if video.published_at is None:
        return None
    title_key = _normalize_for_duplicate_check(video.title)
    description_key = _normalize_for_duplicate_check(video.description or "")
    window_start = video.published_at - DUPLICATE_MAX_TIMEDELTA
    window_end = video.published_at + DUPLICATE_MAX_TIMEDELTA
    candidates = db.scalars(
        select(Video)
        .where(
            Video.id != video.id,
            Video.published_at.is_not(None),
            Video.published_at >= window_start,
            Video.published_at <= window_end,
        )
        .order_by(Video.published_at)
    )
    for other in candidates:
        if (
            _normalize_for_duplicate_check(other.title) == title_key
            and _normalize_for_duplicate_check(other.description or "") == description_key
        ):
            return other
    return None


def process_video(
    db: Session,
    ollama_http_client: httpx.Client,
    ollama_base_url: str,
    ollama_model: str,
    video: Video,
    ingestion_run: IngestionRun | None = None,
    series: SeriesContext | None = None,
) -> None:
    """Analiza un video y guarda sus candidatos en staging. Hace commit.

    Invitados: reglas por serie (`series_profile`) + el LLM solo descarta lo que no es persona
    (`candidate_classifier`); si las reglas no encuentran a nadie, una segunda opinión del LLM con
    una sola pregunta (`_second_opinion_names`, confianza baja). Contactos, categorías, tipo de video y alcaldía: `analyze_video`.
    `series` son los perfiles ya calculados para el lote (`_build_series`); si no se pasan, se
    calculan aquí. El programa (solo del catálogo) y los conductores que detecta `series_profile`
    se guardan como sugerencia (`StagingVideoSuggestion`) para revisarlos en Staging Review.

    Idempotente: si el video ya se procesó (`last_ingested_at`), no hace nada.
    """
    if video.last_ingested_at is not None:
        logger.info(
            "[app.services.pipeline.process_video] Video %s ya procesado, se omite",
            video.youtube_video_id,
        )
        return

    run_id = ingestion_run.id if ingestion_run else None

    analysis = ollama_client.analyze_video(
        ollama_http_client, ollama_base_url, ollama_model, video.title, video.description,
        existing_categories=_active_names(db, GuestCategory),
        existing_video_types=_active_names(db, VideoType),
        existing_boroughs=_active_names(db, Borough),
        existing_hosts=_active_names(db, Host),
        existing_programs=_active_names(db, Program),
    )

    video_series, profiles = series if series is not None else _build_series(db)
    profile = profiles.get(video_series.get(video.id, ""))
    host_names = _active_names(db, Host)
    program_names = _active_names(db, Program)
    hints = series_profile.extract_hints(
        video.title, video.description, program_names, profile, host_names,
    )
    refined = _refine_hints(
        ollama_http_client, ollama_base_url, ollama_model, video, hints,
        list(profile.hosts.values()) if profile else [],
    )
    second_opinion = _second_opinion_names(
        ollama_http_client, ollama_base_url, ollama_model, video, refined,
        excluded=[*(h.name for h in refined.hosts), *host_names, *program_names, refined.program],
    )
    if second_opinion:
        # Lo que el LLM ya propone como invitado deja de ser "dudoso".
        taken = {series_profile.compact(n) for n in second_opinion}
        refined = series_profile.VideoHints(
            program=refined.program, hosts=refined.hosts, guests=refined.guests,
            unknown=[u for u in refined.unknown if series_profile.compact(u.name) not in taken],
        )

    _save_video_suggestion(db, video, run_id, refined, profile)

    # Categoría y "posible grupo" salen del análisis del LLM, solo cuando es el mismo nombre.
    analysis_guests = {series_profile.compact(g.name): g for g in analysis.guests}
    for guest in refined.guests:
        found_in_title, found_in_description = _name_found_where(
            guest.name, video.title, video.description
        )
        raw = _REGEX_NAME_CONFIDENCE[_GUEST_SOURCE_CONFIDENCE_KEY.get(guest.source, "after_colon")]
        llm_guest = analysis_guests.get(series_profile.compact(guest.name))
        is_group = llm_guest.is_possible_group if llm_guest else False
        db.add(StagingGuestCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            extracted_name=guest.name, found_in_title=found_in_title,
            found_in_description=found_in_description, is_possible_group=is_group,
            category_match=llm_guest.category_match if llm_guest else None,
            category_is_new_suggestion=llm_guest.category_is_new_suggestion if llm_guest else False,
            raw_confidence=raw,
            adjusted_confidence=_adjust_confidence(raw, found_in_title, found_in_description, is_group),
            evidence=guest.evidence or guest.name, extraction_method="regex",
        ))

    for name in second_opinion:
        found_in_title, found_in_description = _name_found_where(name, video.title, video.description)
        llm_guest = analysis_guests.get(series_profile.compact(name))
        is_group = llm_guest.is_possible_group if llm_guest else False
        db.add(StagingGuestCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            extracted_name=name, found_in_title=found_in_title,
            found_in_description=found_in_description, is_possible_group=is_group,
            category_match=llm_guest.category_match if llm_guest else None,
            category_is_new_suggestion=llm_guest.category_is_new_suggestion if llm_guest else False,
            raw_confidence=_LLM_SECOND_OPINION_CONFIDENCE,
            adjusted_confidence=_adjust_confidence(
                _LLM_SECOND_OPINION_CONFIDENCE, found_in_title, found_in_description, is_group,
            ),
            evidence=name, extraction_method="llm",
        ))

    for contact in regex_rules.extract_contacts(video.description):
        db.add(StagingContactCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            type_hint=contact.type_hint, value=contact.value,
            raw_confidence=_REGEX_CONTACT_CONFIDENCE, extraction_method="regex",
        ))

    for contact in analysis.contacts:
        db.add(StagingContactCandidate(
            video_id=video.id, ingestion_run_id=run_id,
            type_hint=contact.type_hint, value=contact.value,
            raw_confidence=contact.raw_confidence, extraction_method="llm",
        ))

    # "Sin invitados" (FR-014): candidato automático de la regla de regex (CLAUDE.md: "la IA lo
    # marca 'sin invitados', reclasificable por un humano"). La opinión del LLM no se persiste
    # aparte: es solo una señal adicional para Staging Review, no reemplaza esta regla.
    if regex_rules.is_no_guests_candidate(video.title, video.description):
        video.guest_status = "no_guests"

    duplicate = _find_possible_duplicate(db, video)
    if duplicate is not None:
        video.possible_duplicate_of_video_id = duplicate.id

    video.last_ingested_at = datetime.now(timezone.utc)
    db.commit()


def run_batch(
    db: Session,
    youtube_http_client: httpx.Client,
    youtube_api_key: str,
    ollama_http_client: httpx.Client,
    ollama_base_url: str,
    ollama_model: str,
    handle: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    trigger: str = "manual",
) -> IngestionRun:
    """Corre el pipeline completo sobre hasta `batch_size` videos nuevos del canal.

    No detiene el lote si un video falla: registra el error (`IngestionRunError`) y sigue con
    el siguiente. Nunca reprocesa un video que ya tenga `last_ingested_at`.
    """
    run = IngestionRun(trigger=trigger, requested_batch_size=batch_size)
    db.add(run)
    db.commit()

    try:
        playlist_id = get_uploads_playlist_id(youtube_http_client, youtube_api_key, handle)
        all_video_ids = list_video_ids(youtube_http_client, youtube_api_key, playlist_id)
    except YouTubeError as exc:
        return _fail_run(db, run, "(canal)", exc)

    already_ingested = set(db.scalars(
        select(Video.youtube_video_id).where(
            Video.youtube_video_id.in_(all_video_ids), Video.last_ingested_at.is_not(None)
        )
    ))
    pending_ids = [vid for vid in all_video_ids if vid not in already_ingested][:batch_size]

    if pending_ids:
        try:
            sync_videos(db, youtube_http_client, youtube_api_key, pending_ids)
        except YouTubeError as exc:
            return _fail_run(db, run, "(lote)", exc)

    videos = list(db.scalars(select(Video).where(Video.youtube_video_id.in_(pending_ids))))
    series = _build_series(db) if videos else None  # una vez por lote, con los videos ya sincronizados

    for video in videos:
        try:
            process_video(
                db, ollama_http_client, ollama_base_url, ollama_model, video, ingestion_run=run,
                series=series,
            )
            run.success_count += 1
        except Exception as exc:  # noqa: BLE001 - resiliencia por video, a propósito (paso 6)
            db.rollback()
            db.add(IngestionRunError(
                ingestion_run_id=run.id, youtube_video_id=video.youtube_video_id,
                error_message=str(exc),
            ))
            run.error_count += 1
            logger.warning(
                "[app.services.pipeline.run_batch] Error en %s: %s",
                video.youtube_video_id, exc,
            )
        run.processed_count += 1
        db.commit()

    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run


def trigger_manual_run(db: Session, batch_size: int = DEFAULT_BATCH_SIZE) -> IngestionRun:
    """Dispara una corrida manual (botón "Ingesta" de la app): arma los clientes HTTP y la
    configuración desde variables de entorno y llama a `run_batch`.

    Lanza `RuntimeError` (mensaje claro) si falta `YOUTUBE_API_KEY` u `OLLAMA_MODEL`, antes de
    crear ningún `IngestionRun`.
    """
    api_key = get_youtube_api_key()
    ollama_base_url = get_ollama_base_url()
    ollama_model = get_ollama_model()
    with httpx.Client() as youtube_client, httpx.Client() as ollama_http_client:
        return run_batch(
            db, youtube_client, api_key, ollama_http_client, ollama_base_url, ollama_model,
            CHANNEL_HANDLE, batch_size=batch_size, trigger="manual",
        )


def _fail_run(db: Session, run: IngestionRun, where: str, exc: Exception) -> IngestionRun:
    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    db.add(IngestionRunError(ingestion_run_id=run.id, youtube_video_id=where, error_message=str(exc)))
    db.commit()
    logger.error("[app.services.pipeline.run_batch] %s", exc)
    return run
