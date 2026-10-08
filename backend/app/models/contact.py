"""Contactos del invitado (1→N). El tipo viene del catálogo contact_types.

Modelo objetivo de la adenda de contactos (`docs/PHASE3_PLAN.md`): el invitado puede faltar
("sin asignar"), el valor se guarda también normalizado para no duplicar, y cada contacto lleva
relación (propio / mánager / patrocinador), video de origen, evidencia y estado.

`verified` se conserva por compatibilidad con la API y la interfaz actuales; `status` es el
estado nuevo (todo lo que ya existía queda `validated`).
"""
import re

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.catalogs import ContactRelationship, ContactType

_SCHEME_WWW_RE = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)
_PHONE_LIKE_RE = re.compile(r"[+\d\s().-]{7,}")


def normalize_contact_value(value: str) -> str:
    """Forma comparable de un contacto: minúsculas, sin `http(s)://`, `www.` ni `/` final;
    los teléfonos quedan solo con dígitos (y sin la lada 52 de México) para que
    "+52 55 1234 5678" y "5512345678" cuenten como el mismo."""
    text = " ".join(value.split())
    if _PHONE_LIKE_RE.fullmatch(text):
        digits = re.sub(r"\D", "", text)
        return digits[2:] if len(digits) == 12 and digits.startswith("52") else digits
    return _SCHEME_WWW_RE.sub("", text.lower()).rstrip("/")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'video_description')", name="source_valid"),
        CheckConstraint("status IN ('candidate', 'validated', 'rejected')", name="status_valid"),
        UniqueConstraint(
            "guest_id", "contact_type_id", "normalized_value", name="uq_contacts_guest_type_value"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null = contacto sin asignar (p. ej. su invitado candidato se rechazó); puede reasignarse.
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"))
    contact_type_id: Mapped[int] = mapped_column(
        ForeignKey("contact_types.id", ondelete="RESTRICT")
    )
    value: Mapped[str] = mapped_column(String(500))
    # Se llena solo al asignar `value` (ver `_sync_normalized_value`); base de la restricción única.
    normalized_value: Mapped[str] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(30), server_default="manual", default="manual")
    verified: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # Propio / mánager / patrocinador: el patrocinador y el mánager son contactos DEL invitado.
    relationship_id: Mapped[int | None] = mapped_column(
        ForeignKey("contact_relationships.id", ondelete="RESTRICT")
    )
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="validated", default="validated")

    guest: Mapped["Guest | None"] = relationship(back_populates="contacts")  # noqa: F821
    contact_type: Mapped[ContactType] = relationship()
    relation: Mapped[ContactRelationship | None] = relationship()

    @validates("value")
    def _sync_normalized_value(self, _key: str, value: str) -> str:
        self.normalized_value = normalize_contact_value(value)
        return value
