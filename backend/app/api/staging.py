"""Endpoints de Staging Review: candidatos de invitado y de contacto (protegidos)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.contacts import ContactOut
from app.schemas.guests import GuestOut
from app.schemas.staging import (
    CandidateStatus, ContactCandidateAccept, ContactCandidateOut, ContactCandidatePage,
    GuestCandidateAccept, GuestCandidateOut, GuestCandidatePage, GuestSuggestion,
    ReviewCounts, ReviewFilter, ReviewResolve, ReviewResolveOut, ReviewVideoPage,
)
from app.services import staging as service
from app.services import staging_review as review_service
from app.services.videos import VideoNotFoundError
from app.services.contacts import ContactNotFoundError
from app.services.guests import GuestNotFoundError, InvalidReferenceError
from app.services.participations import ParticipationDuplicateError

router = APIRouter(prefix="/staging", tags=["staging"], dependencies=[Depends(require_admin)])

_KNOWN_ERRORS = (
    GuestNotFoundError, ContactNotFoundError, service.StagingCandidateNotFoundError,
    service.StagingCandidateAlreadyReviewedError, InvalidReferenceError, ParticipationDuplicateError,
    VideoNotFoundError, review_service.ReviewInputError,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (
        GuestNotFoundError, ContactNotFoundError, service.StagingCandidateNotFoundError,
        VideoNotFoundError,
    )):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.StagingCandidateAlreadyReviewedError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


# --- Invitados candidatos -----------------------------------------------------

@router.get("/guest-candidates", response_model=GuestCandidatePage)
def list_guest_candidates(
    status: CandidateStatus | None = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    items, total = service.list_guest_candidates(db, status or "", page, page_size)
    return GuestCandidatePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/guest-candidates/{candidate_id}", response_model=GuestCandidateOut)
def get_guest_candidate(candidate_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_guest_candidate(db, candidate_id)
    except service.StagingCandidateNotFoundError as exc:
        raise _http_error(exc)


@router.get("/guest-candidates/{candidate_id}/suggestions", response_model=list[GuestSuggestion])
def suggest_guests(candidate_id: int, db: Session = Depends(get_db)):
    """Invitados existentes con nombre parecido al candidato, para no duplicar (FR-001)."""
    try:
        candidate = service.get_guest_candidate(db, candidate_id)
    except service.StagingCandidateNotFoundError as exc:
        raise _http_error(exc)
    return service.suggest_similar_guests(db, candidate.extracted_name)


@router.post("/guest-candidates/{candidate_id}/accept", response_model=GuestOut)
def accept_guest_candidate(candidate_id: int, data: GuestCandidateAccept, db: Session = Depends(get_db)):
    try:
        return service.accept_guest_candidate(db, candidate_id, data)
    except _KNOWN_ERRORS as exc:
        raise _http_error(exc)


@router.post("/guest-candidates/{candidate_id}/reject", response_model=GuestCandidateOut)
def reject_guest_candidate(candidate_id: int, db: Session = Depends(get_db)):
    try:
        return service.reject_guest_candidate(db, candidate_id)
    except _KNOWN_ERRORS as exc:
        raise _http_error(exc)


# --- Contactos candidatos ------------------------------------------------------

@router.get("/contact-candidates", response_model=ContactCandidatePage)
def list_contact_candidates(
    status: CandidateStatus | None = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    items, total = service.list_contact_candidates(db, status or "", page, page_size)
    return ContactCandidatePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/contact-candidates/{candidate_id}", response_model=ContactCandidateOut)
def get_contact_candidate(candidate_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_contact_candidate(db, candidate_id)
    except service.StagingCandidateNotFoundError as exc:
        raise _http_error(exc)


@router.post("/contact-candidates/{candidate_id}/accept", response_model=ContactOut)
def accept_contact_candidate(
    candidate_id: int, data: ContactCandidateAccept, db: Session = Depends(get_db)
):
    try:
        return service.accept_contact_candidate(db, candidate_id, data)
    except _KNOWN_ERRORS as exc:
        raise _http_error(exc)


@router.post("/contact-candidates/{candidate_id}/reject", response_model=ContactCandidateOut)
def reject_contact_candidate(candidate_id: int, db: Session = Depends(get_db)):
    try:
        return service.reject_contact_candidate(db, candidate_id)
    except _KNOWN_ERRORS as exc:
        raise _http_error(exc)


# --- Revisión por video ---------------------------------------------------------

@router.get("/review/counts", response_model=ReviewCounts)
def review_counts(q: str | None = None, db: Session = Depends(get_db)):
    """Contadores de la barra de filtros (videos por filtro, respetando la búsqueda)."""
    return review_service.review_counts(db, q)


@router.get("/review/videos", response_model=ReviewVideoPage)
def list_review_videos(
    filter: ReviewFilter = "pending",
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(review_service.DEFAULT_PAGE_SIZE, ge=1, le=review_service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    items, total = review_service.list_review_videos(db, filter, q, page, page_size)
    return ReviewVideoPage(items=items, total=total, page=page, page_size=page_size)


@router.post("/review/videos/{video_id}/resolve", response_model=ReviewResolveOut)
def resolve_review_video(video_id: int, data: ReviewResolve, db: Session = Depends(get_db)):
    """Aplica de una vez lo que decidió el humano sobre un video (botón "Correcto")."""
    try:
        return review_service.resolve_video(db, video_id, data)
    except _KNOWN_ERRORS as exc:
        raise _http_error(exc)
