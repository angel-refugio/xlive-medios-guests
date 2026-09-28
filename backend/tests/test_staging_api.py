"""Pruebas de los endpoints de Staging Review (Fase 3, paso 7)."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.catalogs import ContactType
from app.models.guest import Guest
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate
from app.models.video import Video


def _seed_guest_candidate(engine, **kw) -> tuple[int, int]:
    """Crea un video + candidato de invitado directo en la BD; devuelve (video_id, candidate_id)."""
    with Session(engine) as s:
        video = Video(youtube_video_id="abc123", title="con Karimm Kury", source="youtube")
        s.add(video)
        s.commit()
        defaults = dict(
            video_id=video.id, extracted_name="Karimm Kury", found_in_title=True,
            found_in_description=False, raw_confidence=0.5, adjusted_confidence=0.5,
            evidence="con Karimm Kury", extraction_method="regex",
        )
        defaults.update(kw)
        candidate = StagingGuestCandidate(**defaults)
        s.add(candidate)
        s.commit()
        return video.id, candidate.id


def _seed_contact_candidate(engine) -> tuple[int, int, int]:
    """Crea video + invitado + tipo de contacto + candidato; devuelve (guest_id, type_id, candidate_id)."""
    with Session(engine) as s:
        video = Video(youtube_video_id="abc123", title="con Karimm Kury", source="youtube")
        guest = Guest(full_name="Karimm Kury")
        ct = ContactType(name="Instagram")
        s.add_all([video, guest, ct])
        s.commit()
        candidate = StagingContactCandidate(
            video_id=video.id, type_hint="instagram", value="@karimmkury",
            raw_confidence=0.6, extraction_method="regex",
        )
        s.add(candidate)
        s.commit()
        return guest.id, ct.id, candidate.id


def test_requires_authentication(api_client):
    anonymous = TestClient(api_client.app)
    assert anonymous.get("/staging/guest-candidates").status_code == 401
    assert anonymous.post("/staging/guest-candidates/1/accept", json={}).status_code == 401
    assert anonymous.get("/staging/contact-candidates").status_code == 401


def test_list_and_get_guest_candidate(api_client, api_engine):
    _, candidate_id = _seed_guest_candidate(api_engine)

    listing = api_client.get("/staging/guest-candidates")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["extracted_name"] == "Karimm Kury"

    detail = api_client.get(f"/staging/guest-candidates/{candidate_id}")
    assert detail.status_code == 200
    assert detail.json()["video"]["youtube_video_id"] == "abc123"


def test_get_guest_candidate_404(api_client):
    assert api_client.get("/staging/guest-candidates/999").status_code == 404


def test_suggestions_endpoint(api_client, api_engine):
    _, candidate_id = _seed_guest_candidate(api_engine)
    with Session(api_engine) as s:
        s.add(Guest(full_name="Karimm Kury"))
        s.commit()

    resp = api_client.get(f"/staging/guest-candidates/{candidate_id}/suggestions")
    assert resp.status_code == 200
    assert resp.json()[0]["full_name"] == "Karimm Kury"


def test_accept_guest_candidate_crea_invitado(api_client, api_engine):
    _, candidate_id = _seed_guest_candidate(api_engine)

    resp = api_client.post(f"/staging/guest-candidates/{candidate_id}/accept", json={})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Karimm Kury"

    detail = api_client.get(f"/staging/guest-candidates/{candidate_id}").json()
    assert detail["status"] == "accepted"

    participations = api_client.get(f"/guests/{resp.json()['id']}/participations").json()
    assert len(participations) == 1


def test_accept_guest_candidate_ya_revisado_da_409(api_client, api_engine):
    _, candidate_id = _seed_guest_candidate(api_engine)
    api_client.post(f"/staging/guest-candidates/{candidate_id}/accept", json={})

    resp = api_client.post(f"/staging/guest-candidates/{candidate_id}/accept", json={})
    assert resp.status_code == 409


def test_reject_guest_candidate(api_client, api_engine):
    _, candidate_id = _seed_guest_candidate(api_engine)

    resp = api_client.post(f"/staging/guest-candidates/{candidate_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_accept_contact_candidate(api_client, api_engine):
    guest_id, type_id, candidate_id = _seed_contact_candidate(api_engine)

    resp = api_client.post(
        f"/staging/contact-candidates/{candidate_id}/accept",
        json={"guest_id": guest_id, "contact_type_id": type_id},
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "@karimmkury"
    assert resp.json()["source"] == "video_description"
    assert resp.json()["verified"] is False


def test_videos_filtra_por_guest_status(api_client, api_engine):
    _seed_guest_candidate(api_engine)  # video en 'pending'
    with Session(api_engine) as s:
        s.add(Video(youtube_video_id="sinInvitados", title="Resumen", source="youtube", guest_status="no_guests"))
        s.commit()

    resp = api_client.get("/videos", params={"guest_status": "no_guests"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["youtube_video_id"] == "sinInvitados"
