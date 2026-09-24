"""Pruebas de los 5 catálogos: listar, crear, renombrar, desactivar y protección."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auth
from app.api.catalogs import CATALOG_ROUTERS
from app.db.base import Base
from app.db.session import get_db
from app.services.users import create_admin
import app.models  # noqa: F401

PASSWORD = "clave-segura-123"
PREFIXES = ["/guest-categories", "/boroughs", "/video-types", "/contact-types", "/programs"]


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secreto-de-pruebas-con-longitud-suficiente-32b")


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(auth.router)
    for router in CATALOG_ROUTERS:
        app.include_router(router)

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
    yield c
    engine.dispose()


def test_router_prefixes_match_expected():
    assert sorted(r.prefix for r in CATALOG_ROUTERS) == sorted(PREFIXES)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_requires_authentication(client, prefix):
    anonymous = TestClient(client.app)
    assert anonymous.get(prefix).status_code == 401
    assert anonymous.post(prefix, json={"name": "X"}).status_code == 401
    assert anonymous.patch(f"{prefix}/1", json={"name": "X"}).status_code == 401


@pytest.mark.parametrize("prefix", PREFIXES)
def test_create_and_list(client, prefix):
    resp = client.post(prefix, json={"name": "  Cantante  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Cantante"
    assert resp.json()["is_active"] is True
    assert [i["name"] for i in client.get(prefix).json()] == ["Cantante"]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_duplicate_name_returns_409(client, prefix):
    client.post(prefix, json={"name": "Actor"})
    resp = client.post(prefix, json={"name": "actor"})  # sin distinguir mayúsculas
    assert resp.status_code == 409
    assert "Ya existe" in resp.json()["detail"]


@pytest.mark.parametrize(
    "existing, attempt",
    [
        ("Música", "musica"),
        ("musica", "MÚSICA"),
        ("Actor de cine", "actor  de   cine"),
        ("Álvaro Obregón", "alvaro obregon"),
        ("Cantante", "  CANTANTE "),
    ],
)
def test_duplicate_ignores_accents_case_and_extra_spaces(client, existing, attempt):
    assert client.post("/guest-categories", json={"name": existing}).status_code == 201
    resp = client.post("/guest-categories", json={"name": attempt})
    assert resp.status_code == 409
    assert existing in resp.json()["detail"]


def test_rename_to_accent_variant_of_other_returns_409(client):
    client.post("/programs", json={"name": "Café con noticias"})
    other = client.post("/programs", json={"name": "Otro programa"}).json()
    resp = client.patch(f"/programs/{other['id']}", json={"name": "cafe con noticias"})
    assert resp.status_code == 409


def test_rename_fixing_own_accent_is_ok(client):
    item = client.post("/programs", json={"name": "Musica en vivo"}).json()
    resp = client.patch(f"/programs/{item['id']}", json={"name": "Música en vivo"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Música en vivo"


def test_name_is_stored_as_typed_with_collapsed_spaces(client):
    resp = client.post("/boroughs", json={"name": "  Álvaro   Obregón "})
    assert resp.json()["name"] == "Álvaro Obregón"


def test_empty_or_long_name_rejected(client):
    assert client.post("/programs", json={"name": "   "}).status_code == 422
    assert client.post("/programs", json={"name": "x" * 151}).status_code == 422


def test_rename(client):
    item = client.post("/video-types", json={"name": "Entrevista"}).json()
    resp = client.patch(f"/video-types/{item['id']}", json={"name": "Entrevista larga"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Entrevista larga"


def test_rename_to_existing_name_returns_409(client):
    client.post("/video-types", json={"name": "Evento"})
    other = client.post("/video-types", json={"name": "Podcast"}).json()
    assert client.patch(f"/video-types/{other['id']}", json={"name": "Evento"}).status_code == 409


def test_rename_to_same_name_is_ok(client):
    item = client.post("/programs", json={"name": "Buenos días"}).json()
    assert client.patch(f"/programs/{item['id']}", json={"name": "Buenos días"}).status_code == 200


def test_deactivate_hides_from_default_list_and_reactivate(client):
    item = client.post("/guest-categories", json={"name": "Actor"}).json()
    resp = client.patch(f"/guest-categories/{item['id']}", json={"is_active": False})
    assert resp.json()["is_active"] is False
    assert client.get("/guest-categories").json() == []
    listed = client.get("/guest-categories", params={"include_inactive": True}).json()
    assert [i["name"] for i in listed] == ["Actor"]

    client.patch(f"/guest-categories/{item['id']}", json={"is_active": True})
    assert len(client.get("/guest-categories").json()) == 1


def test_update_unknown_id_returns_404(client):
    resp = client.patch("/boroughs/9999", json={"name": "Nada"})
    assert resp.status_code == 404
    assert "boroughs" in resp.json()["detail"]


def test_list_is_sorted_by_name(client):
    for name in ["Zeta", "alfa", "Beta"]:
        client.post("/contact-types", json={"name": name})
    assert [i["name"] for i in client.get("/contact-types").json()] == ["alfa", "Beta", "Zeta"]
