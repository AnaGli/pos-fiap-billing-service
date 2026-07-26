"""add mercado pago order status fields

Revision ID: 20260726_02
Revises: 20260726_01
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_02"
down_revision = "20260726_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("provider_payment_reference", sa.String(length=100), nullable=True))
    op.add_column("payments", sa.Column("provider_status_detail", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "provider_status_detail")
    op.drop_column("payments", "provider_payment_reference")
