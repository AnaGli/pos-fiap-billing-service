import os

os.environ["DATABASE_URL"] = "sqlite:///./test_billing_service.db"
os.environ["CATALOG_BACKEND"] = "memory"

from fastapi.testclient import TestClient

from app.catalog_store import reset_catalog_store
from app.api.routes.billing import get_mercado_pago_client
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
    reset_catalog_store()
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


def test_create_pix_payment_returns_qr_code():
    class FakeMercadoPagoClient:
        def create_pix_order(self, *, amount, payer_email, payer_first_name=None, external_reference, description=None, processing_mode="automatic", expiration_time=None, idempotency_key=None):
            return (
                {
                    "id": "ORD-123",
                    "status": "action_required",
                    "status_detail": "waiting_transfer",
                    "transactions": {
                        "payments": [
                            {
                                "id": "PAY-987654321",
                                "status": "action_required",
                                "status_detail": "waiting_transfer",
                                "payment_method": {
                                    "id": "pix",
                                    "type": "bank_transfer",
                                    "qr_code": "000201PIXCODE",
                                    "qr_code_base64": "base64-image",
                                    "ticket_url": "https://mercadopago.test/ticket/987654321",
                                },
                            }
                        ]
                    },
                },
                "idem-key-1",
            )

    app.dependency_overrides[get_mercado_pago_client] = lambda: FakeMercadoPagoClient()
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    response = client.post(
        f"/budgets/{budget['id']}/pay/pix",
        json={"payer_email": "ana@email.com"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["mercado_pago_order_id"] == "ORD-123"
    assert body["mercado_pago_payment_id"] == "PAY-987654321"
    assert body["status"] == "action_required"
    assert body["status_detail"] == "waiting_transfer"
    assert body["qr_code"] == "000201PIXCODE"


def test_create_pix_payment_accepts_test_first_name():
    captured = {}

    class FakeMercadoPagoClient:
        def create_pix_order(self, *, amount, payer_email, payer_first_name=None, external_reference, description=None, processing_mode="automatic", expiration_time=None, idempotency_key=None):
            captured["payer_email"] = payer_email
            captured["payer_first_name"] = payer_first_name
            return (
                {
                    "id": "ORD-TEST",
                    "status": "action_required",
                    "status_detail": "waiting_transfer",
                    "transactions": {
                        "payments": [
                            {
                                "id": "PAY-TEST",
                                "status": "action_required",
                                "status_detail": "waiting_transfer",
                                "payment_method": {
                                    "id": "pix",
                                    "type": "bank_transfer",
                                    "qr_code": "TESTPIX",
                                    "qr_code_base64": "TESTBASE64",
                                    "ticket_url": "https://mercadopago.test/ticket/test",
                                },
                            }
                        ]
                    },
                },
                "idem-key-test",
            )

    app.dependency_overrides[get_mercado_pago_client] = lambda: FakeMercadoPagoClient()
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()

    response = client.post(
        f"/budgets/{budget['id']}/pay/pix",
        json={
            "payer_email": "test_user_br@testuser.com",
            "payer_first_name": "APRO",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["payer_email"] == "test_user_br@testuser.com"
    assert captured["payer_first_name"] == "APRO"


def test_check_mercado_pago_connection_lists_payment_methods():
    class FakeMercadoPagoClient:
        def list_payment_methods(self):
            return [
                {"id": "pix"},
                {"id": "visa"},
                {"id": "master"},
            ]

    app.dependency_overrides[get_mercado_pago_client] = lambda: FakeMercadoPagoClient()

    response = client.get("/integrations/mercado-pago/payment-methods")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_methods"] == 3
    assert body["pix_available"] is True
    assert "pix" in body["methods"]


def test_confirm_pix_payment_marks_budget_paid_and_publishes_event():
    class FakeMercadoPagoClient:
        def create_pix_order(self, *, amount, payer_email, payer_first_name=None, external_reference, description=None, processing_mode="automatic", expiration_time=None, idempotency_key=None):
            return (
                {
                    "id": "ORD-TO-CONFIRM",
                    "status": "action_required",
                    "status_detail": "waiting_transfer",
                    "transactions": {
                        "payments": [
                            {
                                "id": "PAY-TO-CONFIRM",
                                "status": "action_required",
                                "status_detail": "waiting_transfer",
                                "payment_method": {
                                    "id": "pix",
                                    "type": "bank_transfer",
                                    "qr_code": "PIX-CODE",
                                    "qr_code_base64": "PIX-BASE64",
                                    "ticket_url": "https://mercadopago.test/ticket/confirm",
                                },
                            }
                        ]
                    },
                },
                "idem-confirm",
            )

        def get_order(self, order_id: str):
            return {
                "id": order_id,
                "status": "processed",
                "status_detail": "accredited",
                "transactions": {
                    "payments": [
                        {
                            "id": "PAY-TO-CONFIRM",
                            "status": "processed",
                            "status_detail": "accredited",
                            "payment_method": {
                                "id": "pix",
                                "type": "bank_transfer",
                            },
                        }
                    ]
                },
            }

    app.dependency_overrides[get_mercado_pago_client] = lambda: FakeMercadoPagoClient()
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()
    client.post(
        f"/budgets/{budget['id']}/pay/pix",
        json={"payer_email": "test_user_br@testuser.com", "payer_first_name": "APRO"},
    )

    response = client.post(f"/budgets/{budget['id']}/confirm-payment")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["budget_status"] == "PAID"
    assert body["payment_status"] == "APPROVED"
    assert body["provider_status"] == "processed"
    assert body["provider_status_detail"] == "accredited"
    assert body["event_published"] is True

    with SessionLocal() as db:
        events = db.query(OutboxEvent).order_by(OutboxEvent.created_at).all()
        assert events[-1].event_type == "PaymentApproved"


def test_refund_creates_refund_processed_event():
    budget = client.post("/internal/events/diagnosis-completed", json=DIAGNOSIS_EVENT).json()
    client.post(f"/budgets/{budget['id']}/approve", json={"provider_reference": "mp-123"})

    response = client.post("/orders/101/refund", json={"reason": "Falha na execução"})

    assert response.status_code == 200
    assert response.json()["status"] == "REFUNDED"
