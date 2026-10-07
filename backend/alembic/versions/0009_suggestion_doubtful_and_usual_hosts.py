"""Staging Review: nombres dudosos y conductores habituales en la sugerencia de cada video.

Agrega a `staging_video_suggestions`:
- `doubtful_names`: nombres que la ingesta no pudo clasificar (por ejemplo hashtags), con la
  opinión del LLM como pista; el humano decide "→ invitado" o "→ conductor" con un clic.
- `usual_host_names`: conductores que se repiten en la serie del video pero que el texto del
  video no menciona; se ofrecen como sugerencia de un clic.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "staging_video_suggestions",
        sa.Column("doubtful_names", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "staging_video_suggestions",
        sa.Column("usual_host_names", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("staging_video_suggestions", "usual_host_names")
    op.drop_column("staging_video_suggestions", "doubtful_names")
