"""Fase 3, paso 7: Staging Review — aceptar, editar o rechazar candidatos de la ingesta.

Aceptar un candidato de invitado crea o vincula un `Guest` y su `Participation`; aceptar uno
de contacto crea un `Contact` con `source='video_description'` y `verified=False` (regla ya
acordada). Nada de esto reemplaza el CRUD normal: reutiliza `app.services.guests/contacts/
participations` para no duplicar validaciones.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.contact import Contact
from app.models.guest import Guest
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate
from app.schemas.contacts import ContactCreate
from app.schemas.guests import GuestCreate, GuestUpdate
from app.schemas.participations import ParticipationCreate
from app.schemas.staging import ContactCandidateAccept, GuestCandidateAccept
from app.services import contacts as contacts_service
from app.services import guests as guests_service
from app.services import participations as participations_service
from app.services.catalogs import normalize_name
from app.services.participations import ParticipationDuplicateError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_SUGGESTION_LIMIT = 5


class StagingCandidateNotFoundError(LookupError):
    pass


class StagingCandidateAlreadyReviewedError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Invitados candidatos -----------------------------------------------------

def list_guest_candidates(
    db: Session, status: str = "pending", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[list[StagingGuestCandidate], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    filters = [StagingGuestCandidate.status == status] if status else []
    total = db.execute(
        select(func.count(StagingGuestCandidate.id)).where(*filters)
    ).scalar_one()
    stmt = (
        select(StagingGuestCandidate)
        .where(*filters)
        .options(selectinload(StagingGuestCandidate.video))
        # Staging Review ordena por el ajuste, no por la confianza cruda (regla del pipeline).
        .order_by(StagingGuestCandidate.adjusted_confidence.desc(), StagingGuestCandidate.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(db.execute(stmt).scalars()), total


def get_guest_candidate(db: Session, candidate_id: int) -> StagingGuestCandidate:
    candidate = db.get(StagingGuestCandidate, candidate_id)
    if candidate is None:
        msg = f"No existe el candidato de invitado {candidate_id}"
        logger.warning("[app.services.staging.get_guest_candidate] %s", msg)
        raise StagingCandidateNotFoundError(msg)
    return candidate


def suggest_similar_guests(
    db: Session, name: str, limit: int = DEFAULT_SUGGESTION_LIMIT
) -> list[Guest]:
    """Invitados existentes con nombre parecido (FR-001), para no duplicar.

    Compara en Python, como `catalogs._ensure_unique`: la tabla de invitados no es tan grande
    como para justificar una búsqueda por similitud en SQL todavía.
    """
    key = normalize_name(name)
    exact: list[Guest] = []
    partial: list[Guest] = []
    for guest in db.execute(select(Guest)).scalars():
        guest_key = normalize_name(guest.full_name)
        if guest_key == key:
            exact.append(guest)
        elif key in guest_key or guest_key in key:
            partial.append(guest)
    return (exact + partial)[:limit]


def _ensure_pending(candidate: StagingGuestCandidate | StagingContactCandidate, kind: str) -> None:
    if candidate.status != "pending":
        msg = f"El candidato de {kind} {candidate.id} ya fue revisado ({candidate.status})"
        logger.warning("[app.services.staging._ensure_pending] %s", msg)
        raise StagingCandidateAlreadyReviewedError(msg)


def accept_guest_candidate(
    db: Session, candidate_id: int, data: GuestCandidateAccept
) -> Guest:
    """Crea o vincula un invitado, crea su participación en el video, y cierra el candidato."""
    candidate = get_guest_candidate(db, candidate_id)
    _ensure_pending(candidate, "invitado")

    if data.existing_guest_id is not None:
        guest = guests_service.get_guest(db, data.existing_guest_id)  # 404 si no existe
        # Solo edita lo que el humano haya enviado explícitamente (exclude_unset); vincular
        # sin tocar nada más es igual de válido.
        edits = data.model_dump(exclude={"existing_guest_id"}, exclude_unset=True)
        if edits:
            guest = guests_service.update_guest(db, guest.id, GuestUpdate(**edits))
    else:
        guest = guests_service.create_guest(db, GuestCreate(
            full_name=data.full_name or candidate.extracted_name,
            organization=data.organization, role=data.role, notes=data.notes,
            approx_age=data.approx_age, borough_id=data.borough_id,
            category_ids=data.category_ids, new_categories=data.new_categories,
        ))

    try:
        participations_service.create_participation(
            db, guest.id, ParticipationCreate(video_id=candidate.video_id)
        )
    except ParticipationDuplicateError:
        logger.info(
            "[app.services.staging.accept_guest_candidate] %s ya participaba en el video %s",
            guest.id, candidate.video_id,
        )

    candidate.status = "accepted"
    candidate.linked_guest_id = guest.id
    candidate.reviewed_at = _now()
    db.commit()
    return guest


def reject_guest_candidate(db: Session, candidate_id: int) -> StagingGuestCandidate:
    candidate = get_guest_candidate(db, candidate_id)
    _ensure_pending(candidate, "invitado")
    candidate.status = "rejected"
    candidate.reviewed_at = _now()
    db.commit()
    return candidate


# --- Contactos candidatos ------------------------------------------------------

def list_contact_candidates(
    db: Session, status: str = "pending", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[list[StagingContactCandidate], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    filters = [StagingContactCandidate.status == status] if status else []
    total = db.execute(
        select(func.count(StagingContactCandidate.id)).where(*filters)
    ).scalar_one()
    stmt = (
        select(StagingContactCandidate)
        .where(*filters)
        .options(selectinload(StagingContactCandidate.video))
        .order_by(StagingContactCandidate.raw_confidence.desc(), StagingContactCandidate.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(db.execute(stmt).scalars()), total


def get_contact_candidate(db: Session, candidate_id: int) -> StagingContactCandidate:
    candidate = db.get(StagingContactCandidate, candidate_id)
    if candidate is None:
        msg = f"No existe el candidato de contacto {candidate_id}"
        logger.warning("[app.services.staging.get_contact_candidate] %s", msg)
        raise StagingCandidateNotFoundError(msg)
    return candidate


def accept_contact_candidate(
    db: Session, candidate_id: int, data: ContactCandidateAccept
) -> Contact:
    """Crea el contacto (`source='video_description'`, `verified=False`) y cierra el candidato.

    El invitado al que se atribuye (`data.guest_id`) siempre lo elige quien revisa: no se
    infiere solo a partir de `guest_candidate_id`, aunque el candidato ya sugiera uno.
    """
    candidate = get_contact_candidate(db, candidate_id)
    _ensure_pending(candidate, "contacto")

    contact = contacts_service.create_contact(db, data.guest_id, ContactCreate(
        contact_type_id=data.contact_type_id,
        value=data.value or candidate.value,
        note=data.note,
        source="video_description",
        verified=False,
    ))

    candidate.status = "accepted"
    candidate.linked_contact_id = contact.id
    candidate.reviewed_at = _now()
    db.commit()
    return contact


def reject_contact_candidate(db: Session, candidate_id: int) -> StagingContactCandidate:
    candidate = get_contact_candidate(db, candidate_id)
    _ensure_pending(candidate, "contacto")
    candidate.status = "rejected"
    candidate.reviewed_at = _now()
    db.commit()
    return candidate
