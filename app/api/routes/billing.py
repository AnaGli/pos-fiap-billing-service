from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.schemas.billing import (
    ApproveBudgetRequest,
    BudgetResponse,
    CatalogItemCreate,
    CatalogItemResponse,
    DiagnosisCompletedEvent,
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


@router.post("/catalog/items", response_model=CatalogItemResponse, status_code=status.HTTP_201_CREATED)
def create_catalog_item(data: CatalogItemCreate, service: BillingService = Depends(get_service)):
    return service.create_catalog_item(data)


@router.get("/catalog/items", response_model=list[CatalogItemResponse])
def list_catalog(service: BillingService = Depends(get_service)):
    return service.list_catalog()


@router.post("/internal/events/diagnosis-completed", response_model=BudgetResponse)
def intake_diagnosis_completed(event: DiagnosisCompletedEvent, service: BillingService = Depends(get_service)):
    return service.intake_diagnosis_completed(event)


@router.get("/budgets/{budget_id}", response_model=BudgetResponse)
def get_budget(budget_id: int, service: BillingService = Depends(get_service)):
    return service.get_budget(budget_id)


@router.post("/budgets/{budget_id}/approve", response_model=BudgetResponse)
def approve_budget(budget_id: int, data: ApproveBudgetRequest, service: BillingService = Depends(get_service)):
    return service.approve_budget(budget_id, data)


@router.post("/orders/{order_id}/refund", response_model=BudgetResponse)
def refund_order(order_id: int, data: RefundRequest, service: BillingService = Depends(get_service)):
    return service.refund_by_order_id(order_id, data)
