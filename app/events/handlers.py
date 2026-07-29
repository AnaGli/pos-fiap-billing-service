from sqlalchemy.orm import Session

from app.schemas.billing import DiagnosisCompletedEvent, RefundRequest
from app.services.billing_service import BillingService


def handle_event(db: Session, event: dict):
    event_type = event["eventType"]
    service = BillingService(db)

    if event_type == "DiagnosisCompleted":
        return service.intake_diagnosis_completed(DiagnosisCompletedEvent.model_validate(event))
    if event_type == "ExecutionFailed":
        return service.refund_by_order_id(
            event["orderId"],
            RefundRequest(reason=event.get("reason", "Execution failed")),
        )

    raise ValueError(f"Unsupported Billing event: {event_type}")
