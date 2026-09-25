"""Conductores (catálogo) y su vínculo N↔N con los programas.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hosts")),
        sa.UniqueConstraint("name", name=op.f("uq_hosts_name")),
    )
    op.create_table(
        "program_host_links",
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["program_id"], ["programs.id"],
            name=op.f("fk_program_host_links_program_id_programs"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"],
            name=op.f("fk_program_host_links_host_id_hosts"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("program_id", "host_id", name=op.f("pk_program_host_links")),
    )


def downgrade() -> None:
    op.drop_table("program_host_links")
    op.drop_table("hosts")
