"""Staging Review por video: lista de videos con sus candidatos y resolución en un solo paso.

Reutiliza `app.services.staging` (aceptar/rechazar un candidato) para no duplicar validaciones:
aceptar crea o vincula un `Guest` y su `Participation`; nada se vuelve dato final sin que un
humano lo apruebe. Un video entra a la revisión cuando ya lo procesó la ingesta
(`last_ingested_at`).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.catalogs import Host, Program
from app.models.guest import Guest
from app.models.ingestion import (
    StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion,
)
from app.models.video import Video
from app.schemas.catalogs import CatalogCreate
from app.schemas.guests import GuestCreate
from app.schemas.participations import ParticipationCreate
from app.schemas.staging import GuestCandidateAccept, ReviewResolve
from app.services import catalogs as catalogs_service
from app.services import guests as guests_service
from app.services import participations as participations_service
from app.services import staging as staging_service
from app.services.catalogs import normalize_name
from app.services.guests import InvalidReferenceError
from app.services.participations import ParticipationDuplicateError
from app.services.videos import VideoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
REVIEW_FILTERS = (
    "pending", "with_contacts", "doubtful_contacts", "no_candidates", "no_guests", "duplicates",
)


class ReviewInputError(ValueError):
    """La resolución enviada no es coherente (candidato de otro video, contradicciones…)."""


def _pending_guest_exists():
    return exists().where(
        StagingGuestCandidate.video_id == Video.id, StagingGuestCandidate.status == "pending"
    )


def _pending_contact_exists():
    return exists().where(
        StagingContactCandidate.video_id == Video.id, StagingContactCandidate.status == "pending"
    )


def _pending_suggestion_exists():
    return exists().where(
        StagingVideoSuggestion.video_id == Video.id, StagingVideoSuggestion.status == "pending"
    )


MOBILE_MARK = "📱"


def _duplicate_copy_clause():
    """El video es la COPIA de un par de posibles duplicados y no la que se conserva.

    El canal sube el mismo video dos veces, una con 📱 al final del título, y la ingesta marca cada
    uno como duplicado del otro. Se conserva el que no tiene 📱; si los dos son iguales en eso, el
    de menor id. La copia no se borra: sale de la cola de revisión y se consulta en "Posibles
    duplicados".
    """
    original = aliased(Video)
    mobile = Video.title.contains(MOBILE_MARK)
    original_mobile = original.title.contains(MOBILE_MARK)
    return exists().where(
        original.id == Video.possible_duplicate_of_video_id,
        or_(
            and_(mobile, ~original_mobile),
            and_(or_(and_(mobile, original_mobile), and_(~mobile, ~original_mobile)),
                 Video.id > original.id),
        ),
    )


def _filter_clause(review_filter: str):
    if review_filter == "pending":
        # Pendiente = invitados candidatos o una sugerencia de programa/conductores sin revisar.
        return or_(_pending_guest_exists(), _pending_suggestion_exists())
    if review_filter == "with_contacts":
        return _pending_contact_exists()
    if review_filter == "doubtful_contacts":
        return exists().where(
            StagingContactCandidate.video_id == Video.id,
            StagingContactCandidate.status == "pending",
            StagingContactCandidate.doubtful.is_(True),
        )
    if review_filter == "no_candidates":
        return (
            ~_pending_guest_exists() & ~_pending_contact_exists() & ~_pending_suggestion_exists()
            & (Video.guest_status == "pending")
        )
    if review_filter == "no_guests":
        return Video.guest_status == "no_guests"
    if review_filter == "duplicates":
        return _duplicate_copy_clause()
    msg = f"Filtro de revisión desconocido: {review_filter!r}"
    logger.error("[app.services.staging_review._filter_clause] %s", msg)
    raise ReviewInputError(msg)


def _base_filters(review_filter: str, q: str | None) -> list:
    filters = [Video.last_ingested_at.is_not(None), _filter_clause(review_filter)]
    if review_filter != "duplicates":
        filters.append(~_duplicate_copy_clause())   # las copias no se revisan
    if q and q.strip():
        filters.append(Video.title.ilike(f"%{q.strip()}%"))
    return filters


def review_counts(db: Session, q: str | None = None) -> dict[str, int]:
    """Contador de videos por filtro (respeta la búsqueda `q`)."""
    return {
        name: db.execute(select(func.count(Video.id)).where(*_base_filters(name, q))).scalar_one()
        for name in REVIEW_FILTERS
    }


def list_review_videos(
    db: Session, review_filter: str = "pending", q: str | None = None, page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[dict], int]:
    """Videos del filtro, con sus candidatos PENDIENTES (invitados por confianza, contactos)."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    filters = _base_filters(review_filter, q)
    total = db.execute(select(func.count(Video.id)).where(*filters)).scalar_one()
    videos = list(db.execute(
        select(Video).where(*filters)
        .order_by(Video.published_at.desc().nulls_last(), Video.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    ).scalars())
    ids = [v.id for v in videos]
    copy_ids = set(db.execute(
        select(Video.id).where(Video.id.in_(ids), _duplicate_copy_clause())
    ).scalars()) if ids else set()

    guests_by_video: dict[int, list] = {i: [] for i in ids}
    contacts_by_video: dict[int, list] = {i: [] for i in ids}
    if ids:
        for cand in db.execute(
            select(StagingGuestCandidate)
            .where(StagingGuestCandidate.video_id.in_(ids), StagingGuestCandidate.status == "pending")
            .order_by(StagingGuestCandidate.adjusted_confidence.desc(), StagingGuestCandidate.id)
        ).scalars():
            guests_by_video[cand.video_id].append(cand)
        for cand in db.execute(
            select(StagingContactCandidate)
            .where(StagingContactCandidate.video_id.in_(ids), StagingContactCandidate.status == "pending")
            .order_by(StagingContactCandidate.id)
        ).scalars():
            contacts_by_video[cand.video_id].append(cand)

    suggestions = {
        sug.video_id: sug for sug in db.execute(
            select(StagingVideoSuggestion).where(
                StagingVideoSuggestion.video_id.in_(ids), StagingVideoSuggestion.status == "pending"
            )
        ).scalars()
    } if ids else {}
    program_id_by_name = {
        normalize_name(p.name): p.id
        for p in db.execute(select(Program).where(Program.is_active.is_(True))).scalars()
    }

    def suggested_program_id(suggestion) -> int | None:
        if suggestion is None or not suggestion.program_name:
            return None
        return program_id_by_name.get(normalize_name(suggestion.program_name))

    # Conductores del catálogo de los programas que aparecen: el asignado y el sugerido.
    program_ids = {v.program_id for v in videos if v.program_id is not None}
    program_ids |= {pid for pid in map(suggested_program_id, suggestions.values()) if pid is not None}
    host_names_by_program = {
        program.id: sorted(h.name for h in program.hosts if h.is_active)
        for program in db.execute(
            select(Program).where(Program.id.in_(program_ids)).options(selectinload(Program.hosts))
        ).scalars()
    } if program_ids else {}

    items = []
    for v in videos:
        suggestion = suggestions.get(v.id)
        suggested_id = suggested_program_id(suggestion)
        suggested_hosts = list(suggestion.host_names or []) if suggestion else []
        # Habituales para un clic: los de la serie guardados en la sugerencia más los del catálogo
        # del programa (asignado o sugerido), sin repetir los que el texto ya menciona.
        usual: list[str] = []
        taken = {normalize_name(n) for n in suggested_hosts}
        candidates = [
            *(suggestion.usual_host_names or [] if suggestion else []),
            *host_names_by_program.get(v.program_id or suggested_id, []),
        ]
        for name in candidates:
            if normalize_name(name) not in taken:
                taken.add(normalize_name(name))
                usual.append(name)
        items.append({
            "id": v.id, "youtube_video_id": v.youtube_video_id, "title": v.title,
            "description": v.description, "published_at": v.published_at,
            "guest_status": v.guest_status,
            "possible_duplicate_of_video_id": v.possible_duplicate_of_video_id,
            "is_duplicate_copy": v.id in copy_ids,
            "program_id": v.program_id,
            "suggested_program_id": suggested_id,
            "suggested_host_names": suggested_hosts,
            "program_host_names": host_names_by_program.get(v.program_id, []),
            "doubtful_names": list(suggestion.doubtful_names or []) if suggestion else [],
            "usual_host_names": usual,
            "guest_candidates": guests_by_video[v.id],
            "contact_candidates": contacts_by_video[v.id],
        })
    return items, total


def _find_exact_guest(db: Session, name: str) -> Guest | None:
    """Invitado existente con el mismo nombre (sin acentos ni mayúsculas): se vincula solo, para
    no duplicar (FR-001). Los nombres solo parecidos NO se vinculan solos."""
    key = normalize_name(name)
    for guest in db.execute(select(Guest)).scalars():
        if normalize_name(guest.full_name) == key:
            return guest
    return None


def _link_participation(db: Session, guest_id: int, video_id: int) -> None:
    try:
        participations_service.create_participation(db, guest_id, ParticipationCreate(video_id=video_id))
    except ParticipationDuplicateError:
        logger.info(
            "[app.services.staging_review._link_participation] %s ya participaba en el video %s",
            guest_id, video_id,
        )


def _validated_pending(db: Session, video_id: int, candidate_id: int) -> StagingGuestCandidate:
    candidate = staging_service.get_guest_candidate(db, candidate_id)  # 404 si no existe
    if candidate.video_id != video_id:
        msg = f"El candidato {candidate_id} no pertenece al video {video_id}"
        logger.warning("[app.services.staging_review._validated_pending] %s", msg)
        raise ReviewInputError(msg)
    staging_service._ensure_pending(candidate, "invitado")  # 409 si ya se revisó
    return candidate


def _validated_program_and_hosts(
    db: Session, video: Video, data: ReviewResolve,
) -> tuple[Program | None, list[tuple[str, Host | None]]]:
    """Valida el programa y los conductores ANTES de escribir. Los conductores son del programa:
    sin programa (el que se envía o el que el video ya tiene) no hay dónde guardarlos."""
    program = None
    if data.program_id is not None:
        program = db.get(Program, data.program_id)
        if program is None or (not program.is_active and program.id != video.program_id):
            msg = f"El programa {data.program_id} no existe o está desactivado"
            logger.warning("[app.services.staging_review._validated_program_and_hosts] %s", msg)
            raise InvalidReferenceError(msg)
    host_plan: list[tuple[str, Host | None]] = []
    if data.host_names:
        target = program or (db.get(Program, video.program_id) if video.program_id else None)
        if target is None:
            msg = "Para guardar conductores elige primero el programa del video"
            logger.warning("[app.services.staging_review._validated_program_and_hosts] %s", msg)
            raise ReviewInputError(msg)
        hosts_by_key = {normalize_name(h.name): h for h in db.execute(select(Host)).scalars()}
        for name in data.host_names:
            host = hosts_by_key.get(normalize_name(name))
            if host is not None and not host.is_active:
                msg = f"El conductor {name!r} está desactivado en el catálogo"
                logger.warning("[app.services.staging_review._validated_program_and_hosts] %s", msg)
                raise ReviewInputError(msg)
            host_plan.append((name, host))
    return program, host_plan


def _apply_program_and_hosts(
    db: Session, video: Video, program: Program | None, host_plan: list[tuple[str, Host | None]],
) -> list[int]:
    """Asigna el programa al video y agrega los conductores al programa (sin quitar los que ya
    tenía). Un conductor que no está en el catálogo se crea: lo aprobó un humano."""
    if program is not None:
        video.program_id = program.id
    if not host_plan:
        return []
    target = program or db.get(Program, video.program_id)
    host_ids: list[int] = []
    for name, host in host_plan:
        if host is None:
            host = catalogs_service.create_item(db, Host, CatalogCreate(name=name))
        if host not in target.hosts:
            target.hosts.append(host)
        host_ids.append(host.id)
    return host_ids


def _close_suggestion(db: Session, video_id: int, accepted: bool) -> None:
    """Cierra la sugerencia pendiente del video: aceptada si el humano envió programa o
    conductores, rechazada si los dejó vacíos."""
    suggestion = db.execute(
        select(StagingVideoSuggestion).where(
            StagingVideoSuggestion.video_id == video_id, StagingVideoSuggestion.status == "pending"
        )
    ).scalar_one_or_none()
    if suggestion is not None:
        suggestion.status = "accepted" if accepted else "rejected"
        suggestion.reviewed_at = datetime.now(timezone.utc)


def resolve_video(db: Session, video_id: int, data: ReviewResolve) -> dict:
    """Aplica la decisión del humano sobre un video. Valida todo ANTES de escribir.

    - `guests`: candidatos aceptados (con el nombre ya corregido); se vincula con el invitado
      existente de nombre idéntico, o se crea uno nuevo; se crea su participación en el video.
    - `reject_candidate_ids`: candidatos quitados.
    - `added_guests`: invitados que el humano agrega a mano.
    - `no_guests`: marca el video "sin invitados" y rechaza lo que quede pendiente.
    El estado del video queda `has_guests` si hubo al menos un invitado aceptado o agregado.
    """
    video = db.get(Video, video_id)
    if video is None:
        msg = f"No existe el video {video_id}"
        logger.warning("[app.services.staging_review.resolve_video] %s", msg)
        raise VideoNotFoundError(msg)

    accept_ids = [g.candidate_id for g in data.guests]
    overlap = set(accept_ids) & set(data.reject_candidate_ids)
    if overlap or len(set(accept_ids)) != len(accept_ids):
        msg = f"Candidatos repetidos o aceptados y rechazados a la vez: {sorted(overlap) or accept_ids}"
        logger.warning("[app.services.staging_review.resolve_video] %s", msg)
        raise ReviewInputError(msg)
    if data.no_guests and (data.guests or data.added_guests):
        msg = "No se puede marcar 'sin invitados' y a la vez aceptar o agregar invitados"
        logger.warning("[app.services.staging_review.resolve_video] %s", msg)
        raise ReviewInputError(msg)
    for candidate_id in [*accept_ids, *data.reject_candidate_ids]:
        _validated_pending(db, video_id, candidate_id)
    program, host_plan = _validated_program_and_hosts(db, video, data)

    accepted_guest_ids: list[int] = []
    for item in data.guests:
        candidate = staging_service.get_guest_candidate(db, item.candidate_id)
        name = item.full_name or candidate.extracted_name
        existing_id = item.existing_guest_id
        if existing_id is None:
            match = _find_exact_guest(db, name)
            existing_id = match.id if match is not None else None
        if existing_id is not None:
            accept = GuestCandidateAccept(existing_guest_id=existing_id)
        else:
            accept = GuestCandidateAccept(full_name=name)
        accepted_guest_ids.append(staging_service.accept_guest_candidate(db, item.candidate_id, accept).id)

    rejected = 0
    for candidate_id in data.reject_candidate_ids:
        staging_service.reject_guest_candidate(db, candidate_id)
        rejected += 1

    for added in data.added_guests:
        if added.existing_guest_id is not None:
            guest = guests_service.get_guest(db, added.existing_guest_id)
        else:
            guest = _find_exact_guest(db, added.full_name) or guests_service.create_guest(
                db, GuestCreate(full_name=added.full_name)
            )
        _link_participation(db, guest.id, video_id)
        accepted_guest_ids.append(guest.id)

    if data.no_guests:
        for candidate in db.execute(
            select(StagingGuestCandidate).where(
                StagingGuestCandidate.video_id == video_id, StagingGuestCandidate.status == "pending"
            )
        ).scalars().all():
            staging_service.reject_guest_candidate(db, candidate.id)
            rejected += 1
        video.guest_status = "no_guests"
    elif accepted_guest_ids:
        video.guest_status = "has_guests"

    host_ids = _apply_program_and_hosts(db, video, program, host_plan)
    _close_suggestion(db, video_id, accepted=data.program_id is not None or bool(data.host_names))
    db.commit()
    return {
        "video_id": video_id, "guest_status": video.guest_status,
        "accepted_guest_ids": accepted_guest_ids, "rejected_count": rejected,
        "program_id": video.program_id, "host_ids": host_ids,
    }
