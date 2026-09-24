"""Pruebas de participaciones: vínculo invitado ↔ video, único por par."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def guest(api_client):
    return api_client.post("/guests", json={"full_name": "Ana López"}).json()


@pytest.fixture()
def video(api_client):
    return api_client.post(
        "/videos", json={"youtube_video_id": "vid1", "title": "Entrevista 1"}
    ).json()


def _url(guest_id, participation_id=None):
    base = f"/guests/{guest_id}/participations"
    return base if participation_id is None else f"{base}/{participation_id}"


def test_requires_authentication(api_client, guest):
    anonymous = TestClient(api_client.app)
    assert anonymous.get(_url(guest["id"])).status_code == 401
    assert anonymous.post(_url(guest["id"]), json={}).status_code == 401
    assert anonymous.patch(_url(guest["id"], 1), json={}).status_code == 401
    assert anonymous.delete(_url(guest["id"], 1) + "?confirm=true").status_code == 401
    assert anonymous.get("/videos/1/participations").status_code == 401


def test_create_and_response_shape(api_client, guest, video):
    resp = api_client.post(_url(guest["id"]), json={"video_id": video["id"], "notes": " Habló de su gira "})
    assert resp.status_code == 201
    body = resp.json()
    assert body["notes"] == "Habló de su gira"
    assert body["guest"] == {"id": guest["id"], "full_name": "Ana López"}
    assert body["video"] == {
        "id": video["id"],
        "youtube_video_id": "vid1",
        "title": "Entrevista 1",
        "source": "manual",
    }


def test_create_without_notes(api_client, guest, video):
    body = api_client.post(_url(guest["id"]), json={"video_id": video["id"]}).json()
    assert body["notes"] is None


def test_create_requires_video_id(api_client, guest):
    assert api_client.post(_url(guest["id"]), json={}).status_code == 422


def test_duplicate_pair_returns_409(api_client, guest, video):
    api_client.post(_url(guest["id"]), json={"video_id": video["id"]})
    resp = api_client.post(_url(guest["id"]), json={"video_id": video["id"]})
    assert resp.status_code == 409
    assert "ya participa" in resp.json()["detail"]


def test_same_video_with_different_guests_is_ok(api_client, guest, video):
    other = api_client.post("/guests", json={"full_name": "Luis"}).json()
    assert api_client.post(_url(guest["id"]), json={"video_id": video["id"]}).status_code == 201
    assert api_client.post(_url(other["id"]), json={"video_id": video["id"]}).status_code == 201


def test_unknown_video_returns_422_and_unknown_guest_404(api_client, guest, video):
    assert api_client.post(_url(guest["id"]), json={"video_id": 999}).status_code == 422
    assert api_client.get(_url(9999)).status_code == 404
    assert api_client.post(_url(9999), json={"video_id": video["id"]}).status_code == 404
    assert api_client.get(_url(9999, 1)).status_code == 404
    assert api_client.patch(_url(9999, 1), json={"notes": "x"}).status_code == 404
    assert api_client.delete(_url(9999, 1) + "?confirm=true").status_code == 404


def test_list_by_guest_newest_video_first(api_client, guest):
    old = api_client.post(
        "/videos", json={"youtube_video_id": "old", "title": "Viejo", "published_at": "2023-01-01T00:00:00Z"}
    ).json()
    new = api_client.post(
        "/videos", json={"youtube_video_id": "new", "title": "Nuevo", "published_at": "2024-01-01T00:00:00Z"}
    ).json()
    api_client.post(_url(guest["id"]), json={"video_id": old["id"]})
    api_client.post(_url(guest["id"]), json={"video_id": new["id"]})
    titles = [p["video"]["title"] for p in api_client.get(_url(guest["id"])).json()]
    assert titles == ["Nuevo", "Viejo"]


def test_list_only_returns_that_guests_participations(api_client, guest, video):
    other = api_client.post("/guests", json={"full_name": "Luis"}).json()
    api_client.post(_url(guest["id"]), json={"video_id": video["id"]})
    assert len(api_client.get(_url(guest["id"])).json()) == 1
    assert api_client.get(_url(other["id"])).json() == []


def test_list_by_video(api_client, guest, video):
    other = api_client.post("/guests", json={"full_name": "Luis"}).json()
    api_client.post(_url(guest["id"]), json={"video_id": video["id"]})
    api_client.post(_url(other["id"]), json={"video_id": video["id"]})
    listed = api_client.get(f"/videos/{video['id']}/participations").json()
    assert [p["guest"]["full_name"] for p in listed] == ["Ana López", "Luis"]
    assert api_client.get("/videos/9999/participations").status_code == 404


def test_participation_of_another_guest_is_404(api_client, guest, video):
    other = api_client.post("/guests", json={"full_name": "Luis"}).json()
    participation = api_client.post(_url(other["id"]), json={"video_id": video["id"]}).json()
    assert api_client.get(_url(guest["id"], participation["id"])).status_code == 404
    assert api_client.patch(_url(guest["id"], participation["id"]), json={"notes": "x"}).status_code == 404
    assert api_client.delete(_url(guest["id"], participation["id"]) + "?confirm=true").status_code == 404
    assert api_client.get(_url(other["id"], participation["id"])).status_code == 200


def test_patch_notes_set_and_clear(api_client, guest, video):
    participation = api_client.post(_url(guest["id"]), json={"video_id": video["id"], "notes": "a"}).json()
    url = _url(guest["id"], participation["id"])
    assert api_client.patch(url, json={"notes": "b"}).json()["notes"] == "b"
    assert api_client.patch(url, json={}).json()["notes"] == "b"  # sin enviar: no cambia
    assert api_client.patch(url, json={"notes": None}).json()["notes"] is None


def test_patch_unknown_participation_returns_404(api_client, guest):
    assert api_client.patch(_url(guest["id"], 9999), json={"notes": "x"}).status_code == 404


def test_delete_requires_confirmation(api_client, guest, video):
    participation = api_client.post(_url(guest["id"]), json={"video_id": video["id"]}).json()
    url = _url(guest["id"], participation["id"])
    resp = api_client.delete(url)
    assert resp.status_code == 400
    assert "confirm=true" in resp.json()["detail"]
    assert api_client.get(url).status_code == 200


def test_delete_keeps_guest_and_video(api_client, guest, video):
    participation = api_client.post(_url(guest["id"]), json={"video_id": video["id"]}).json()
    url = _url(guest["id"], participation["id"])
    assert api_client.delete(url + "?confirm=true").status_code == 204
    assert api_client.get(url).status_code == 404
    assert api_client.get(f"/guests/{guest['id']}").status_code == 200
    assert api_client.get(f"/videos/{video['id']}").status_code == 200
    # ya se puede volver a vincular
    assert api_client.post(_url(guest["id"]), json={"video_id": video["id"]}).status_code == 201


def test_deleting_guest_removes_participations_from_video_listing(api_client, guest, video):
    api_client.post(_url(guest["id"]), json={"video_id": video["id"]})
    assert api_client.delete(f"/guests/{guest['id']}?confirm=true").status_code == 204
    assert api_client.get(f"/videos/{video['id']}/participations").json() == []
