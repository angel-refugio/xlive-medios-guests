"""Usuarios de la app. Por ahora solo existe el rol "administrador" (todos los permisos)."""
from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROLE_ADMIN = "administrador"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Texto (no enum de BD) para poder agregar roles después sin migración.
    role: Mapped[str] = mapped_column(String(50), default=ROLE_ADMIN, server_default=ROLE_ADMIN)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
