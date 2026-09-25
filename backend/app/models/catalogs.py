"""Catálogos configurables. Se desactivan (is_active) en lugar de borrarse."""
from sqlalchemy import Boolean, Column, ForeignKey, String, Table, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class Host(CatalogMixin, Base):
    """Conductor: quien presenta un programa (no es un invitado)."""

    __tablename__ = "hosts"


program_host_links = Table(
    "program_host_links",
    Base.metadata,
    Column("program_id", ForeignKey("programs.id", ondelete="CASCADE"), primary_key=True),
    Column("host_id", ForeignKey("hosts.id", ondelete="RESTRICT"), primary_key=True),
)


class Program(CatalogMixin, Base):
    """Programa del canal (opcional para los videos) y sus conductores (N↔N)."""

    __tablename__ = "programs"

    hosts: Mapped[list[Host]] = relationship(secondary=program_host_links)
