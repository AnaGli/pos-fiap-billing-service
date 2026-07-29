import pytest

from app.integrations.mercado_pago import MercadoPagoClient, MercadoPagoError


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_create_pix_order_requires_access_token(monkeypatch):
    monkeypatch.delenv("MERCADO_PAGO_ACCESS_TOKEN", raising=False)
    client = MercadoPagoClient(access_token=None, base_url="https://api.test")

    with pytest.raises(MercadoPagoError, match="MERCADO_PAGO_ACCESS_TOKEN is not configured"):
        client.create_pix_order(
            amount=150.0,
            payer_email="ana@email.com",
            external_reference="budget_1_order_2",
        )


def test_create_pix_order_sends_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(
            201,
            payload={
                "id": "ORD-123",
                "transactions": {"payments": [{"id": "PAY-123"}]},
            },
        )

    monkeypatch.setattr("app.integrations.mercado_pago.httpx.post", fake_post)

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")
    response, idempotency_key = client.create_pix_order(
        amount=350.0,
        payer_email="ana@email.com",
        payer_first_name="Ana",
        external_reference="budget_1_order_2",
        description="Pagamento Pix do orçamento 1",
        expiration_time="P1D",
        idempotency_key="idem-123",
    )

    assert response["id"] == "ORD-123"
    assert idempotency_key == "idem-123"
    assert captured["url"] == "https://api.test/v1/orders"
    assert captured["timeout"] == 30.0
    assert captured["headers"]["Authorization"] == "Bearer token-123"
    assert captured["headers"]["X-Idempotency-Key"] == "idem-123"
    assert captured["json"]["type"] == "online"
    assert captured["json"]["total_amount"] == "350.00"
    assert captured["json"]["external_reference"] == "budget_1_order_2"
    assert captured["json"]["description"] == "Pagamento Pix do orçamento 1"
    assert captured["json"]["payer"] == {"email": "ana@email.com", "first_name": "Ana"}
    assert captured["json"]["transactions"]["payments"][0]["amount"] == "350.00"
    assert captured["json"]["transactions"]["payments"][0]["payment_method"] == {
        "id": "pix",
        "type": "bank_transfer",
    }
    assert captured["json"]["transactions"]["payments"][0]["expiration_time"] == "P1D"


def test_create_pix_order_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.mercado_pago.httpx.post",
        lambda *args, **kwargs: FakeResponse(401, text='{"message":"unauthorized"}'),
    )

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")

    with pytest.raises(MercadoPagoError, match="unauthorized"):
        client.create_pix_order(
            amount=100.0,
            payer_email="ana@email.com",
            external_reference="budget_1_order_2",
        )


def test_list_payment_methods_returns_response_json(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.mercado_pago.httpx.get",
        lambda *args, **kwargs: FakeResponse(200, payload=[{"id": "pix"}, {"id": "visa"}]),
    )

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")

    methods = client.list_payment_methods()

    assert methods == [{"id": "pix"}, {"id": "visa"}]


def test_list_payment_methods_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.mercado_pago.httpx.get",
        lambda *args, **kwargs: FakeResponse(500, text='{"message":"failure"}'),
    )

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")

    with pytest.raises(MercadoPagoError, match="failure"):
        client.list_payment_methods()


def test_get_order_returns_response_json(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.mercado_pago.httpx.get",
        lambda *args, **kwargs: FakeResponse(200, payload={"id": "ORD-123", "status": "processed"}),
    )

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")

    order = client.get_order("ORD-123")

    assert order == {"id": "ORD-123", "status": "processed"}


def test_get_order_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.mercado_pago.httpx.get",
        lambda *args, **kwargs: FakeResponse(404, text='{"message":"not found"}'),
    )

    client = MercadoPagoClient(access_token="token-123", base_url="https://api.test")

    with pytest.raises(MercadoPagoError, match="not found"):
        client.get_order("ORD-404")
