"""Catálogos configurables. Se desactivan (is_active) en lugar de borrarse."""
from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CatalogMixin:
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)


class GuestCategory(CatalogMixin, Base):
    """Categoría del invitado = tipo de talento (cantante, actor…)."""

    __tablename__ = "guest_categories"


class Borough(CatalogMixin, Base):
    """Alcaldías de la CDMX (editable)."""

    __tablename__ = "boroughs"


class VideoType(CatalogMixin, Base):
    """Tipo de video: entrevista, evento, podcast…"""

    __tablename__ = "video_types"


class ContactType(CatalogMixin, Base):
    """Tipo de contacto: celular, correo, Instagram, patrocinador…"""

    __tablename__ = "contact_types"


class Program(CatalogMixin, Base):
    """Programa del canal (opcional para los videos)."""

    __tablename__ = "programs"
