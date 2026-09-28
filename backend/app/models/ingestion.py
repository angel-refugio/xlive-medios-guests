"""Fase 3: registro de corridas de ingesta y candidatos en revisión (Staging Review).

Todo lo que produce el pipeline (reglas de regex + LLM) es candidato: vive aquí, separado de
las tablas finales (`guests`, `contacts`), hasta que un humano lo acepta, edita o rechaza desde
la app (paso 7, todavía sin implementar). Reglas de contenido: ver docs/PHASE3_PLAN.md.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

_CONFIDENCE_RANGE = "{col} >= 0 AND {col} <= 1"
_EXTRACTION_METHOD_VALUES = "extraction_method IN ('regex', 'llm')"
_STATUS_VALUES = "status IN ('pending', 'accepted', 'rejected')"


class IngestionRun(Base):
    """Una corrida del pipeline (manual o, en una fase final, programada; FR-011)."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), server_default="running", default="running")
    trigger: Mapped[str] = mapped_column(String(20), server_default="manual", default="manual")
    # Tamaño de lote pedido (ej. 30); puede diferir de processed_count si el canal tenía menos.
    requested_batch_size: Mapped[int | None]
    processed_count: Mapped[int] = mapped_column(server_default="0", default=0)
    success_count: Mapped[int] = mapped_column(server_default="0", default=0)
    error_count: Mapped[int] = mapped_column(server_default="0", default=0)

    errors: Mapped[list["IngestionRunError"]] = relationship(
        back_populates="ingestion_run", cascade="all, delete-orphan", passive_deletes=True
    )


class IngestionRunError(Base):
    """Un error puntual dentro de una corrida; no detiene el resto del lote (paso 6)."""

    __tablename__ = "ingestion_run_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingestion_run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE")
    )
    # No siempre hay un Video creado (p. ej. si falló la llamada a YouTube antes de guardarlo).
    youtube_video_id: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="errors")


class StagingGuestCandidate(Base):
    """Invitado candidato propuesto para un video, pendiente de revisión humana."""

    __tablename__ = "staging_guest_candidates"
    __table_args__ = (
        CheckConstraint(_STATUS_VALUES, name="status_valid"),
        CheckConstraint(_EXTRACTION_METHOD_VALUES, name="extraction_method_valid"),
        CheckConstraint(
            _CONFIDENCE_RANGE.format(col="raw_confidence"), name="raw_confidence_range"
        ),
        CheckConstraint(
            _CONFIDENCE_RANGE.format(col="adjusted_confidence"), name="adjusted_confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    # Se conserva aunque se borre el historial de la corrida (ver IngestionRun.errors, que sí
    # se borra en cascada): el candidato pendiente de revisión no debe perderse por eso.
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )

    extracted_name: Mapped[str] = mapped_column(String(255))
    # Señales objetivas usadas para el ajuste de confianza (regla del pipeline).
    found_in_title: Mapped[bool]
    found_in_description: Mapped[bool]
    is_possible_group: Mapped[bool] = mapped_column(server_default="false", default=False)
    # Nombre de categoría existente o sugerencia de categoría nueva; texto libre hasta revisión.
    category_match: Mapped[str | None] = mapped_column(String(150))
    category_is_new_suggestion: Mapped[bool] = mapped_column(server_default="false", default=False)
    # Cruda del LLM/regex y la ya ajustada con señales objetivas (Staging Review ordena por esta).
    raw_confidence: Mapped[float] = mapped_column(Float)
    adjusted_confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(20), server_default="pending", default="pending")
    # Se llena al aceptar (crea o vincula un Guest existente); nunca antes.
    linked_guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guests.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    video: Mapped["Video"] = relationship()  # noqa: F821
    contacts: Mapped[list["StagingContactCandidate"]] = relationship(
        back_populates="guest_candidate"
    )


class StagingContactCandidate(Base):
    """Contacto candidato para un video, opcionalmente atado a un invitado candidato."""

    __tablename__ = "staging_contact_candidates"
    __table_args__ = (
        CheckConstraint(_STATUS_VALUES, name="status_valid"),
        CheckConstraint(_EXTRACTION_METHOD_VALUES, name="extraction_method_valid"),
        CheckConstraint(
            _CONFIDENCE_RANGE.format(col="raw_confidence"), name="raw_confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    # Null = contacto a nivel video/evento (p. ej. patrocinador), no de un invitado en concreto.
    guest_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_guest_candidates.id", ondelete="SET NULL")
    )

    # Pista de tipo en texto libre (p. ej. "instagram", "celular"); se empareja contra
    # `contact_types` en Staging Review, no aquí.
    type_hint: Mapped[str] = mapped_column(String(150))
    value: Mapped[str] = mapped_column(String(500))
    raw_confidence: Mapped[float] = mapped_column(Float)
    extraction_method: Mapped[str] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(20), server_default="pending", default="pending")
    linked_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    video: Mapped["Video"] = relationship()  # noqa: F821
    guest_candidate: Mapped[StagingGuestCandidate | None] = relationship(back_populates="contacts")
