import os

os.environ["DATABASE_URL"] = "sqlite:///./test_billing_service.db"

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.outbox_event import OutboxEvent

client = TestClient(app)

DIAGNOSIS_EVENT = {
    "eventId": "diag-1",
    "eventType": "DiagnosisCompleted",
    "orderId": 101,
    "services": [{"serviceId": "oil-change", "quantity": 1}],
    "parts": [{"partId": "oil-filter", "quantity": 1}],
    "estimatedHours": 2,
}


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    client.post(
        "/catalog/items",
        json={"code": "oil-change", "name": "Troca de óleo", "item_type": "SERVICE", "price": 120.0},
    )
    client.post(
        "/catalog/items",
        json={"code": "oil-filter", "name": "Filtro de óleo", "item_type": "PART", "price": 35.0},
    )


def test_diagnosis_completed_generates_budget():
    response = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT)

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == 101
    assert body["status"] == "WAITING_APPROVAL"
    assert body["total_amount"] == 155.0

    with SessionLocal() as db:
        event = db.query(OutboxEvent).one()
        assert event.event_type == "BudgetCreated"


def test_approve_budget_registers_payment_and_event():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    response = client.post(
        f"/budgets/{budget['id']}/approve",
        json={"provider_reference": "mp-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PAID"
    assert body["payments"][0]["provider_reference"] == "mp-123"


def test_refund_creates_refund_processed_event():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()
    client.post(f"/budgets/{budget['id']}/approve", json={"provider_reference": "mp-123"})

    response = client.post("/orders/101/refund", json={"reason": "Falha na execução"})

    assert response.status_code == 200
    assert response.json()["status"] == "REFUNDED"
