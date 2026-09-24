"""Invitado y su vínculo N↔N con categorías."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.catalogs import Borough, GuestCategory

guest_category_links = Table(
    "guest_category_links",
    Base.metadata,
    Column("guest_id", ForeignKey("guests.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "category_id",
        ForeignKey("guest_categories.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Guest(Base):
    __tablename__ = "guests"
    __table_args__ = (
        CheckConstraint("approx_age IS NULL OR approx_age >= 0", name="approx_age_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    approx_age: Mapped[int | None]
    borough_id: Mapped[int | None] = mapped_column(
        ForeignKey("boroughs.id", ondelete="RESTRICT")
    )

    borough: Mapped[Borough | None] = relationship()
    categories: Mapped[list[GuestCategory]] = relationship(secondary=guest_category_links)
    contacts: Mapped[list["Contact"]] = relationship(  # noqa: F821
        back_populates="guest", cascade="all, delete-orphan", passive_deletes=True
    )
    participations: Mapped[list["Participation"]] = relationship(  # noqa: F821
        back_populates="guest", cascade="all, delete-orphan", passive_deletes=True
    )
