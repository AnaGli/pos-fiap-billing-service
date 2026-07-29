from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.billing import Budget


def get_budget_by_order_id(db: Session, order_id: int) -> Budget | None:
    statement = (
        select(Budget)
        .where(Budget.order_id == order_id)
        .options(
            selectinload(Budget.items),
            selectinload(Budget.payments),
            selectinload(Budget.refunds),
        )
    )
    return db.scalar(statement)


def get_budget_by_id(db: Session, budget_id: int) -> Budget | None:
    statement = (
        select(Budget)
        .where(Budget.id == budget_id)
        .options(
            selectinload(Budget.items),
            selectinload(Budget.payments),
            selectinload(Budget.refunds),
        )
    )
    return db.scalar(statement)
