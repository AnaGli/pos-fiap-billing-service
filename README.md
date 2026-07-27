# Billing Service

Serviço responsável pela parte comercial e financeira da oficina.

## Responsabilidades

- Manter catálogo e preços de serviços/peças;
- Gerar orçamento a partir do diagnóstico;
- Gerar cobrança Pix e registrar pagamento;
- Registrar estorno;
- Publicar eventos de orçamento e pagamento em outbox.

## Execução via Docker

```bash
docker compose up --build
```

API: `http://localhost:8003`  
Docs: `http://localhost:8003/docs`

Variáveis de ambiente para Mercado Pago:

- `MERCADO_PAGO_ACCESS_TOKEN`
- `MERCADO_PAGO_BASE_URL` (opcional, padrão `https://api.mercadopago.com`)

Teste rápido de conexão com o Mercado Pago:

```bash
curl http://localhost:8003/integrations/mercado-pago/payment-methods
```

Esse endpoint consulta `GET /v1/payment_methods` no Mercado Pago e ajuda a validar:

- token configurado
- conectividade com a API
- disponibilidade do meio `pix`

Para publicar a outbox no broker:

```bash
python -m app.messaging.outbox_publisher
```

Para consumir eventos do RabbitMQ:

```bash
python -m app.messaging.consumer
```

## Fluxo

1. Recebe `DiagnosisCompleted`;
2. Calcula valores com base no catálogo local;
3. Cria orçamento com status `WAITING_APPROVAL`;
4. Ao iniciar o pagamento Pix, cria uma `order` no Mercado Pago e armazena o QR Code;
5. Após confirmação do pagamento, publica `PaymentApproved`;
6. Em compensação, registra estorno e publica `RefundProcessed`.

## BDD

O serviço possui um cenário BDD em Gherkin cobrindo o fluxo de:

- recebimento do diagnóstico;
- criação do orçamento;
- abertura do Pix;
- confirmação do pagamento;
- compensação com estorno após falha de execução.

Arquivos:

- `tests/features/billing_pix_flow.feature`
- `tests/test_bdd_billing.py`

## Endpoint Pix

Criação da cobrança Pix:

```bash
curl -X POST http://localhost:8003/budgets/1/pay/pix \
  -H "Content-Type: application/json" \
  -d '{
    "payer_email": "cliente@email.com",
    "expiration_time": "P1D"
  }'
```
