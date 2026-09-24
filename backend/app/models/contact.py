"""Contactos del invitado (1→N). El tipo viene del catálogo contact_types."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.catalogs import ContactType


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'video_description')", name="source_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"))
    contact_type_id: Mapped[int] = mapped_column(
        ForeignKey("contact_types.id", ondelete="RESTRICT")
    )
    value: Mapped[str] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(30), server_default="manual", default="manual")
    verified: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)

    guest: Mapped["Guest"] = relationship(back_populates="contacts")  # noqa: F821
    contact_type: Mapped[ContactType] = relationship()
