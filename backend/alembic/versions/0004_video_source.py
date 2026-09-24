"""Origen del video: 'manual' (cargado desde la app) o 'youtube' (ingesta).

Permite identificar y borrar los videos manuales/de prueba cuando lleguen los reales.
Los videos existentes quedan como 'manual'.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        op.f("ck_videos_source_valid"), "videos", "source IN ('manual', 'youtube')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_videos_source_valid"), "videos", type_="check")
    op.drop_column("videos", "source")
