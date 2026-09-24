"""Fixtures compartidas. Las pruebas de modelo usan SQLite en memoria (sin Docker)."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.base import Base
import app.models  # noqa: F401


API_PASSWORD = "clave-segura-123"
API_JWT_SECRET = "secreto-de-pruebas-con-longitud-suficiente-32b"


@pytest.fixture()
def api_engine():
    """Engine SQLite compartido por la API de prueba, con FKs activas (como PostgreSQL)."""
    from sqlalchemy.pool import StaticPool

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
def api_client(api_engine, monkeypatch):
    """Cliente HTTP autenticado como administrador contra la app completa."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app
    from app.services.users import create_admin

    monkeypatch.setenv("JWT_SECRET", API_JWT_SECRET)

    def override_get_db():
        with Session(api_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    with Session(api_engine) as s:
        create_admin(s, "admin", API_PASSWORD)
    client = TestClient(app)
    token = client.post(
        "/auth/login", json={"username": "admin", "password": API_PASSWORD}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _record):
        # SQLite no aplica FKs por defecto; PostgreSQL sí.
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()
