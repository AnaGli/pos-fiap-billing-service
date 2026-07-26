"""add pix payment integration fields

Revision ID: 20260726_01
Revises: 20260724_01
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_01"
down_revision = "20260724_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'PENDING'")

    op.add_column("payments", sa.Column("external_reference", sa.String(length=100), nullable=True))
    op.add_column("payments", sa.Column("payment_method_id", sa.String(length=50), nullable=True))
    op.add_column("payments", sa.Column("provider_status", sa.String(length=50), nullable=True))
    op.add_column("payments", sa.Column("qr_code", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("qr_code_base64", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("ticket_url", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("idempotency_key", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "idempotency_key")
    op.drop_column("payments", "ticket_url")
    op.drop_column("payments", "qr_code_base64")
    op.drop_column("payments", "qr_code")
    op.drop_column("payments", "provider_status")
    op.drop_column("payments", "payment_method_id")
    op.drop_column("payments", "external_reference")
