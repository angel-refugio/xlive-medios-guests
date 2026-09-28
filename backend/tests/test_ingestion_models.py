"""Pruebas del modelo de staging de la Fase 3 (paso 2): corridas de ingesta y candidatos."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Contact, ContactType, Guest, IngestionRun, IngestionRunError,
    StagingContactCandidate, StagingGuestCandidate, Video,
)


def _video(yt_id="abc123", **kw):
    return Video(youtube_video_id=yt_id, title="Título", **kw)


def _guest_candidate(video_id, run_id=None, **kw):
    defaults = dict(
        video_id=video_id,
        ingestion_run_id=run_id,
        extracted_name="Fulano",
        found_in_title=True,
        found_in_description=False,
        raw_confidence=0.5,
        adjusted_confidence=0.5,
        evidence="Entrevista con Fulano",
        extraction_method="llm",
    )
    defaults.update(kw)
    return StagingGuestCandidate(**defaults)


def _contact_candidate(video_id, **kw):
    defaults = dict(
        video_id=video_id, type_hint="instagram", value="@algo",
        raw_confidence=0.2, extraction_method="regex",
    )
    defaults.update(kw)
    return StagingContactCandidate(**defaults)


# --- IngestionRun -------------------------------------------------------------

def test_ingestion_run_defaults(session):
    run = IngestionRun()
    session.add(run)
    session.commit()
    assert run.status == "running"
    assert run.trigger == "manual"
    assert run.processed_count == 0 and run.success_count == 0 and run.error_count == 0
    assert run.finished_at is None


def test_ingestion_run_invalid_status_rejected(session):
    session.add(IngestionRun(status="otro"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_ingestion_run_invalid_trigger_rejected(session):
    session.add(IngestionRun(trigger="cron"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_ingestion_run_cascades_errors(session):
    run = IngestionRun()
    session.add(run)
    session.commit()
    session.add(IngestionRunError(ingestion_run_id=run.id, youtube_video_id="vid1", error_message="boom"))
    session.commit()

    session.delete(run)
    session.commit()
    assert session.scalars(select(IngestionRunError)).all() == []


# --- StagingGuestCandidate ------------------------------------------------------

def test_guest_candidate_minimal(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()
    assert candidate.status == "pending"
    assert candidate.is_possible_group is False
    assert candidate.category_is_new_suggestion is False
    assert candidate.linked_guest_id is None


def test_guest_candidate_invalid_status_rejected(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_guest_candidate(v.id, status="otro"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_guest_candidate_invalid_extraction_method_rejected(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_guest_candidate(v.id, extraction_method="ner"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("field", ["raw_confidence", "adjusted_confidence"])
def test_guest_candidate_confidence_out_of_range_rejected(session, field):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_guest_candidate(v.id, **{field: 1.5}))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_video_cascades_guest_candidates(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_guest_candidate(v.id))
    session.commit()

    session.delete(v)
    session.commit()
    assert session.scalars(select(StagingGuestCandidate)).all() == []


def test_deleting_ingestion_run_keeps_guest_candidate(session):
    v, run = _video(), IngestionRun()
    session.add_all([v, run])
    session.commit()
    candidate = _guest_candidate(v.id, run_id=run.id)
    session.add(candidate)
    session.commit()

    session.delete(run)
    session.commit()
    session.refresh(candidate)
    assert candidate.ingestion_run_id is None


def test_deleting_linked_guest_clears_candidate_link(session):
    v, g = _video(), Guest(full_name="Fulano")
    session.add_all([v, g])
    session.commit()
    candidate = _guest_candidate(v.id, status="accepted", linked_guest_id=g.id)
    session.add(candidate)
    session.commit()

    session.delete(g)
    session.commit()
    session.refresh(candidate)
    assert candidate.linked_guest_id is None


# --- StagingContactCandidate -----------------------------------------------------

def test_contact_candidate_minimal(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _contact_candidate(v.id)
    session.add(candidate)
    session.commit()
    assert candidate.status == "pending"
    assert candidate.guest_candidate_id is None


def test_contact_candidate_linked_to_guest_candidate(session):
    v = _video()
    session.add(v)
    session.commit()
    guest_candidate = _guest_candidate(v.id)
    session.add(guest_candidate)
    session.commit()
    contact_candidate = _contact_candidate(v.id, guest_candidate_id=guest_candidate.id)
    session.add(contact_candidate)
    session.commit()
    assert guest_candidate.contacts == [contact_candidate]


def test_contact_candidate_invalid_extraction_method_rejected(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_contact_candidate(v.id, extraction_method="scraping"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_contact_candidate_confidence_out_of_range_rejected(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_contact_candidate(v.id, raw_confidence=-0.1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_video_cascades_contact_candidates(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add(_contact_candidate(v.id))
    session.commit()

    session.delete(v)
    session.commit()
    assert session.scalars(select(StagingContactCandidate)).all() == []


def test_deleting_guest_candidate_clears_contact_candidate_link(session):
    v = _video()
    session.add(v)
    session.commit()
    guest_candidate = _guest_candidate(v.id)
    session.add(guest_candidate)
    session.commit()
    contact_candidate = _contact_candidate(v.id, guest_candidate_id=guest_candidate.id)
    session.add(contact_candidate)
    session.commit()

    session.delete(guest_candidate)
    session.commit()
    session.refresh(contact_candidate)
    assert contact_candidate.guest_candidate_id is None


def test_deleting_linked_contact_clears_candidate_link(session):
    v, ct, g = _video(), ContactType(name="Instagram"), Guest(full_name="Fulano")
    session.add_all([v, ct, g])
    session.commit()
    contact = Contact(guest_id=g.id, contact_type_id=ct.id, value="@algo", source="video_description")
    session.add(contact)
    session.commit()
    candidate = _contact_candidate(v.id, status="accepted", linked_contact_id=contact.id)
    session.add(candidate)
    session.commit()

    session.delete(contact)
    session.commit()
    session.refresh(candidate)
    assert candidate.linked_contact_id is None


# --- Video.possible_duplicate_of_video_id ----------------------------------------

def test_video_possible_duplicate_flag(session):
    v1 = _video("v1")
    session.add(v1)
    session.commit()
    v2 = _video("v2", possible_duplicate_of_video_id=v1.id)
    session.add(v2)
    session.commit()
    assert v2.possible_duplicate_of_video_id == v1.id


def test_deleting_original_clears_possible_duplicate_flag(session):
    v1 = _video("v1")
    session.add(v1)
    session.commit()
    v2 = _video("v2", possible_duplicate_of_video_id=v1.id)
    session.add(v2)
    session.commit()

    session.delete(v1)
    session.commit()
    session.refresh(v2)
    assert v2.possible_duplicate_of_video_id is None
