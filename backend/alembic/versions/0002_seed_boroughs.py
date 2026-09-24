"""Semilla: las 16 alcaldías de la CDMX (único catálogo precargado).

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CDMX_BOROUGHS = [
    "Álvaro Obregón", "Azcapotzalco", "Benito Juárez", "Coyoacán",
    "Cuajimalpa de Morelos", "Cuauhtémoc", "Gustavo A. Madero", "Iztacalco",
    "Iztapalapa", "La Magdalena Contreras", "Miguel Hidalgo", "Milpa Alta",
    "Tláhuac", "Tlalpan", "Venustiano Carranza", "Xochimilco",
]


def upgrade() -> None:
    boroughs = sa.table("boroughs", sa.column("name", sa.String))
    op.bulk_insert(boroughs, [{"name": n} for n in CDMX_BOROUGHS])


def downgrade() -> None:
    boroughs = sa.table("boroughs", sa.column("name", sa.String))
    op.execute(boroughs.delete().where(boroughs.c.name.in_(CDMX_BOROUGHS)))
