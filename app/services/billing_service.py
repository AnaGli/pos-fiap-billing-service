from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.billing import Budget, BudgetItem, BudgetStatus, CatalogItem, Payment, PaymentStatus, Refund
from app.models.outbox_event import OutboxEvent
from app.models.processed_event import ProcessedEvent
from app.repositories import billing_repository
from app.schemas.billing import ApproveBudgetRequest, CatalogItemCreate, DiagnosisCompletedEvent, RefundRequest


class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def create_catalog_item(self, data: CatalogItemCreate) -> CatalogItem:
        existing = billing_repository.get_catalog_item_by_code(self.db, data.code)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Catalog item already exists")
        item = CatalogItem(**data.model_dump())
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def list_catalog(self) -> list[CatalogItem]:
        return billing_repository.list_catalog(self.db)

    def get_budget(self, budget_id: int) -> Budget:
        budget = billing_repository.get_budget_by_id(self.db, budget_id)
        if budget is None:
            raise HTTPException(status_code=404, detail="Budget not found")
        return budget

    def get_budget_by_order_id(self, order_id: int) -> Budget:
        budget = billing_repository.get_budget_by_order_id(self.db, order_id)
        if budget is None:
            raise HTTPException(status_code=404, detail="Budget not found")
        return budget

    def intake_diagnosis_completed(self, event: DiagnosisCompletedEvent) -> Budget:
        if self.db.get(ProcessedEvent, event.eventId) is not None:
            return self.get_budget_by_order_id(event.orderId)

        existing_budget = billing_repository.get_budget_by_order_id(self.db, event.orderId)
        if existing_budget is not None:
            self.db.add(ProcessedEvent(event_id=event.eventId, event_type=event.eventType, order_id=event.orderId))
            self.db.commit()
            return self.get_budget_by_order_id(event.orderId)

        items = []
        total = 0.0

        for service in event.services:
            catalog_item = billing_repository.get_catalog_item_by_code(self.db, service.service_id)
            if catalog_item is None or not catalog_item.active:
                raise HTTPException(status_code=422, detail=f"Catalog item not found: {service.service_id}")
            line_total = float(catalog_item.price) * service.quantity
            items.append(
                BudgetItem(
                    item_code=catalog_item.code,
                    item_name=catalog_item.name,
                    item_type=catalog_item.item_type,
                    quantity=service.quantity,
                    unit_price=float(catalog_item.price),
                    line_total=line_total,
                )
            )
            total += line_total

        for part in event.parts:
            catalog_item = billing_repository.get_catalog_item_by_code(self.db, part.part_id)
            if catalog_item is None or not catalog_item.active:
                raise HTTPException(status_code=422, detail=f"Catalog item not found: {part.part_id}")
            line_total = float(catalog_item.price) * part.quantity
            items.append(
                BudgetItem(
                    item_code=catalog_item.code,
                    item_name=catalog_item.name,
                    item_type=catalog_item.item_type,
                    quantity=part.quantity,
                    unit_price=float(catalog_item.price),
                    line_total=line_total,
                )
            )
            total += line_total

        budget = Budget(order_id=event.orderId, total_amount=total, status=BudgetStatus.WAITING_APPROVAL)
        budget.items.extend(items)
        self.db.add(budget)
        self.db.flush()
        self.db.add(
            OutboxEvent(
                event_type="BudgetCreated",
                aggregate_id=str(event.orderId),
                payload={
                    "orderId": event.orderId,
                    "budgetId": budget.id,
                    "totalAmount": total,
                },
            )
        )
        self.db.add(ProcessedEvent(event_id=event.eventId, event_type=event.eventType, order_id=event.orderId))
        self.db.commit()
        return self.get_budget(budget.id)

    def approve_budget(self, budget_id: int, data: ApproveBudgetRequest) -> Budget:
        budget = self.get_budget(budget_id)
        if budget.status != BudgetStatus.WAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="Budget cannot be approved from current status")

        budget.status = BudgetStatus.PAID
        budget.payments.append(
            Payment(
                provider="MERCADO_PAGO",
                provider_reference=data.provider_reference,
                amount=float(budget.total_amount),
                status=PaymentStatus.APPROVED,
            )
        )
        self.db.add(
            OutboxEvent(
                event_type="PaymentApproved",
                aggregate_id=str(budget.order_id),
                payload={
                    "orderId": budget.order_id,
                    "budgetId": budget.id,
                    "paymentStatus": "APPROVED",
                },
            )
        )
        self.db.commit()
        return self.get_budget(budget_id)

    def refund_by_order_id(self, order_id: int, data: RefundRequest) -> Budget:
        budget = self.get_budget_by_order_id(order_id)
        if budget.status != BudgetStatus.PAID:
            raise HTTPException(status_code=409, detail="Refund can only be processed for paid budgets")

        budget.status = BudgetStatus.REFUNDED
        budget.refunds.append(Refund(amount=float(budget.total_amount), reason=data.reason))
        if budget.payments:
            budget.payments[-1].status = PaymentStatus.REFUNDED
        self.db.add(
            OutboxEvent(
                event_type="RefundProcessed",
                aggregate_id=str(order_id),
                payload={"orderId": order_id, "reason": data.reason},
            )
        )
        self.db.commit()
        return self.get_budget(budget.id)
