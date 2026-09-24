"""Esquema inicial: catálogos, invitados, contactos, videos y participaciones.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CATALOGS = ("guest_categories", "boroughs", "video_types", "contact_types", "programs")


def upgrade() -> None:
    for table in CATALOGS:
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint("name", name=op.f(f"uq_{table}_name")),
        )

    op.create_table(
        "guests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("organization", sa.String(255)),
        sa.Column("role", sa.String(255)),
        sa.Column("notes", sa.Text()),
        sa.Column("approx_age", sa.Integer()),
        sa.Column("borough_id", sa.Integer()),
        sa.CheckConstraint(
            "approx_age IS NULL OR approx_age >= 0",
            name=op.f("ck_guests_approx_age_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["borough_id"], ["boroughs.id"],
            name=op.f("fk_guests_borough_id_boroughs"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guests")),
    )

    op.create_table(
        "guest_category_links",
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_id"], ["guests.id"],
            name=op.f("fk_guest_category_links_guest_id_guests"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["guest_categories.id"],
            name=op.f("fk_guest_category_links_category_id_guest_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("guest_id", "category_id", name=op.f("pk_guest_category_links")),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("contact_type_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("source", sa.String(30), server_default="manual", nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint(
            "source IN ('manual', 'video_description')",
            name=op.f("ck_contacts_source_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["guest_id"], ["guests.id"],
            name=op.f("fk_contacts_guest_id_guests"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_type_id"], ["contact_types.id"],
            name=op.f("fk_contacts_contact_type_id_contact_types"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("youtube_video_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("playlist", sa.String(255)),
        sa.Column("channel_id", sa.String(64)),
        sa.Column("channel_title", sa.String(255)),
        sa.Column("thumbnail_url", sa.String(500)),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("video_type_id", sa.Integer()),
        sa.Column("event_borough_id", sa.Integer()),
        sa.Column("program_id", sa.Integer()),
        sa.Column("part_of_video_id", sa.Integer()),
        sa.Column("guest_status", sa.String(20), server_default="pending", nullable=False),
        sa.CheckConstraint(
            "part_of_video_id IS NULL OR part_of_video_id <> id",
            name=op.f("ck_videos_not_part_of_itself"),
        ),
        sa.CheckConstraint(
            "guest_status IN ('pending', 'has_guests', 'no_guests')",
            name=op.f("ck_videos_guest_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["video_type_id"], ["video_types.id"],
            name=op.f("fk_videos_video_type_id_video_types"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_borough_id"], ["boroughs.id"],
            name=op.f("fk_videos_event_borough_id_boroughs"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"], ["programs.id"],
            name=op.f("fk_videos_program_id_programs"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["part_of_video_id"], ["videos.id"],
            name=op.f("fk_videos_part_of_video_id_videos"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
        sa.UniqueConstraint("youtube_video_id", name=op.f("uq_videos_youtube_video_id")),
    )

    op.create_table(
        "participations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(
            ["guest_id"], ["guests.id"],
            name=op.f("fk_participations_guest_id_guests"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"],
            name=op.f("fk_participations_video_id_videos"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participations")),
        sa.UniqueConstraint("guest_id", "video_id", name=op.f("uq_participations_guest_video")),
    )


def downgrade() -> None:
    for table in (
        "participations", "videos", "contacts", "guest_category_links", "guests",
        *CATALOGS,
    ):
        op.drop_table(table)
