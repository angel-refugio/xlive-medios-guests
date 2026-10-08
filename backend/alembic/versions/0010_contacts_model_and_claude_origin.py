"""Contactos del invitado (modelo objetivo) y origen Claude en los candidatos de staging.

- Catálogo nuevo `contact_relationships` (propio, mánager, patrocinador; editable desde la app).
- `contacts`: `guest_id` admite NULL (contacto sin asignar), y se agregan `normalized_value`
  (restricción única por invitado + tipo + valor normalizado), `relationship_id`, `video_id`,
  `evidence` y `status` (candidate / validated / rejected). Todo lo que ya existía queda
  `validated`. `verified` se conserva por compatibilidad con la API y la interfaz actuales.
- `staging_contact_candidates`: valor normalizado, relación propuesta, evidencia, dudoso con su
  motivo, invitado asignado por la IA y posible invitado no detectado.
- Origen (`extractor`: claude_code / claude_api) y `instructions_version` en los tres tipos de
  candidato, y `staging_video_suggestions.new_program_name` (programa propuesto fuera del catálogo).

Revision ID: 0010
Revises: 0009
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_SCHEME_WWW_RE = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)
_PHONE_LIKE_RE = re.compile(r"[+\d\s().-]{7,}")


def _normalize(value: str) -> str:
    """Copia de `app.models.contact.normalize_contact_value` (una migración no importa código de la
    app: debe seguir funcionando aunque ese código cambie)."""
    text = " ".join(value.split())
    if _PHONE_LIKE_RE.fullmatch(text):
        digits = re.sub(r"\D", "", text)
        return digits[2:] if len(digits) == 12 and digits.startswith("52") else digits
    return _SCHEME_WWW_RE.sub("", text.lower()).rstrip("/")


def upgrade() -> None:
    relationships = op.create_table(
        "contact_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_relationships")),
        sa.UniqueConstraint("name", name=op.f("uq_contact_relationships_name")),
    )
    op.bulk_insert(relationships, [{"name": "propio"}, {"name": "manager"}, {"name": "patrocinador"}])

    # --- contacts ---
    op.add_column("contacts", sa.Column("normalized_value", sa.String(500), nullable=True))
    op.add_column("contacts", sa.Column("relationship_id", sa.Integer(), nullable=True))
    op.add_column("contacts", sa.Column("video_id", sa.Integer(), nullable=True))
    op.add_column("contacts", sa.Column("evidence", sa.Text(), nullable=True))
    op.add_column(
        "contacts", sa.Column("status", sa.String(20), server_default="validated", nullable=False),
    )

    connection = op.get_bind()
    contacts = sa.table("contacts", sa.column("id", sa.Integer), sa.column("value", sa.String),
                        sa.column("normalized_value", sa.String))
    for row in connection.execute(sa.select(contacts.c.id, contacts.c.value)).all():
        connection.execute(
            contacts.update().where(contacts.c.id == row.id).values(normalized_value=_normalize(row.value))
        )
    op.alter_column("contacts", "normalized_value", nullable=False)
    op.alter_column("contacts", "guest_id", existing_type=sa.Integer(), nullable=True)

    op.create_foreign_key(
        op.f("fk_contacts_relationship_id_contact_relationships"),
        "contacts", "contact_relationships", ["relationship_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_contacts_video_id_videos"), "contacts", "videos", ["video_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_contacts_status_valid"), "contacts", "status IN ('candidate', 'validated', 'rejected')",
    )
    # Si dos contactos existentes quedaran iguales tras normalizar, esta línea falla con un mensaje
    # claro de PostgreSQL: se deduplican a mano desde la app antes de volver a migrar.
    op.create_unique_constraint(
        op.f("uq_contacts_guest_type_value"), "contacts", ["guest_id", "contact_type_id", "normalized_value"],
    )

    # --- staging ---
    for column in (
        sa.Column("normalized_value", sa.String(500), nullable=True),
        sa.Column("relationship_name", sa.String(30), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("doubtful", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("doubtful_reason", sa.String(300), nullable=True),
        sa.Column("guest_name", sa.String(255), nullable=True),
        sa.Column("possible_guest_name", sa.String(255), nullable=True),
    ):
        op.add_column("staging_contact_candidates", column)
    for table in ("staging_contact_candidates", "staging_guest_candidates", "staging_video_suggestions"):
        op.add_column(table, sa.Column("extractor", sa.String(20), nullable=True))
        op.add_column(table, sa.Column("instructions_version", sa.String(20), nullable=True))
    op.add_column("staging_video_suggestions", sa.Column("new_program_name", sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column("staging_video_suggestions", "new_program_name")
    for table in ("staging_video_suggestions", "staging_guest_candidates", "staging_contact_candidates"):
        op.drop_column(table, "instructions_version")
        op.drop_column(table, "extractor")
    for name in ("possible_guest_name", "guest_name", "doubtful_reason", "doubtful", "evidence",
                 "relationship_name", "normalized_value"):
        op.drop_column("staging_contact_candidates", name)

    op.drop_constraint(op.f("uq_contacts_guest_type_value"), "contacts", type_="unique")
    op.drop_constraint(op.f("ck_contacts_status_valid"), "contacts", type_="check")
    op.drop_constraint(op.f("fk_contacts_video_id_videos"), "contacts", type_="foreignkey")
    op.drop_constraint(op.f("fk_contacts_relationship_id_contact_relationships"), "contacts", type_="foreignkey")
    # Falla (a propósito) si quedan contactos sin asignar: asígnalos o bórralos desde la app antes.
    op.alter_column("contacts", "guest_id", existing_type=sa.Integer(), nullable=False)
    for name in ("status", "evidence", "video_id", "relationship_id", "normalized_value"):
        op.drop_column("contacts", name)
    op.drop_table("contact_relationships")
