"""Pruebas del servicio de Staging Review (Fase 3, paso 7)."""
import pytest

from app.models.catalogs import ContactType
from app.models.guest import Guest
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate
from app.models.participation import Participation
from app.models.video import Video
from app.schemas.staging import ContactCandidateAccept, GuestCandidateAccept
from app.services import staging
from app.services.guests import GuestNotFoundError


def _video(yt_id="abc123", **kw):
    return Video(youtube_video_id=yt_id, title="Título", source="youtube", **kw)


def _guest_candidate(video_id, **kw):
    defaults = dict(
        video_id=video_id, extracted_name="Karimm Kury", found_in_title=True,
        found_in_description=False, raw_confidence=0.5, adjusted_confidence=0.5,
        evidence="con Karimm Kury", extraction_method="regex",
    )
    defaults.update(kw)
    return StagingGuestCandidate(**defaults)


def _contact_candidate(video_id, **kw):
    defaults = dict(
        video_id=video_id, type_hint="instagram", value="@karimmkury",
        raw_confidence=0.6, extraction_method="regex",
    )
    defaults.update(kw)
    return StagingContactCandidate(**defaults)


# --- Invitados candidatos: listar y sugerir -------------------------------------

def test_list_guest_candidates_ordena_por_confianza_ajustada(session):
    v = _video()
    session.add(v)
    session.commit()
    low = _guest_candidate(v.id, extracted_name="Baja", adjusted_confidence=0.2)
    high = _guest_candidate(v.id, extracted_name="Alta", adjusted_confidence=0.9)
    session.add_all([low, high])
    session.commit()

    items, total = staging.list_guest_candidates(session)
    assert total == 2
    assert [c.extracted_name for c in items] == ["Alta", "Baja"]


def test_list_guest_candidates_filtra_por_status(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add_all([
        _guest_candidate(v.id, status="pending"),
        _guest_candidate(v.id, status="rejected"),
    ])
    session.commit()

    items, total = staging.list_guest_candidates(session, status="rejected")
    assert total == 1
    assert items[0].status == "rejected"


def test_get_guest_candidate_inexistente(session):
    with pytest.raises(staging.StagingCandidateNotFoundError):
        staging.get_guest_candidate(session, 999)


def test_suggest_similar_guests_coincidencia_exacta_y_parcial(session):
    exacto = Guest(full_name="Karimm Kury")
    parcial = Guest(full_name="Karimm Kury Jr")
    distinto = Guest(full_name="Otro Nombre")
    session.add_all([exacto, parcial, distinto])
    session.commit()

    suggestions = staging.suggest_similar_guests(session, "karimm kury")
    names = {g.full_name for g in suggestions}
    assert names == {"Karimm Kury", "Karimm Kury Jr"}


def test_suggest_similar_guests_respeta_el_limite(session):
    session.add_all([Guest(full_name=f"Karimm {i}") for i in range(10)])
    session.commit()
    assert len(staging.suggest_similar_guests(session, "Karimm", limit=3)) == 3


# --- Invitados candidatos: aceptar / rechazar -----------------------------------

def test_accept_guest_candidate_crea_invitado_y_participacion(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id, extracted_name="Karimm Kury")
    session.add(candidate)
    session.commit()

    guest = staging.accept_guest_candidate(session, candidate.id, GuestCandidateAccept())

    assert guest.full_name == "Karimm Kury"  # tomado de extracted_name
    assert len(guest.participations) == 1
    assert guest.participations[0].video_id == v.id
    assert candidate.status == "accepted"
    assert candidate.linked_guest_id == guest.id
    assert candidate.reviewed_at is not None


def test_accept_guest_candidate_full_name_explicito_sobrescribe(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id, extracted_name="Karimm Kury")
    session.add(candidate)
    session.commit()

    guest = staging.accept_guest_candidate(
        session, candidate.id, GuestCandidateAccept(full_name="Karimm Kury Oficial")
    )
    assert guest.full_name == "Karimm Kury Oficial"


def test_accept_guest_candidate_vincula_existente_sin_editar(session):
    v = _video()
    existente = Guest(full_name="Karimm Kury", organization="Original")
    session.add_all([v, existente])
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()

    guest = staging.accept_guest_candidate(
        session, candidate.id, GuestCandidateAccept(existing_guest_id=existente.id)
    )
    assert guest.id == existente.id
    assert guest.organization == "Original"  # no se tocó
    assert len(guest.participations) == 1


def test_accept_guest_candidate_vincula_existente_editando(session):
    v = _video()
    existente = Guest(full_name="Karimm Kury")
    session.add_all([v, existente])
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()

    guest = staging.accept_guest_candidate(
        session, candidate.id,
        GuestCandidateAccept(existing_guest_id=existente.id, organization="TV Azteca"),
    )
    assert guest.organization == "TV Azteca"


def test_accept_guest_candidate_existente_inexistente_da_404(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()

    with pytest.raises(GuestNotFoundError):
        staging.accept_guest_candidate(
            session, candidate.id, GuestCandidateAccept(existing_guest_id=999)
        )


def test_accept_guest_candidate_no_duplica_participacion_existente(session):
    v = _video()
    existente = Guest(full_name="Karimm Kury")
    session.add_all([v, existente])
    session.commit()
    session.add(Participation(guest_id=existente.id, video_id=v.id))
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()

    guest = staging.accept_guest_candidate(
        session, candidate.id, GuestCandidateAccept(existing_guest_id=existente.id)
    )
    assert len(guest.participations) == 1  # no se duplicó


def test_accept_guest_candidate_ya_revisado_lanza_error(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id, status="accepted")
    session.add(candidate)
    session.commit()

    with pytest.raises(staging.StagingCandidateAlreadyReviewedError):
        staging.accept_guest_candidate(session, candidate.id, GuestCandidateAccept())


def test_reject_guest_candidate(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id)
    session.add(candidate)
    session.commit()

    rejected = staging.reject_guest_candidate(session, candidate.id)
    assert rejected.status == "rejected"
    assert rejected.reviewed_at is not None


def test_reject_guest_candidate_ya_revisado_lanza_error(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _guest_candidate(v.id, status="rejected")
    session.add(candidate)
    session.commit()

    with pytest.raises(staging.StagingCandidateAlreadyReviewedError):
        staging.reject_guest_candidate(session, candidate.id)


# --- Contactos candidatos --------------------------------------------------------

def test_accept_contact_candidate_crea_contacto(session):
    v, guest, ct = _video(), Guest(full_name="Karimm Kury"), ContactType(name="Instagram")
    session.add_all([v, guest, ct])
    session.commit()
    candidate = _contact_candidate(v.id, value="@karimmkury")
    session.add(candidate)
    session.commit()

    contact = staging.accept_contact_candidate(
        session, candidate.id, ContactCandidateAccept(guest_id=guest.id, contact_type_id=ct.id)
    )
    assert contact.value == "@karimmkury"
    assert contact.source == "video_description"
    assert contact.verified is False
    assert candidate.status == "accepted"
    assert candidate.linked_contact_id == contact.id


def test_accept_contact_candidate_valor_explicito_sobrescribe(session):
    v, guest, ct = _video(), Guest(full_name="Karimm Kury"), ContactType(name="Instagram")
    session.add_all([v, guest, ct])
    session.commit()
    candidate = _contact_candidate(v.id, value="@viejo")
    session.add(candidate)
    session.commit()

    contact = staging.accept_contact_candidate(
        session, candidate.id,
        ContactCandidateAccept(guest_id=guest.id, contact_type_id=ct.id, value="@nuevo"),
    )
    assert contact.value == "@nuevo"


def test_accept_contact_candidate_ya_revisado_lanza_error(session):
    v, guest, ct = _video(), Guest(full_name="A"), ContactType(name="Instagram")
    session.add_all([v, guest, ct])
    session.commit()
    candidate = _contact_candidate(v.id, status="rejected")
    session.add(candidate)
    session.commit()

    with pytest.raises(staging.StagingCandidateAlreadyReviewedError):
        staging.accept_contact_candidate(
            session, candidate.id, ContactCandidateAccept(guest_id=guest.id, contact_type_id=ct.id)
        )


def test_reject_contact_candidate(session):
    v = _video()
    session.add(v)
    session.commit()
    candidate = _contact_candidate(v.id)
    session.add(candidate)
    session.commit()

    rejected = staging.reject_contact_candidate(session, candidate.id)
    assert rejected.status == "rejected"


def test_list_contact_candidates_ordena_por_confianza(session):
    v = _video()
    session.add(v)
    session.commit()
    session.add_all([
        _contact_candidate(v.id, value="baja", raw_confidence=0.1),
        _contact_candidate(v.id, value="alta", raw_confidence=0.9),
    ])
    session.commit()

    items, total = staging.list_contact_candidates(session)
    assert total == 2
    assert [c.value for c in items] == ["alta", "baja"]
