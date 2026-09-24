"""Pruebas de autenticación: login, /auth/me, rutas protegidas y tokens inválidos."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auth
from app.api.deps import require_admin, require_roles
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import Base
from app.db.session import get_db
from app.models.user import User
from app.services.users import create_admin
import app.models  # noqa: F401

PASSWORD = "clave-segura-123"


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secreto-de-pruebas-con-longitud-suficiente-32b")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(db_engine):
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/protected")
    def protected(user: User = Depends(require_admin)):
        return {"user": user.username}

    @app.get("/only-editors")
    def only_editors(user: User = Depends(require_roles("editor"))):
        return {"user": user.username}

    def override_get_db():
        with Session(db_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    with Session(db_engine) as s:
        create_admin(s, "admin", PASSWORD)
    return TestClient(app)


def _login(client, username="admin", password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_roundtrip():
    hashed = hash_password(PASSWORD)
    assert hashed != PASSWORD
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("otra", hashed)
    assert not verify_password(PASSWORD, "no-es-un-hash")


def test_login_ok_returns_token(client):
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_login_wrong_password(client):
    resp = _login(client, password="incorrecta")
    assert resp.status_code == 401


def test_login_unknown_user_same_message(client):
    wrong_pass = _login(client, password="incorrecta")
    unknown = _login(client, username="nadie")
    assert unknown.status_code == 401
    assert unknown.json() == wrong_pass.json()


def test_login_inactive_user(client, db_engine):
    with Session(db_engine) as s:
        s.query(User).filter_by(username="admin").one().is_active = False
        s.commit()
    assert _login(client).status_code == 401


def test_me_with_valid_token(client):
    token = _login(client).json()["access_token"]
    resp = client.get("/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json() == {"username": "admin", "role": "administrador"}


def test_protected_route_without_token(client):
    assert client.get("/protected").status_code == 401


def test_protected_route_with_valid_token(client):
    token = _login(client).json()["access_token"]
    resp = client.get("/protected", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json() == {"user": "admin"}


def test_invalid_token(client):
    resp = client.get("/protected", headers=_auth_header("token.invalido.xyz"))
    assert resp.status_code == 401


def test_expired_token(client):
    token = create_access_token("admin", "administrador", expires_minutes=-1)
    assert client.get("/protected", headers=_auth_header(token)).status_code == 401


def test_token_signed_with_other_secret(client, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "otro-secreto-distinto-con-longitud-suficiente")
    token = create_access_token("admin", "administrador")
    monkeypatch.setenv("JWT_SECRET", "secreto-de-pruebas-con-longitud-suficiente-32b")
    assert client.get("/protected", headers=_auth_header(token)).status_code == 401


def test_token_for_deleted_user(client, db_engine):
    token = _login(client).json()["access_token"]
    with Session(db_engine) as s:
        s.delete(s.query(User).filter_by(username="admin").one())
        s.commit()
    assert client.get("/protected", headers=_auth_header(token)).status_code == 401


def test_role_without_permission_gets_403(client):
    token = _login(client).json()["access_token"]
    assert client.get("/only-editors", headers=_auth_header(token)).status_code == 403


def test_create_admin_duplicate_and_empty(db_engine):
    with Session(db_engine) as s:
        create_admin(s, "otro", PASSWORD)
        with pytest.raises(ValueError, match="ya existe"):
            create_admin(s, "otro", PASSWORD)
        with pytest.raises(ValueError, match="obligatorios"):
            create_admin(s, "", PASSWORD)
