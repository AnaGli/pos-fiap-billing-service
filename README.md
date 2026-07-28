# Billing Service

Serviço responsável pela parte comercial e financeira da oficina. Ele é o dono
do catálogo, dos orçamentos, dos pagamentos e das compensações financeiras.

Para a visão consolidada da solução, incluindo a arquitetura completa e o
padrão Saga adotado, consulte:

- [Documentação Geral da Solução](../pos-fiap-os-service/docs/README.md)

## Responsabilidades

- manter catálogo e preços de serviços/peças;
- gerar orçamento a partir do diagnóstico;
- iniciar cobrança Pix no Mercado Pago;
- confirmar pagamento;
- registrar estorno;
- publicar eventos financeiros e comerciais via outbox.

## Bancos de Dados

- relacional: PostgreSQL
- banco lógico relacional: `billing_service`
- não relacional: DynamoDB
- tabela NoSQL: `billing_catalog`

O catálogo foi isolado no `Billing Service`, sem dependência direta de outros
serviços ou acesso cruzado a bancos externos.

## Eventos

### Publicados

- `BudgetCreated`
- `PaymentApproved`
- `RefundProcessed`

### Consumidos

- `DiagnosisCompleted`
- `ExecutionFailed`

## Endpoints

Principais endpoints:

- `POST /catalog/items`
- `GET /catalog/items`
- `GET /integrations/mercado-pago/payment-methods`
- `POST /internal/events/diagnosis-completed`
- `GET /budgets/{budget_id}`
- `POST /budgets/{budget_id}/approve`
- `POST /budgets/{budget_id}/pay/pix`
- `POST /budgets/{budget_id}/confirm-payment`
- `POST /orders/{order_id}/refund`
- `GET /health`

Swagger:

- `http://localhost:8003/docs`

## Execução Local

O serviço é executado exclusivamente via Docker.

Subida local:

```bash
docker compose up --build
```

API:

- `http://localhost:8003`

## Mercado Pago

Variáveis de ambiente:

- `MERCADO_PAGO_ACCESS_TOKEN`
- `MERCADO_PAGO_BASE_URL` (opcional, padrão `https://api.mercadopago.com`)

Teste rápido de conectividade:

```bash
curl http://localhost:8003/integrations/mercado-pago/payment-methods
```

Esse endpoint consulta `GET /v1/payment_methods` e ajuda a validar:

- token configurado;
- conectividade com a API;
- disponibilidade do meio `pix`.

Exemplo de criação de cobrança Pix:

```bash
curl -X POST http://localhost:8003/budgets/1/pay/pix \
  -H "Content-Type: application/json" \
  -d '{
    "payer_email": "cliente@email.com",
    "expiration_time": "P1D"
  }'
```

## Fluxo Funcional

1. Consome `DiagnosisCompleted`;
2. consulta o catálogo local;
3. cria orçamento com status `WAITING_APPROVAL`;
4. publica `BudgetCreated`;
5. inicia cobrança Pix no Mercado Pago;
6. após confirmação, publica `PaymentApproved`;
7. em caso de falha operacional, processa compensação com `RefundProcessed`.

## BDD

Este serviço contém o cenário BDD principal da solução, cobrindo:

- recebimento do diagnóstico;
- criação do orçamento;
- abertura do Pix;
- confirmação do pagamento;
- compensação com estorno após falha de execução.

Arquivos:

- `tests/features/billing_pix_flow.feature`
- `tests/test_bdd_billing.py`

## Testes

Para executar os testes dentro do container:

```bash
docker compose run --rm api sh -c "alembic upgrade head && pytest -q"
```

## Observabilidade

O serviço possui integração com Datadog para:

- traces HTTP;
- traces de consumo/publicação no RabbitMQ;
- traces SQL;
- logs estruturados com `correlation_id`.

Serviços esperados no Datadog:

- `billing-service`
- `billing-service-publisher`
- `billing-service-consumer`
- `billing-service-db`

## CI/CD e Deploy

Artefatos presentes no repositório:

- Dockerfile
- manifestos Kubernetes em `k8s/`
- pipeline em `.github/workflows/ci-cd.yml`

O pipeline contempla:

- build;
- testes automatizados;
- validação de qualidade;
- deploy automatizado em Kubernetes.
