"""Video de YouTube. Los metadatos crudos viven aquí, separados de los invitados."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint(
            "part_of_video_id IS NULL OR part_of_video_id <> id", name="not_part_of_itself"
        ),
        CheckConstraint(
            "guest_status IN ('pending', 'has_guests', 'no_guests')", name="guest_status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    playlist: Mapped[str | None] = mapped_column(String(255))
    channel_id: Mapped[str | None] = mapped_column(String(64))
    channel_title: Mapped[str | None] = mapped_column(String(255))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    duration_seconds: Mapped[int | None]

    video_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_types.id", ondelete="RESTRICT")
    )
    event_borough_id: Mapped[int | None] = mapped_column(
        ForeignKey("boroughs.id", ondelete="RESTRICT")
    )
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="RESTRICT")
    )
    # Si se borra el video original, sus "partes" quedan como videos independientes.
    part_of_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL")
    )
    guest_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending"
    )

    participations: Mapped[list["Participation"]] = relationship(  # noqa: F821
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )
