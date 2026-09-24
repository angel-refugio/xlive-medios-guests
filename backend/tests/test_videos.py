"""Pruebas de videos manuales: CRUD, referencias, origen ('source') y borrado."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.video import Video


def _create(client, youtube_id="abc123", title="Entrevista 1", **extra):
    return client.post("/videos", json={"youtube_video_id": youtube_id, "title": title, **extra})


def test_requires_authentication(api_client):
    anonymous = TestClient(api_client.app)
    assert anonymous.get("/videos").status_code == 401
    assert anonymous.post("/videos", json={}).status_code == 401
    assert anonymous.get("/videos/1").status_code == 401
    assert anonymous.patch("/videos/1", json={}).status_code == 401
    assert anonymous.delete("/videos/1?confirm=true").status_code == 401


def test_create_minimal_is_manual_and_pending(api_client):
    resp = _create(api_client, youtube_id="  abc123 ", title="  Entrevista 1 ")
    assert resp.status_code == 201
    body = resp.json()
    assert body["youtube_video_id"] == "abc123"
    assert body["title"] == "Entrevista 1"
    assert body["source"] == "manual"
    assert body["guest_status"] == "pending"
    assert body["video_type"] is None
    assert body["program"] is None
    assert body["event_borough"] is None


def test_create_ignores_source_sent_by_client(api_client):
    body = _create(api_client, source="youtube").json()
    assert body["source"] == "manual"


def test_create_full_with_catalogs(api_client):
    video_type = api_client.post("/video-types", json={"name": "Entrevista"}).json()
    program = api_client.post("/programs", json={"name": "Buenos días"}).json()
    borough = api_client.post("/boroughs", json={"name": "Coyoacán"}).json()
    original = _create(api_client, youtube_id="orig1", title="Original").json()
    resp = _create(
        api_client,
        description="Una descripción",
        published_at="2024-05-01T10:00:00Z",
        video_type_id=video_type["id"],
        program_id=program["id"],
        event_borough_id=borough["id"],
        part_of_video_id=original["id"],
        guest_status="has_guests",
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["video_type"]["name"] == "Entrevista"
    assert body["program"]["name"] == "Buenos días"
    assert body["event_borough"]["name"] == "Coyoacán"
    assert body["part_of_video_id"] == original["id"]
    assert body["guest_status"] == "has_guests"
    assert body["published_at"].startswith("2024-05-01T10:00:00")


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Sin id"},
        {"youtube_video_id": "x"},
        {"youtube_video_id": "  ", "title": "T"},
        {"youtube_video_id": "x", "title": "  "},
        {"youtube_video_id": "x" * 33, "title": "T"},
        {"youtube_video_id": "x", "title": "T" * 501},
        {"youtube_video_id": "x", "title": "T", "guest_status": "otro"},
    ],
)
def test_create_validation_errors(api_client, payload):
    assert api_client.post("/videos", json=payload).status_code == 422


def test_duplicate_youtube_id_returns_409(api_client):
    _create(api_client, youtube_id="dup1")
    resp = _create(api_client, youtube_id="dup1", title="Otro")
    assert resp.status_code == 409
    assert "dup1" in resp.json()["detail"]


def test_unknown_or_inactive_references_return_422(api_client):
    assert _create(api_client, video_type_id=999).status_code == 422
    assert _create(api_client, program_id=999).status_code == 422
    assert _create(api_client, event_borough_id=999).status_code == 422
    assert _create(api_client, part_of_video_id=999).status_code == 422

    program = api_client.post("/programs", json={"name": "Viejo"}).json()
    api_client.patch(f"/programs/{program['id']}", json={"is_active": False})
    resp = _create(api_client, youtube_id="otro", program_id=program["id"])
    assert resp.status_code == 422
    assert "desactivado" in resp.json()["detail"]


def test_get_and_404(api_client):
    video = _create(api_client).json()
    assert api_client.get(f"/videos/{video['id']}").json()["title"] == "Entrevista 1"
    resp = api_client.get("/videos/9999")
    assert resp.status_code == 404
    assert "9999" in resp.json()["detail"]


def test_patch_partial_keeps_other_fields(api_client):
    program = api_client.post("/programs", json={"name": "P"}).json()
    video = _create(api_client, program_id=program["id"]).json()
    resp = api_client.patch(f"/videos/{video['id']}", json={"title": "Nuevo título"})
    body = resp.json()
    assert body["title"] == "Nuevo título"
    assert body["program"]["name"] == "P"
    assert body["youtube_video_id"] == "abc123"


def test_patch_null_clears_optionals_but_not_required(api_client):
    program = api_client.post("/programs", json={"name": "P"}).json()
    video = _create(api_client, program_id=program["id"], description="d").json()
    url = f"/videos/{video['id']}"
    resp = api_client.patch(url, json={"program_id": None, "description": None})
    assert resp.json()["program"] is None
    assert resp.json()["description"] is None
    for field in ("title", "youtube_video_id", "guest_status"):
        assert api_client.patch(url, json={field: None}).status_code == 422
    assert api_client.patch(url, json={"title": "  "}).status_code == 422


def test_patch_youtube_id_duplicate_and_same_value(api_client):
    _create(api_client, youtube_id="uno")
    other = _create(api_client, youtube_id="dos").json()
    url = f"/videos/{other['id']}"
    assert api_client.patch(url, json={"youtube_video_id": "uno"}).status_code == 409
    assert api_client.patch(url, json={"youtube_video_id": "dos"}).status_code == 200


def test_patch_cannot_be_part_of_itself(api_client):
    video = _create(api_client).json()
    resp = api_client.patch(f"/videos/{video['id']}", json={"part_of_video_id": video["id"]})
    assert resp.status_code == 422
    assert "sí mismo" in resp.json()["detail"]


def test_patch_keeps_inactive_program_already_assigned(api_client):
    program = api_client.post("/programs", json={"name": "P"}).json()
    video = _create(api_client, program_id=program["id"]).json()
    api_client.patch(f"/programs/{program['id']}", json={"is_active": False})
    resp = api_client.patch(
        f"/videos/{video['id']}", json={"program_id": program["id"], "title": "Otro"}
    )
    assert resp.status_code == 200


def test_patch_unknown_video_returns_404(api_client):
    assert api_client.patch("/videos/9999", json={"title": "X"}).status_code == 404


def test_pagination_and_order_newest_first(api_client):
    _create(api_client, youtube_id="a", title="Sin fecha")
    _create(api_client, youtube_id="b", title="Viejo", published_at="2023-01-01T00:00:00Z")
    _create(api_client, youtube_id="c", title="Nuevo", published_at="2024-01-01T00:00:00Z")
    page = api_client.get("/videos").json()
    assert (page["total"], page["page"], page["page_size"]) == (3, 1, 50)
    assert [v["title"] for v in page["items"]] == ["Nuevo", "Viejo", "Sin fecha"]
    page2 = api_client.get("/videos", params={"page": 2, "page_size": 2}).json()
    assert [v["title"] for v in page2["items"]] == ["Sin fecha"]


def test_pagination_invalid_params_rejected(api_client):
    assert api_client.get("/videos", params={"page": 0}).status_code == 422
    assert api_client.get("/videos", params={"page_size": 201}).status_code == 422


def test_filter_by_source_lists_only_manual_ones(api_client, api_engine):
    _create(api_client, youtube_id="manual1", title="Manual")
    with Session(api_engine) as s:  # simula un video traído por la ingesta (Fase 3)
        s.add(Video(youtube_video_id="yt1", title="De YouTube", source="youtube"))
        s.commit()

    manual = api_client.get("/videos", params={"source": "manual"}).json()
    assert [v["title"] for v in manual["items"]] == ["Manual"]
    assert manual["total"] == 1
    youtube = api_client.get("/videos", params={"source": "youtube"}).json()
    assert [v["title"] for v in youtube["items"]] == ["De YouTube"]
    assert api_client.get("/videos").json()["total"] == 2
    assert api_client.get("/videos", params={"source": "otro"}).status_code == 422


def test_delete_requires_confirmation(api_client):
    video = _create(api_client).json()
    resp = api_client.delete(f"/videos/{video['id']}")
    assert resp.status_code == 400
    assert "confirm=true" in resp.json()["detail"]
    assert api_client.get(f"/videos/{video['id']}").status_code == 200


def test_delete_removes_participations_keeps_guests_and_detaches_parts(api_client, api_engine):
    guest = api_client.post("/guests", json={"full_name": "Ana"}).json()
    original = _create(api_client, youtube_id="orig", title="Original").json()
    part = _create(api_client, youtube_id="part", title="Parte", part_of_video_id=original["id"]).json()
    api_client.post(f"/guests/{guest['id']}/participations", json={"video_id": original["id"]})

    assert api_client.delete(f"/videos/{original['id']}?confirm=true").status_code == 204
    assert api_client.get(f"/videos/{original['id']}").status_code == 404
    assert api_client.get(f"/guests/{guest['id']}").status_code == 200  # el invitado sigue
    assert api_client.get(f"/guests/{guest['id']}/participations").json() == []
    assert api_client.get(f"/videos/{part['id']}").json()["part_of_video_id"] is None


def test_delete_unknown_video_returns_404(api_client):
    assert api_client.delete("/videos/9999?confirm=true").status_code == 404
