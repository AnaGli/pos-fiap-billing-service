import os
from uuid import uuid4

import httpx


class MercadoPagoError(Exception):
    pass


class MercadoPagoClient:
    def __init__(self, access_token: str | None = None, base_url: str | None = None):
        self.access_token = access_token or os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
        self.base_url = (base_url or os.getenv("MERCADO_PAGO_BASE_URL") or "https://api.mercadopago.com").rstrip("/")

    def create_pix_order(
        self,
        *,
        amount: float,
        payer_email: str,
        payer_first_name: str | None = None,
        external_reference: str,
        description: str | None = None,
        processing_mode: str = "automatic",
        expiration_time: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict, str]:
        if not self.access_token:
            raise MercadoPagoError("MERCADO_PAGO_ACCESS_TOKEN is not configured")

        request_idempotency_key = idempotency_key or str(uuid4())
        payload = {
            "type": "online",
            "total_amount": f"{amount:.2f}",
            "external_reference": external_reference,
            "processing_mode": processing_mode,
            "transactions": {
                "payments": [
                    {
                        "amount": f"{amount:.2f}",
                        "payment_method": {
                            "id": "pix",
                            "type": "bank_transfer",
                        },
                    }
                ]
            },
            "payer": {"email": payer_email},
        }
        if payer_first_name:
            payload["payer"]["first_name"] = payer_first_name
        if description:
            payload["description"] = description
        if expiration_time:
            payload["transactions"]["payments"][0]["expiration_time"] = expiration_time

        response = httpx.post(
            f"{self.base_url}/v1/orders",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "X-Idempotency-Key": request_idempotency_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise MercadoPagoError(response.text)
        return response.json(), request_idempotency_key

    def list_payment_methods(self) -> list[dict]:
        if not self.access_token:
            raise MercadoPagoError("MERCADO_PAGO_ACCESS_TOKEN is not configured")

        response = httpx.get(
            f"{self.base_url}/v1/payment_methods",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise MercadoPagoError(response.text)
        return response.json()

    def get_order(self, order_id: str) -> dict:
        if not self.access_token:
            raise MercadoPagoError("MERCADO_PAGO_ACCESS_TOKEN is not configured")

        response = httpx.get(
            f"{self.base_url}/v1/orders/{order_id}",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise MercadoPagoError(response.text)
        return response.json()
