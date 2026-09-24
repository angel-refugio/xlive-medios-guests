"""Endpoints de autenticación: login y datos del usuario actual."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    username: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.execute(select(User).where(User.username == data.username)).scalar_one_or_none()
    # Mismo mensaje para usuario inexistente, inactivo o contraseña errada (no filtra qué falló).
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        logger.warning("[app.api.auth.login] Login fallido para usuario %r", data.username)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return TokenResponse(access_token=create_access_token(user.username, user.role))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(username=user.username, role=user.role)
