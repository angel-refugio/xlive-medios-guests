"""Fase 3, mejora de extracción: programa y conductores sugeridos por la ingesta (Staging Review).

Una fila por video con el programa del catálogo y los conductores que propone la ingesta. Son
candidatos hasta que un humano los revisa en Staging Review: recién entonces se asigna el
programa al video (`videos.program_id`) y los conductores al programa (`program_host_links`).

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staging_video_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=True),
        sa.Column("program_name", sa.String(150), nullable=True),
        sa.Column("host_names", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staging_video_suggestions")),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"],
            name=op.f("fk_staging_video_suggestions_video_id_videos"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name=op.f("fk_staging_video_suggestions_ingestion_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("video_id", name=op.f("uq_staging_video_suggestions_video_id")),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_staging_video_suggestions_status_valid"),
        ),
    )


def downgrade() -> None:
    op.drop_table("staging_video_suggestions")
