from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.billing import BudgetStatus, CatalogItemType, PaymentStatus


class DiagnosisCompletedService(BaseModel):
    service_id: str = Field(alias="serviceId")
    quantity: int


class DiagnosisCompletedPart(BaseModel):
    part_id: str = Field(alias="partId")
    quantity: int


class DiagnosisCompletedEvent(BaseModel):
    eventId: str
    eventType: str
    orderId: int
    services: list[DiagnosisCompletedService]
    parts: list[DiagnosisCompletedPart] = []
    estimatedHours: int


class CatalogItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    item_type: CatalogItemType
    price: float = Field(gt=0)


class ApproveBudgetRequest(BaseModel):
    provider_reference: str = Field(min_length=1, max_length=100)


class RefundRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class CatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    item_type: CatalogItemType
    price: float
    active: bool


class BudgetItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_code: str
    item_name: str
    item_type: CatalogItemType
    quantity: int
    unit_price: float
    line_total: float


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    provider_reference: str
    amount: float
    status: PaymentStatus
    created_at: datetime


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    total_amount: float
    status: BudgetStatus
    items: list[BudgetItemResponse]
    payments: list[PaymentResponse]
