"""Pruebas de invitados: CRUD, categorías N↔N al vuelo, alcaldía, paginación y borrado."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auth, guests
from app.api.catalogs import CATALOG_ROUTERS
from app.db.base import Base
from app.db.session import get_db
from app.models.catalogs import Borough, ContactType, GuestCategory
from app.models.contact import Contact
from app.models.guest import Guest
from app.models.participation import Participation
from app.models.video import Video
from app.services.users import create_admin
import app.models  # noqa: F401

PASSWORD = "clave-segura-123"


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secreto-de-pruebas-con-longitud-suficiente-32b")


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # como PostgreSQL: aplica ON DELETE CASCADE

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(engine):
    app = FastAPI()
    app.include_router(auth.router)
    for router in CATALOG_ROUTERS:
        app.include_router(router)
    app.include_router(guests.router)

    def override_get_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    with Session(engine) as s:
        create_admin(s, "admin", PASSWORD)
        s.add(Borough(name="Coyoacán"))
        s.commit()
    c = TestClient(app)
    token = c.post("/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "access_token"
    ]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _borough_id(engine):
    with Session(engine) as s:
        return s.query(Borough).filter_by(name="Coyoacán").one().id


def test_requires_authentication(client):
    anonymous = TestClient(client.app)
    assert anonymous.get("/guests").status_code == 401
    assert anonymous.post("/guests", json={"full_name": "Ana"}).status_code == 401
    assert anonymous.get("/guests/1").status_code == 401
    assert anonymous.patch("/guests/1", json={}).status_code == 401
    assert anonymous.delete("/guests/1?confirm=true").status_code == 401


def test_create_with_only_name(client):
    resp = client.post("/guests", json={"full_name": "  Ana   López "})
    assert resp.status_code == 201
    body = resp.json()
    assert body["full_name"] == "Ana López"
    assert body["approx_age"] is None
    assert body["borough"] is None
    assert body["categories"] == []


def test_create_requires_name(client):
    assert client.post("/guests", json={}).status_code == 422
    assert client.post("/guests", json={"full_name": "   "}).status_code == 422


def test_create_full(client, engine):
    borough_id = _borough_id(engine)
    resp = client.post(
        "/guests",
        json={
            "full_name": "Luis Pérez",
            "organization": " Banda X ",
            "role": "Vocalista",
            "notes": "",
            "approx_age": 34,
            "borough_id": borough_id,
            "new_categories": ["Cantante"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["organization"] == "Banda X"
    assert body["notes"] is None  # texto vacío = sin dato
    assert body["borough"]["name"] == "Coyoacán"
    assert [c["name"] for c in body["categories"]] == ["Cantante"]


@pytest.mark.parametrize("age", [-1, 121])
def test_age_out_of_range_rejected(client, age):
    assert client.post("/guests", json={"full_name": "Ana", "approx_age": age}).status_code == 422


def test_categories_by_id_and_on_the_fly_without_duplicates(client):
    existing = client.post("/guest-categories", json={"name": "Actor"}).json()
    resp = client.post(
        "/guests",
        json={
            "full_name": "Marta",
            "category_ids": [existing["id"]],
            # "actor" ya existe (ignora mayúsculas): no debe crear otra; "Músico" sí es nueva
            "new_categories": ["actor", "Músico"],
        },
    )
    assert resp.status_code == 201
    assert sorted(c["name"] for c in resp.json()["categories"]) == ["Actor", "Músico"]
    names = [c["name"] for c in client.get("/guest-categories").json()]
    assert names == ["Actor", "Músico"]


def test_on_the_fly_reuses_accent_variant(client):
    client.post("/guest-categories", json={"name": "Música"})
    resp = client.post("/guests", json={"full_name": "Tomás", "new_categories": ["musica"]})
    assert [c["name"] for c in resp.json()["categories"]] == ["Música"]
    assert len(client.get("/guest-categories").json()) == 1


def test_unknown_category_or_borough_returns_422(client):
    assert client.post("/guests", json={"full_name": "A", "category_ids": [999]}).status_code == 422
    assert client.post("/guests", json={"full_name": "A", "borough_id": 999}).status_code == 422


def test_failed_create_does_not_leave_new_categories(client):
    resp = client.post(
        "/guests", json={"full_name": "A", "new_categories": ["Nueva"], "category_ids": [999]}
    )
    assert resp.status_code == 422
    assert client.get("/guest-categories").json() == []
    assert client.get("/guests").json()["total"] == 0


def test_inactive_category_or_borough_rejected_for_new_assignment(client, engine):
    cat = client.post("/guest-categories", json={"name": "Vieja"}).json()
    client.patch(f"/guest-categories/{cat['id']}", json={"is_active": False})
    assert client.post("/guests", json={"full_name": "A", "category_ids": [cat["id"]]}).status_code == 422
    assert client.post("/guests", json={"full_name": "A", "new_categories": ["vieja"]}).status_code == 422

    borough_id = _borough_id(engine)
    client.patch(f"/boroughs/{borough_id}", json={"is_active": False})
    assert client.post("/guests", json={"full_name": "A", "borough_id": borough_id}).status_code == 422


def test_inactive_category_kept_when_already_assigned(client):
    cat = client.post("/guest-categories", json={"name": "Vieja"}).json()
    guest = client.post("/guests", json={"full_name": "A", "category_ids": [cat["id"]]}).json()
    client.patch(f"/guest-categories/{cat['id']}", json={"is_active": False})
    resp = client.patch(f"/guests/{guest['id']}", json={"category_ids": [cat["id"]], "role": "X"})
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()["categories"]] == ["Vieja"]


def test_get_and_404(client):
    guest = client.post("/guests", json={"full_name": "Ana"}).json()
    assert client.get(f"/guests/{guest['id']}").json()["full_name"] == "Ana"
    resp = client.get("/guests/9999")
    assert resp.status_code == 404
    assert "9999" in resp.json()["detail"]


def test_patch_partial_keeps_other_fields(client):
    guest = client.post(
        "/guests", json={"full_name": "Ana", "role": "Actriz", "approx_age": 30, "new_categories": ["Actor"]}
    ).json()
    resp = client.patch(f"/guests/{guest['id']}", json={"approx_age": 31})
    body = resp.json()
    assert body["approx_age"] == 31
    assert body["role"] == "Actriz"
    assert body["full_name"] == "Ana"
    assert [c["name"] for c in body["categories"]] == ["Actor"]  # sin tocar


def test_patch_null_clears_field_and_borough(client, engine):
    guest = client.post(
        "/guests", json={"full_name": "Ana", "role": "Actriz", "borough_id": _borough_id(engine)}
    ).json()
    resp = client.patch(f"/guests/{guest['id']}", json={"role": None, "borough_id": None})
    assert resp.json()["role"] is None
    assert resp.json()["borough"] is None


def test_patch_full_name_cannot_be_null(client):
    guest = client.post("/guests", json={"full_name": "Ana"}).json()
    assert client.patch(f"/guests/{guest['id']}", json={"full_name": None}).status_code == 422


def test_patch_replaces_categories(client):
    guest = client.post("/guests", json={"full_name": "Ana", "new_categories": ["Actor", "Cantante"]}).json()
    keep = next(c["id"] for c in guest["categories"] if c["name"] == "Cantante")
    resp = client.patch(f"/guests/{guest['id']}", json={"category_ids": [keep], "new_categories": ["Conductor"]})
    assert sorted(c["name"] for c in resp.json()["categories"]) == ["Cantante", "Conductor"]
    # lista vacía = quitar todas
    resp = client.patch(f"/guests/{guest['id']}", json={"category_ids": []})
    assert resp.json()["categories"] == []


def test_patch_unknown_guest_returns_404(client):
    assert client.patch("/guests/9999", json={"role": "X"}).status_code == 404


def test_pagination_default_and_custom(client):
    for i in range(5):
        client.post("/guests", json={"full_name": f"Invitado {i}"})
    default = client.get("/guests").json()
    assert (default["total"], default["page"], default["page_size"]) == (5, 1, 50)
    assert len(default["items"]) == 5

    page2 = client.get("/guests", params={"page": 2, "page_size": 2}).json()
    assert [g["full_name"] for g in page2["items"]] == ["Invitado 2", "Invitado 3"]
    assert page2["total"] == 5
    assert client.get("/guests", params={"page": 3, "page_size": 2}).json()["items"][0]["full_name"] == "Invitado 4"
    assert client.get("/guests", params={"page": 9, "page_size": 2}).json()["items"] == []


def test_pagination_invalid_params_rejected(client):
    assert client.get("/guests", params={"page": 0}).status_code == 422
    assert client.get("/guests", params={"page_size": 0}).status_code == 422
    assert client.get("/guests", params={"page_size": 201}).status_code == 422


def test_list_sorted_by_name_ignoring_case(client):
    for name in ["zoe", "Ana", "beto"]:
        client.post("/guests", json={"full_name": name})
    assert [g["full_name"] for g in client.get("/guests").json()["items"]] == ["Ana", "beto", "zoe"]


def test_delete_requires_confirmation(client):
    guest = client.post("/guests", json={"full_name": "Ana"}).json()
    resp = client.delete(f"/guests/{guest['id']}")
    assert resp.status_code == 400
    assert "confirm=true" in resp.json()["detail"]
    assert client.get(f"/guests/{guest['id']}").status_code == 200


def test_delete_cascades_contacts_and_participations_but_keeps_catalogs_and_videos(client, engine):
    guest = client.post("/guests", json={"full_name": "Ana", "new_categories": ["Actor"]}).json()
    with Session(engine) as s:
        contact_type = ContactType(name="Celular")
        video = Video(youtube_video_id="abc123", title="Entrevista")
        s.add_all([contact_type, video])
        s.flush()
        s.add(Contact(guest_id=guest["id"], contact_type_id=contact_type.id, value="555"))
        s.add(Participation(guest_id=guest["id"], video_id=video.id))
        s.commit()

    assert client.delete(f"/guests/{guest['id']}?confirm=true").status_code == 204
    assert client.get(f"/guests/{guest['id']}").status_code == 404
    with Session(engine) as s:
        assert s.query(Guest).count() == 0
        assert s.query(Contact).count() == 0
        assert s.query(Participation).count() == 0
        assert s.query(Video).count() == 1
        assert s.query(ContactType).count() == 1
        assert s.query(GuestCategory).count() == 1


def test_delete_unknown_guest_returns_404(client):
    assert client.delete("/guests/9999?confirm=true").status_code == 404
