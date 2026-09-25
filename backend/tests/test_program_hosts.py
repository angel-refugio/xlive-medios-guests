"""Pruebas del vínculo programa ↔ conductores: listar, reemplazar y validaciones."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auth, program_hosts
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
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(auth.router)
    for router in CATALOG_ROUTERS:
        app.include_router(router)
    app.include_router(program_hosts.router)

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


def make(client, path, name):
    return client.post(path, json={"name": name}).json()["id"]


def test_requiere_autenticacion(client):
    anonymous = TestClient(client.app)
    assert anonymous.get("/program-hosts").status_code == 401
    assert anonymous.put("/program-hosts/1", json={"host_ids": []}).status_code == 401


def test_sin_vinculos_devuelve_lista_vacia(client):
    assert client.get("/program-hosts").json() == []


def test_asigna_varios_conductores_y_un_conductor_a_varios_programas(client):
    circus = make(client, "/programs", "Circus TV")
    v2h = make(client, "/programs", "V2H")
    yaner = make(client, "/hosts", "Yaner")
    gm = make(client, "/hosts", "GM")

    r = client.put(f"/program-hosts/{circus}", json={"host_ids": [yaner, gm]})
    assert r.status_code == 200
    assert client.put(f"/program-hosts/{v2h}", json={"host_ids": [yaner]}).status_code == 200

    links = client.get("/program-hosts").json()
    assert {(l["program_id"], l["host_id"]) for l in links} == {
        (circus, yaner), (circus, gm), (v2h, yaner),
    }


def test_put_reemplaza_el_conjunto_y_vacio_quita_todos(client):
    program = make(client, "/programs", "Inzzania TV")
    a = make(client, "/hosts", "Dante")
    b = make(client, "/hosts", "Otro")
    client.put(f"/program-hosts/{program}", json={"host_ids": [a, b]})

    r = client.put(f"/program-hosts/{program}", json={"host_ids": [b, b]})  # duplicado se ignora
    assert [l["host_id"] for l in r.json()] == [b]
    assert client.put(f"/program-hosts/{program}", json={"host_ids": []}).json() == []
    assert client.get("/program-hosts").json() == []


def test_programa_inexistente_da_404(client):
    r = client.put("/program-hosts/999", json={"host_ids": []})
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


def test_conductor_inexistente_da_422_y_no_cambia_nada(client):
    program = make(client, "/programs", "Programa")
    host = make(client, "/hosts", "Conductor")
    client.put(f"/program-hosts/{program}", json={"host_ids": [host]})

    r = client.put(f"/program-hosts/{program}", json={"host_ids": [host, 777]})
    assert r.status_code == 422
    assert "777" in r.json()["detail"]
    assert [l["host_id"] for l in client.get("/program-hosts").json()] == [host]


def test_conductor_desactivado_solo_se_acepta_si_ya_estaba_asignado(client):
    program = make(client, "/programs", "Programa")
    host = make(client, "/hosts", "Conductor")
    other = make(client, "/programs", "Otro programa")
    client.put(f"/program-hosts/{program}", json={"host_ids": [host]})
    client.patch(f"/hosts/{host}", json={"is_active": False})

    assert client.put(f"/program-hosts/{program}", json={"host_ids": [host]}).status_code == 200
    r = client.put(f"/program-hosts/{other}", json={"host_ids": [host]})
    assert r.status_code == 422
    assert "desactivado" in r.json()["detail"]
