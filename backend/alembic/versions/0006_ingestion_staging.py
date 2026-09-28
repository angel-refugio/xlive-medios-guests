"""Fase 3, paso 2: corridas de ingesta y candidatos en revisión (Staging Review).

Agrega `videos.possible_duplicate_of_video_id` y 4 tablas nuevas: `ingestion_runs`,
`ingestion_run_errors`, `staging_guest_candidates` y `staging_contact_candidates`.
Nada de esto reemplaza a `guests`/`contacts`: son candidatos hasta que un humano los revisa
(paso 7, todavía sin implementar).

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("possible_duplicate_of_video_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_videos_possible_duplicate_of_video_id_videos"),
        "videos", "videos",
        ["possible_duplicate_of_video_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("trigger", sa.String(20), server_default="manual", nullable=False),
        sa.Column("requested_batch_size", sa.Integer(), nullable=True),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("success_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_ingestion_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name=op.f("ck_ingestion_runs_trigger_valid")
        ),
    )

    op.create_table(
        "ingestion_run_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("youtube_video_id", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_run_errors")),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name=op.f("fk_ingestion_run_errors_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "staging_guest_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=True),
        sa.Column("extracted_name", sa.String(255), nullable=False),
        sa.Column("found_in_title", sa.Boolean(), nullable=False),
        sa.Column("found_in_description", sa.Boolean(), nullable=False),
        sa.Column("is_possible_group", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("category_match", sa.String(150), nullable=True),
        sa.Column("category_is_new_suggestion", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("raw_confidence", sa.Float(), nullable=False),
        sa.Column("adjusted_confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("linked_guest_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staging_guest_candidates")),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"],
            name=op.f("fk_staging_guest_candidates_video_id_videos"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name=op.f("fk_staging_guest_candidates_ingestion_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_guest_id"], ["guests.id"],
            name=op.f("fk_staging_guest_candidates_linked_guest_id_guests"), ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_staging_guest_candidates_status_valid"),
        ),
        sa.CheckConstraint(
            "extraction_method IN ('regex', 'llm')",
            name=op.f("ck_staging_guest_candidates_extraction_method_valid"),
        ),
        sa.CheckConstraint(
            "raw_confidence >= 0 AND raw_confidence <= 1",
            name=op.f("ck_staging_guest_candidates_raw_confidence_range"),
        ),
        sa.CheckConstraint(
            "adjusted_confidence >= 0 AND adjusted_confidence <= 1",
            name=op.f("ck_staging_guest_candidates_adjusted_confidence_range"),
        ),
    )

    op.create_table(
        "staging_contact_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=True),
        sa.Column("guest_candidate_id", sa.Integer(), nullable=True),
        sa.Column("type_hint", sa.String(150), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("raw_confidence", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("linked_contact_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staging_contact_candidates")),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"],
            name=op.f("fk_staging_contact_candidates_video_id_videos"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name=op.f("fk_staging_contact_candidates_ingestion_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guest_candidate_id"], ["staging_guest_candidates.id"],
            name=op.f("fk_staging_contact_candidates_guest_candidate_id_staging_guest_candidates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_contact_id"], ["contacts.id"],
            name=op.f("fk_staging_contact_candidates_linked_contact_id_contacts"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_staging_contact_candidates_status_valid"),
        ),
        sa.CheckConstraint(
            "extraction_method IN ('regex', 'llm')",
            name=op.f("ck_staging_contact_candidates_extraction_method_valid"),
        ),
        sa.CheckConstraint(
            "raw_confidence >= 0 AND raw_confidence <= 1",
            name=op.f("ck_staging_contact_candidates_raw_confidence_range"),
        ),
    )


def downgrade() -> None:
    op.drop_table("staging_contact_candidates")
    op.drop_table("staging_guest_candidates")
    op.drop_table("ingestion_run_errors")
    op.drop_table("ingestion_runs")
    op.drop_constraint(
        op.f("fk_videos_possible_duplicate_of_video_id_videos"), "videos", type_="foreignkey"
    )
    op.drop_column("videos", "possible_duplicate_of_video_id")
