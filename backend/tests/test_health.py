"""Pruebas del endpoint /health (BD disponible y BD caída)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok(client):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine)

    def _db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_db_fails(client):
    class BrokenSession:
        def execute(self, *_a, **_k):
            raise RuntimeError("BD caída")

    def _db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = _db
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Base de datos no disponible"
