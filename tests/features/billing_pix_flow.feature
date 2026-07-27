Feature: Fluxo de orçamento, pagamento Pix e compensação
  Como Billing Service
  Quero transformar um diagnóstico em orçamento, registrar o pagamento Pix e compensar uma falha posterior
  Para manter o fluxo financeiro consistente

  Scenario: Gerar orçamento, confirmar Pix e processar estorno compensatório
    Given o catálogo do billing possui serviço e peça base
    And existe um diagnóstico concluído para a ordem 501
    When o billing recebe o diagnóstico concluído
    Then o orçamento da ordem 501 é criado aguardando aprovação
    When o cliente inicia o pagamento Pix do orçamento
    Then o billing retorna os dados da cobrança Pix
    When o billing confirma o pagamento no Mercado Pago
    Then o orçamento fica com status PAID
    And o evento PaymentApproved é publicado na outbox
    When o billing recebe uma falha de execução da ordem 501
    Then o orçamento fica com status REFUNDED
    And o evento RefundProcessed é publicado na outbox
