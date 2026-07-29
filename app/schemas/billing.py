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
    correlationId: str | None = None
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


class PixPaymentRequest(BaseModel):
    payer_email: str = Field(min_length=3, max_length=255)
    payer_first_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=255)
    expiration_time: str | None = Field(default=None, min_length=2, max_length=50)


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
    provider_payment_reference: str | None = None
    external_reference: str | None = None
    payment_method_id: str | None = None
    provider_status: str | None = None
    provider_status_detail: str | None = None
    qr_code: str | None = None
    qr_code_base64: str | None = None
    ticket_url: str | None = None
    amount: float
    status: PaymentStatus
    created_at: datetime


class PixPaymentResponse(BaseModel):
    budget_id: int
    order_id: int
    mercado_pago_order_id: str
    mercado_pago_payment_id: str | None = None
    status: str
    status_detail: str | None = None
    qr_code: str | None = None
    qr_code_base64: str | None = None
    ticket_url: str | None = None
    external_reference: str


class PaymentConfirmationResponse(BaseModel):
    budget_id: int
    order_id: int
    mercado_pago_order_id: str
    mercado_pago_payment_id: str | None = None
    budget_status: BudgetStatus
    payment_status: PaymentStatus
    provider_status: str | None = None
    provider_status_detail: str | None = None
    event_published: bool


class MercadoPagoConnectionCheckResponse(BaseModel):
    environment: str
    total_methods: int
    pix_available: bool
    methods: list[str]


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    total_amount: float
    status: BudgetStatus
    items: list[BudgetItemResponse]
    payments: list[PaymentResponse]
