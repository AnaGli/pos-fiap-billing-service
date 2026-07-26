# Billing Service

Serviço responsável pela parte comercial e financeira da oficina.

## Responsabilidades

- Manter catálogo e preços de serviços/peças;
- Gerar orçamento a partir do diagnóstico;
- Aprovar orçamento e registrar pagamento;
- Registrar estorno;
- Publicar eventos de orçamento e pagamento em outbox.

## Execução via Docker

```bash
docker compose up --build
```

API: `http://localhost:8003`  
Docs: `http://localhost:8003/docs`

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
4. Ao aprovar, registra pagamento e publica `PaymentApproved`;
5. Em compensação, registra estorno e publica `RefundProcessed`.
