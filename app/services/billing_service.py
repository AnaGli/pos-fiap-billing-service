from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.catalog_store import CatalogItemDocument, get_catalog_store
from app.core.logging_config import ensure_correlation_id, set_log_context
from app.core.tracing import capture_current_trace_headers
from app.integrations.mercado_pago import MercadoPagoClient, MercadoPagoError
from app.models.billing import Budget, BudgetItem, BudgetStatus, Payment, PaymentStatus, Refund
from app.models.outbox_event import OutboxEvent
from app.models.processed_event import ProcessedEvent
from app.repositories import billing_repository
from app.schemas.billing import (
    ApproveBudgetRequest,
    CatalogItemCreate,
    DiagnosisCompletedEvent,
    PaymentConfirmationResponse,
    PixPaymentRequest,
    PixPaymentResponse,
    RefundRequest,
)


class BillingService:
    def __init__(self, db: Session):
        self.db = db
        self.catalog_store = get_catalog_store()

    def create_catalog_item(self, data: CatalogItemCreate) -> CatalogItemDocument:
        set_log_context(business_operation="billing_create_catalog_item", item_code=data.code)
        existing = self.catalog_store.get_item_by_code(data.code)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Catalog item already exists")
        item = CatalogItemDocument(**data.model_dump(), active=True)
        try:
            return self.catalog_store.create_item(item)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Catalog item already exists") from exc

    def list_catalog(self) -> list[CatalogItemDocument]:
        set_log_context(business_operation="billing_list_catalog")
        return self.catalog_store.list_items()

    def get_budget(self, budget_id: int) -> Budget:
        set_log_context(business_operation="billing_get_budget", budget_id=budget_id)
        budget = billing_repository.get_budget_by_id(self.db, budget_id)
        if budget is None:
            raise HTTPException(status_code=404, detail="Budget not found")
        return budget

    def get_budget_by_order_id(self, order_id: int) -> Budget:
        set_log_context(business_operation="billing_get_budget_by_order", order_id=order_id)
        budget = billing_repository.get_budget_by_order_id(self.db, order_id)
        if budget is None:
            raise HTTPException(status_code=404, detail="Budget not found")
        return budget

    def intake_diagnosis_completed(self, event: DiagnosisCompletedEvent) -> Budget:
        set_log_context(
            correlation_id=event.correlationId or ensure_correlation_id(),
            business_operation="billing_intake_diagnosis_completed",
            order_id=event.orderId,
        )
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
            catalog_item = self.catalog_store.get_item_by_code(service.service_id)
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
            catalog_item = self.catalog_store.get_item_by_code(part.part_id)
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
                    "correlationId": event.correlationId or ensure_correlation_id(),
                    "traceHeaders": capture_current_trace_headers(),
                },
            )
        )
        self.db.add(ProcessedEvent(event_id=event.eventId, event_type=event.eventType, order_id=event.orderId))
        self.db.commit()
        return self.get_budget(budget.id)

    def approve_budget(self, budget_id: int, data: ApproveBudgetRequest) -> Budget:
        set_log_context(
            correlation_id=ensure_correlation_id(),
            business_operation="billing_approve_budget",
            budget_id=budget_id,
        )
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
                    "correlationId": ensure_correlation_id(),
                    "traceHeaders": capture_current_trace_headers(),
                },
            )
        )
        self.db.commit()
        return self.get_budget(budget_id)

    def create_pix_payment(
        self,
        budget_id: int,
        data: PixPaymentRequest,
        mercado_pago: MercadoPagoClient,
    ) -> PixPaymentResponse:
        set_log_context(
            correlation_id=ensure_correlation_id(),
            business_operation="billing_create_pix_payment",
            budget_id=budget_id,
        )
        budget = self.get_budget(budget_id)
        if budget.status == BudgetStatus.PAID:
            raise HTTPException(status_code=409, detail="Budget is already paid")
        if budget.status == BudgetStatus.REFUNDED:
            raise HTTPException(status_code=409, detail="Refunded budget cannot receive a new payment")

        latest_payment = budget.payments[-1] if budget.payments else None
        if latest_payment is not None and latest_payment.status == PaymentStatus.PENDING:
            return self._build_pix_response(budget, latest_payment)

        external_reference = f"budget_{budget.id}_order_{budget.order_id}"
        description = data.description or f"Pagamento Pix do orçamento {budget.id}"

        try:
            order_payload, idempotency_key = mercado_pago.create_pix_order(
                amount=float(budget.total_amount),
                payer_email=data.payer_email,
                payer_first_name=data.payer_first_name,
                description=description,
                external_reference=external_reference,
                expiration_time=data.expiration_time,
            )
        except MercadoPagoError as exc:
            raise HTTPException(status_code=502, detail=f"Mercado Pago error: {exc}") from exc

        payments = order_payload.get("transactions", {}).get("payments", [])
        payment_data = payments[0] if payments else {}
        payment_method_data = payment_data.get("payment_method", {})
        latest_payment = Payment(
            provider="MERCADO_PAGO",
            provider_reference=str(order_payload["id"]),
            provider_payment_reference=str(payment_data["id"]) if payment_data.get("id") is not None else None,
            external_reference=external_reference,
            payment_method_id=payment_method_data.get("id", "pix"),
            provider_status=payment_data.get("status") or order_payload.get("status", "action_required"),
            provider_status_detail=payment_data.get("status_detail") or order_payload.get("status_detail", "waiting_transfer"),
            qr_code=payment_method_data.get("qr_code"),
            qr_code_base64=payment_method_data.get("qr_code_base64"),
            ticket_url=payment_method_data.get("ticket_url"),
            idempotency_key=idempotency_key,
            amount=float(budget.total_amount),
            status=PaymentStatus.PENDING,
        )
        budget.status = BudgetStatus.APPROVED
        budget.payments.append(latest_payment)
        self.db.commit()
        return self._build_pix_response(budget, latest_payment)

    def refund_by_order_id(self, order_id: int, data: RefundRequest) -> Budget:
        set_log_context(
            correlation_id=ensure_correlation_id(),
            business_operation="billing_refund_by_order",
            order_id=order_id,
        )
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
                payload={
                    "orderId": order_id,
                    "reason": data.reason,
                    "correlationId": ensure_correlation_id(),
                    "traceHeaders": capture_current_trace_headers(),
                },
            )
        )
        self.db.commit()
        return self.get_budget(budget.id)

    def confirm_pix_payment(
        self,
        budget_id: int,
        mercado_pago: MercadoPagoClient,
    ) -> PaymentConfirmationResponse:
        set_log_context(
            correlation_id=ensure_correlation_id(),
            business_operation="billing_confirm_pix_payment",
            budget_id=budget_id,
        )
        budget = self.get_budget(budget_id)
        latest_payment = budget.payments[-1] if budget.payments else None
        if latest_payment is None:
            raise HTTPException(status_code=409, detail="Budget does not have a registered payment")

        try:
            order_payload = mercado_pago.get_order(latest_payment.provider_reference)
        except MercadoPagoError as exc:
            raise HTTPException(status_code=502, detail=f"Mercado Pago error: {exc}") from exc

        payments = order_payload.get("transactions", {}).get("payments", [])
        payment_data = payments[0] if payments else {}
        payment_method_data = payment_data.get("payment_method", {})

        latest_payment.provider_status = payment_data.get("status") or order_payload.get("status")
        latest_payment.provider_status_detail = payment_data.get("status_detail") or order_payload.get("status_detail")
        latest_payment.provider_payment_reference = str(payment_data["id"]) if payment_data.get("id") is not None else latest_payment.provider_payment_reference
        latest_payment.payment_method_id = payment_method_data.get("id", latest_payment.payment_method_id)
        latest_payment.qr_code = payment_method_data.get("qr_code", latest_payment.qr_code)
        latest_payment.qr_code_base64 = payment_method_data.get("qr_code_base64", latest_payment.qr_code_base64)
        latest_payment.ticket_url = payment_method_data.get("ticket_url", latest_payment.ticket_url)

        event_published = False
        if latest_payment.provider_status == "processed" and latest_payment.provider_status_detail == "accredited":
            latest_payment.status = PaymentStatus.APPROVED
            if budget.status != BudgetStatus.PAID:
                budget.status = BudgetStatus.PAID
                self.db.add(
                    OutboxEvent(
                        event_type="PaymentApproved",
                        aggregate_id=str(budget.order_id),
                        payload={
                            "orderId": budget.order_id,
                            "budgetId": budget.id,
                            "paymentStatus": "APPROVED",
                            "correlationId": ensure_correlation_id(),
                            "traceHeaders": capture_current_trace_headers(),
                        },
                    )
                )
                event_published = True

        self.db.commit()
        return PaymentConfirmationResponse(
            budget_id=budget.id,
            order_id=budget.order_id,
            mercado_pago_order_id=latest_payment.provider_reference,
            mercado_pago_payment_id=latest_payment.provider_payment_reference,
            budget_status=budget.status,
            payment_status=latest_payment.status,
            provider_status=latest_payment.provider_status,
            provider_status_detail=latest_payment.provider_status_detail,
            event_published=event_published,
        )

    def _build_pix_response(self, budget: Budget, payment: Payment) -> PixPaymentResponse:
        return PixPaymentResponse(
            budget_id=budget.id,
            order_id=budget.order_id,
            mercado_pago_order_id=payment.provider_reference,
            mercado_pago_payment_id=payment.provider_payment_reference,
            status=payment.provider_status or payment.status.value.lower(),
            status_detail=payment.provider_status_detail,
            qr_code=payment.qr_code,
            qr_code_base64=payment.qr_code_base64,
            ticket_url=payment.ticket_url,
            external_reference=payment.external_reference or f"budget_{budget.id}_order_{budget.order_id}",
        )
