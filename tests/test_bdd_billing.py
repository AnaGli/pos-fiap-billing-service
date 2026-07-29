import os

os.environ["DATABASE_URL"] = "sqlite:///./test_billing_service.db"
os.environ["CATALOG_BACKEND"] = "memory"

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

from app.catalog_store import reset_catalog_store
from app.api.routes.billing import get_mercado_pago_client
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.billing import Budget, BudgetStatus
from app.models.outbox_event import OutboxEvent

scenarios("features/billing_pix_flow.feature")

client = TestClient(app)


@pytest.fixture
def context() -> dict[str, Any]:
    return {}


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides.clear()
    reset_catalog_store()


@given("o catálogo do billing possui serviço e peça base")
def seed_catalog():
    client.post(
        "/catalog/items",
        json={"code": "oil-change", "name": "Troca de óleo", "item_type": "SERVICE", "price": 120.0},
    )
    client.post(
        "/catalog/items",
        json={"code": "oil-filter", "name": "Filtro de óleo", "item_type": "PART", "price": 35.0},
    )


@given("existe um diagnóstico concluído para a ordem 501")
def diagnosis_event(context: dict[str, Any]):
    context["diagnosis_event"] = {
        "eventId": "bdd-diag-501",
        "eventType": "DiagnosisCompleted",
        "orderId": 501,
        "services": [{"serviceId": "oil-change", "quantity": 1}],
        "parts": [{"partId": "oil-filter", "quantity": 1}],
        "estimatedHours": 2,
    }


@when("o billing recebe o diagnóstico concluído")
def receive_diagnosis(context: dict[str, Any]):
    response = client.post("/internal/events/diagnosis-completed", json=context["diagnosis_event"])
    assert response.status_code == 200
    context["budget_response"] = response.json()
    context["budget_id"] = response.json()["id"]


@then("o orçamento da ordem 501 é criado aguardando aprovação")
def assert_budget_waiting_approval(context: dict[str, Any]):
    budget = context["budget_response"]
    assert budget["order_id"] == 501
    assert budget["status"] == "WAITING_APPROVAL"
    assert budget["total_amount"] == 155.0


@when("o cliente inicia o pagamento Pix do orçamento")
def initiate_pix_payment(context: dict[str, Any]):
    class FakeMercadoPagoClient:
        def create_pix_order(
            self,
            *,
            amount,
            payer_email,
            payer_first_name=None,
            external_reference,
            description=None,
            processing_mode="automatic",
            expiration_time=None,
            idempotency_key=None,
        ):
            return (
                {
                    "id": "ORD-BDD-501",
                    "status": "action_required",
                    "status_detail": "waiting_transfer",
                    "transactions": {
                        "payments": [
                            {
                                "id": "PAY-BDD-501",
                                "status": "action_required",
                                "status_detail": "waiting_transfer",
                                "payment_method": {
                                    "id": "pix",
                                    "type": "bank_transfer",
                                    "qr_code": "000201PIXCODE",
                                    "qr_code_base64": "base64-image",
                                    "ticket_url": "https://mercadopago.test/ticket/501",
                                },
                            }
                        ]
                    },
                },
                "bdd-idem-501",
            )

        def get_order(self, order_id: str):
            return {
                "id": order_id,
                "status": "processed",
                "status_detail": "accredited",
                "transactions": {
                    "payments": [
                        {
                            "id": "PAY-BDD-501",
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
    response = client.post(
        f"/budgets/{context['budget_id']}/pay/pix",
        json={"payer_email": "test_user_br@testuser.com", "payer_first_name": "APRO", "expiration_time": "P1D"},
    )
    assert response.status_code == 200
    context["pix_response"] = response.json()


@then("o billing retorna os dados da cobrança Pix")
def assert_pix_response(context: dict[str, Any]):
    pix_response = context["pix_response"]
    assert pix_response["mercado_pago_order_id"] == "ORD-BDD-501"
    assert pix_response["mercado_pago_payment_id"] == "PAY-BDD-501"
    assert pix_response["status"] == "action_required"
    assert pix_response["qr_code"] == "000201PIXCODE"


@when("o billing confirma o pagamento no Mercado Pago")
def confirm_payment(context: dict[str, Any]):
    response = client.post(f"/budgets/{context['budget_id']}/confirm-payment")
    assert response.status_code == 200
    context["confirm_response"] = response.json()


@then("o orçamento fica com status PAID")
def assert_budget_paid(context: dict[str, Any]):
    with SessionLocal() as db:
        budget = db.get(Budget, context["budget_id"])
        assert budget is not None
        assert budget.status == BudgetStatus.PAID


@then("o evento PaymentApproved é publicado na outbox")
def assert_payment_approved_event(context: dict[str, Any]):
    with SessionLocal() as db:
        events = db.query(OutboxEvent).order_by(OutboxEvent.created_at).all()
        assert any(event.event_type == "PaymentApproved" for event in events)


@when("o billing recebe uma falha de execução da ordem 501")
def receive_execution_failure():
    with SessionLocal() as db:
        updated = __import__("app.events.handlers", fromlist=["handle_event"]).handle_event(
            db,
            {"eventType": "ExecutionFailed", "orderId": 501, "reason": "Falha de execução"},
        )
        assert updated.status == BudgetStatus.REFUNDED


@then("o orçamento fica com status REFUNDED")
def assert_budget_refunded(context: dict[str, Any]):
    with SessionLocal() as db:
        budget = db.get(Budget, context["budget_id"])
        assert budget is not None
        assert budget.status == BudgetStatus.REFUNDED


@then("o evento RefundProcessed é publicado na outbox")
def assert_refund_processed_event():
    with SessionLocal() as db:
        events = db.query(OutboxEvent).order_by(OutboxEvent.created_at).all()
        assert any(event.event_type == "RefundProcessed" for event in events)
