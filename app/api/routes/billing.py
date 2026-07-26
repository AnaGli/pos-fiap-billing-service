from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.integrations.mercado_pago import MercadoPagoClient
from app.schemas.billing import (
    ApproveBudgetRequest,
    BudgetResponse,
    CatalogItemCreate,
    CatalogItemResponse,
    DiagnosisCompletedEvent,
    MercadoPagoConnectionCheckResponse,
    PaymentConfirmationResponse,
    PixPaymentRequest,
    PixPaymentResponse,
    RefundRequest,
)
from app.services.billing_service import BillingService

router = APIRouter(tags=["Billing"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_service(db: Session = Depends(get_db)) -> BillingService:
    return BillingService(db)


def get_mercado_pago_client() -> MercadoPagoClient:
    return MercadoPagoClient()


@router.post("/catalog/items", response_model=CatalogItemResponse, status_code=status.HTTP_201_CREATED)
def create_catalog_item(data: CatalogItemCreate, service: BillingService = Depends(get_service)):
    return service.create_catalog_item(data)


@router.get("/catalog/items", response_model=list[CatalogItemResponse])
def list_catalog(service: BillingService = Depends(get_service)):
    return service.list_catalog()


@router.get("/integrations/mercado-pago/payment-methods", response_model=MercadoPagoConnectionCheckResponse)
def check_mercado_pago_connection(
    mercado_pago: MercadoPagoClient = Depends(get_mercado_pago_client),
):
    methods = mercado_pago.list_payment_methods()
    method_ids = [method["id"] for method in methods]
    return MercadoPagoConnectionCheckResponse(
        environment="mercado-pago",
        total_methods=len(method_ids),
        pix_available="pix" in method_ids,
        methods=method_ids,
    )


@router.post("/internal/events/diagnosis-completed", response_model=BudgetResponse)
def intake_diagnosis_completed(event: DiagnosisCompletedEvent, service: BillingService = Depends(get_service)):
    return service.intake_diagnosis_completed(event)


@router.get("/budgets/{budget_id}", response_model=BudgetResponse)
def get_budget(budget_id: int, service: BillingService = Depends(get_service)):
    return service.get_budget(budget_id)


@router.post("/budgets/{budget_id}/approve", response_model=BudgetResponse)
def approve_budget(budget_id: int, data: ApproveBudgetRequest, service: BillingService = Depends(get_service)):
    return service.approve_budget(budget_id, data)


@router.post("/budgets/{budget_id}/pay/pix", response_model=PixPaymentResponse)
def pay_budget_with_pix(
    budget_id: int,
    data: PixPaymentRequest,
    service: BillingService = Depends(get_service),
    mercado_pago: MercadoPagoClient = Depends(get_mercado_pago_client),
):
    return service.create_pix_payment(budget_id, data, mercado_pago)


@router.post("/budgets/{budget_id}/confirm-payment", response_model=PaymentConfirmationResponse)
def confirm_budget_payment(
    budget_id: int,
    service: BillingService = Depends(get_service),
    mercado_pago: MercadoPagoClient = Depends(get_mercado_pago_client),
):
    return service.confirm_pix_payment(budget_id, mercado_pago)


@router.post("/orders/{order_id}/refund", response_model=BudgetResponse)
def refund_order(order_id: int, data: RefundRequest, service: BillingService = Depends(get_service)):
    return service.refund_by_order_id(order_id, data)
