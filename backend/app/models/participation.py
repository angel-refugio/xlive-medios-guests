"""Participación: aparición de un invitado en un video (N↔N)."""
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Participation(Base):
    __tablename__ = "participations"
    __table_args__ = (UniqueConstraint("guest_id", "video_id", name="uq_participations_guest_video"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    notes: Mapped[str | None] = mapped_column(Text)

    guest: Mapped["Guest"] = relationship(back_populates="participations")  # noqa: F821
    video: Mapped["Video"] = relationship(back_populates="participations")  # noqa: F821
