"""create initial billing service schema

Revision ID: 20260724_01
Revises:
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260724_01"
down_revision = None
branch_labels = None
depends_on = None

catalog_item_type_enum = postgresql.ENUM("SERVICE", "PART", name="catalogitemtype", create_type=False)
budget_status_enum = postgresql.ENUM("WAITING_APPROVAL", "APPROVED", "PAID", "REFUNDED", name="budgetstatus", create_type=False)
payment_status_enum = postgresql.ENUM("APPROVED", "REFUNDED", name="paymentstatus", create_type=False)


def upgrade() -> None:
    catalog_item_type_enum.create(op.get_bind(), checkfirst=True)
    budget_status_enum.create(op.get_bind(), checkfirst=True)
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=100), unique=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("item_type", catalog_item_type_enum, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", budget_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "budget_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id"), nullable=False),
        sa.Column("item_code", sa.String(length=100), nullable=False),
        sa.Column("item_name", sa.String(length=100), nullable=False),
        sa.Column("item_type", catalog_item_type_enum, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_reference", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", payment_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(length=100), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("outbox_events")
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_table("budget_items")
    op.drop_table("budgets")
    op.drop_table("catalog_items")
    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    budget_status_enum.drop(op.get_bind(), checkfirst=True)
    catalog_item_type_enum.drop(op.get_bind(), checkfirst=True)
