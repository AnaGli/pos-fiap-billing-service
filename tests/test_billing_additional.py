import os

os.environ["DATABASE_URL"] = "sqlite:///./test_billing_service.db"
os.environ["CATALOG_BACKEND"] = "memory"

import pytest
from fastapi.testclient import TestClient

from app.catalog_store import reset_catalog_store
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.billing import Budget, BudgetStatus, Payment, PaymentStatus
from app.models.outbox_event import OutboxEvent
from app.services.billing_service import BillingService

client = TestClient(app)

DIAGNOSIS_EVENT = {
    "eventId": "diag-extra-1",
    "eventType": "DiagnosisCompleted",
    "orderId": 202,
    "services": [{"serviceId": "oil-change", "quantity": 1}],
    "parts": [{"partId": "oil-filter", "quantity": 1}],
    "estimatedHours": 2,
}


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_catalog_store()
    client.post(
        "/catalog/items",
        json={"code": "oil-change", "name": "Troca de óleo", "item_type": "SERVICE", "price": 120.0},
    )
    client.post(
        "/catalog/items",
        json={"code": "oil-filter", "name": "Filtro de óleo", "item_type": "PART", "price": 35.0},
    )


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_create_catalog_item_duplicate_returns_409():
    response = client.post(
        "/catalog/items",
        json={"code": "oil-change", "name": "Troca de óleo", "item_type": "SERVICE", "price": 120.0},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Catalog item already exists"


def test_get_budget_not_found_returns_404():
    response = client.get("/budgets/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Budget not found"


def test_list_catalog_returns_seeded_items():
    response = client.get("/catalog/items")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["code"] for item in body} == {"oil-change", "oil-filter"}


def test_diagnosis_completed_is_idempotent_for_same_event():
    first = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT)
    second = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    with SessionLocal() as db:
        assert db.query(Budget).count() == 1


def test_diagnosis_completed_with_missing_catalog_item_returns_422():
    response = client.post(
        "/internal/events/diagnosis-completed",
        json={
            **DIAGNOSIS_EVENT,
            "eventId": "diag-extra-2",
            "services": [{"serviceId": "unknown-service", "quantity": 1}],
            "parts": [],
        },
    )
    assert response.status_code == 422
    assert "Catalog item not found" in response.json()["detail"]


def test_approve_budget_twice_returns_409_on_second_attempt():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    first = client.post(f"/budgets/{budget['id']}/approve", json={"provider_reference": "mp-123"})
    second = client.post(f"/budgets/{budget['id']}/approve", json={"provider_reference": "mp-456"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Budget cannot be approved from current status"


def test_confirm_payment_without_registered_payment_returns_409():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    response = client.post(f"/budgets/{budget['id']}/confirm-payment")

    assert response.status_code == 409
    assert response.json()["detail"] == "Budget does not have a registered payment"


def test_refund_requires_paid_budget():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    response = client.post(f"/orders/{budget['order_id']}/refund", json={"reason": "Falha"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Refund can only be processed for paid budgets"


def test_confirm_payment_pending_status_does_not_publish_event():
    with SessionLocal() as db:
        budget = Budget(order_id=303, total_amount=100.0, status=BudgetStatus.APPROVED)
        budget.payments.append(
            Payment(
                provider="MERCADO_PAGO",
                provider_reference="ORD-PENDING",
                provider_payment_reference="PAY-PENDING",
                amount=100.0,
                status=PaymentStatus.PENDING,
                provider_status="action_required",
                provider_status_detail="waiting_transfer",
            )
        )
        db.add(budget)
        db.commit()
        budget_id = budget.id

        class FakeMercadoPagoClient:
            def get_order(self, order_id: str):
                return {
                    "id": order_id,
                    "status": "action_required",
                    "status_detail": "waiting_transfer",
                    "transactions": {
                        "payments": [
                            {
                                "id": "PAY-PENDING",
                                "status": "action_required",
                                "status_detail": "waiting_transfer",
                                "payment_method": {"id": "pix", "type": "bank_transfer"},
                            }
                        ]
                    },
                }

        response = BillingService(db).confirm_pix_payment(budget_id, FakeMercadoPagoClient())

        assert response.budget_status == BudgetStatus.APPROVED
        assert response.payment_status == PaymentStatus.PENDING
        assert response.event_published is False
        assert db.query(OutboxEvent).count() == 0
