"""Pruebas de contactos: CRUD anidado bajo el invitado, tipo del catálogo y parciales."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auth, contacts, guests
from app.api.catalogs import CATALOG_ROUTERS
from app.db.base import Base
from app.db.session import get_db
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
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

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
    app.include_router(contacts.router)

    def override_get_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    with Session(engine) as s:
        create_admin(s, "admin", PASSWORD)
    c = TestClient(app)
    token = c.post("/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "access_token"
    ]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.fixture()
def guest(client):
    return client.post("/guests", json={"full_name": "Ana López"}).json()


@pytest.fixture()
def phone_type(client):
    return client.post("/contact-types", json={"name": "Celular"}).json()


def _url(guest_id, contact_id=None):
    base = f"/guests/{guest_id}/contacts"
    return base if contact_id is None else f"{base}/{contact_id}"


def test_requires_authentication(client, guest):
    anonymous = TestClient(client.app)
    assert anonymous.get(_url(guest["id"])).status_code == 401
    assert anonymous.post(_url(guest["id"]), json={}).status_code == 401
    assert anonymous.patch(_url(guest["id"], 1), json={}).status_code == 401
    assert anonymous.delete(_url(guest["id"], 1) + "?confirm=true").status_code == 401


def test_create_minimal_uses_defaults(client, guest, phone_type):
    resp = client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": " 5512345678 "})
    assert resp.status_code == 201
    body = resp.json()
    assert body["value"] == "5512345678"
    assert body["contact_type"]["name"] == "Celular"
    assert body["source"] == "manual"
    assert body["verified"] is False
    assert body["note"] is None
    assert body["guest_id"] == guest["id"]


def test_create_full(client, guest, phone_type):
    resp = client.post(
        _url(guest["id"]),
        json={
            "contact_type_id": phone_type["id"],
            "value": "5500000000",
            "note": "WhatsApp de su representante",
            "source": "video_description",
            "verified": True,
        },
    )
    body = resp.json()
    assert resp.status_code == 201
    assert (body["note"], body["source"], body["verified"]) == (
        "WhatsApp de su representante",
        "video_description",
        True,
    )


def test_create_validation_errors(client, guest, phone_type):
    url = _url(guest["id"])
    assert client.post(url, json={"value": "x"}).status_code == 422  # falta el tipo
    assert client.post(url, json={"contact_type_id": phone_type["id"]}).status_code == 422  # falta el valor
    assert client.post(url, json={"contact_type_id": phone_type["id"], "value": "   "}).status_code == 422
    assert client.post(url, json={"contact_type_id": phone_type["id"], "value": "x" * 501}).status_code == 422
    assert (
        client.post(url, json={"contact_type_id": phone_type["id"], "value": "1", "source": "otro"}).status_code
        == 422
    )


def test_unknown_or_inactive_contact_type_returns_422(client, guest, phone_type):
    url = _url(guest["id"])
    assert client.post(url, json={"contact_type_id": 999, "value": "1"}).status_code == 422
    client.patch(f"/contact-types/{phone_type['id']}", json={"is_active": False})
    resp = client.post(url, json={"contact_type_id": phone_type["id"], "value": "1"})
    assert resp.status_code == 422
    assert "desactivado" in resp.json()["detail"]


def test_unknown_guest_returns_404_everywhere(client, phone_type):
    assert client.get(_url(9999)).status_code == 404
    assert client.post(_url(9999), json={"contact_type_id": phone_type["id"], "value": "1"}).status_code == 404
    assert client.get(_url(9999, 1)).status_code == 404
    assert client.patch(_url(9999, 1), json={"verified": True}).status_code == 404
    assert client.delete(_url(9999, 1) + "?confirm=true").status_code == 404


def test_list_only_returns_contacts_of_that_guest(client, guest, phone_type):
    other = client.post("/guests", json={"full_name": "Otro"}).json()
    client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"})
    client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "2"})
    client.post(_url(other["id"]), json={"contact_type_id": phone_type["id"], "value": "3"})
    assert [c["value"] for c in client.get(_url(guest["id"])).json()] == ["1", "2"]
    assert [c["value"] for c in client.get(_url(other["id"])).json()] == ["3"]


def test_guest_without_contacts_returns_empty_list(client, guest):
    assert client.get(_url(guest["id"])).json() == []


def test_contact_of_another_guest_is_404(client, guest, phone_type):
    other = client.post("/guests", json={"full_name": "Otro"}).json()
    contact = client.post(_url(other["id"]), json={"contact_type_id": phone_type["id"], "value": "1"}).json()
    assert client.get(_url(guest["id"], contact["id"])).status_code == 404
    assert client.patch(_url(guest["id"], contact["id"]), json={"verified": True}).status_code == 404
    assert client.delete(_url(guest["id"], contact["id"]) + "?confirm=true").status_code == 404
    assert client.get(_url(other["id"], contact["id"])).status_code == 200  # sigue intacto


def test_patch_partial_keeps_other_fields(client, guest, phone_type):
    contact = client.post(
        _url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1", "note": "nota"}
    ).json()
    resp = client.patch(_url(guest["id"], contact["id"]), json={"verified": True})
    body = resp.json()
    assert (body["verified"], body["value"], body["note"]) == (True, "1", "nota")


def test_patch_change_type_and_clear_note(client, guest, phone_type):
    email = client.post("/contact-types", json={"name": "Correo"}).json()
    contact = client.post(
        _url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "a@b.com", "note": "x"}
    ).json()
    resp = client.patch(
        _url(guest["id"], contact["id"]), json={"contact_type_id": email["id"], "note": None}
    )
    assert resp.json()["contact_type"]["name"] == "Correo"
    assert resp.json()["note"] is None


def test_patch_rejects_nulls_and_bad_references(client, guest, phone_type):
    contact = client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"}).json()
    url = _url(guest["id"], contact["id"])
    assert client.patch(url, json={"value": None}).status_code == 422
    assert client.patch(url, json={"value": "  "}).status_code == 422
    assert client.patch(url, json={"contact_type_id": None}).status_code == 422
    assert client.patch(url, json={"contact_type_id": 999}).status_code == 422
    assert client.patch(url, json={"verified": None}).status_code == 422
    assert client.get(url).json()["value"] == "1"  # nada cambió


def test_patch_keeps_inactive_type_already_assigned(client, guest, phone_type):
    contact = client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"}).json()
    client.patch(f"/contact-types/{phone_type['id']}", json={"is_active": False})
    resp = client.patch(
        _url(guest["id"], contact["id"]), json={"contact_type_id": phone_type["id"], "verified": True}
    )
    assert resp.status_code == 200


def test_patch_unknown_contact_returns_404(client, guest):
    assert client.patch(_url(guest["id"], 9999), json={"verified": True}).status_code == 404


def test_delete_contact_requires_confirmation(client, guest, phone_type):
    contact = client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"}).json()
    resp = client.delete(_url(guest["id"], contact["id"]))
    assert resp.status_code == 400
    assert "confirm=true" in resp.json()["detail"]
    assert client.delete(_url(guest["id"], contact["id"]) + "?confirm=false").status_code == 400
    assert client.get(_url(guest["id"], contact["id"])).status_code == 200  # sigue existiendo


def test_delete_contact(client, guest, phone_type):
    contact = client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"}).json()
    assert client.delete(_url(guest["id"], contact["id"]) + "?confirm=true").status_code == 204
    assert client.get(_url(guest["id"], contact["id"])).status_code == 404
    assert client.get(_url(guest["id"])).json() == []
    assert client.get(f"/guests/{guest['id']}").status_code == 200  # el invitado no se toca


def test_deleting_guest_removes_its_contacts(client, guest, phone_type, engine):
    from app.models.contact import Contact

    client.post(_url(guest["id"]), json={"contact_type_id": phone_type["id"], "value": "1"})
    assert client.delete(f"/guests/{guest['id']}?confirm=true").status_code == 204
    with Session(engine) as s:
        assert s.query(Contact).count() == 0
