from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.billing import Budget, CatalogItem


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


def get_catalog_item_by_code(db: Session, code: str) -> CatalogItem | None:
    return db.scalar(select(CatalogItem).where(CatalogItem.code == code))


def list_catalog(db: Session) -> list[CatalogItem]:
    return list(db.scalars(select(CatalogItem).order_by(CatalogItem.code)))
