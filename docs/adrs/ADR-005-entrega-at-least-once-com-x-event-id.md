# ADR-005: Garantia de entrega at-least-once com X-Event-Id para deduplicação

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-001](ADR-001-outbox-no-mysql.md), [ADR-003](ADR-003-retry-com-backoff-exponencial-e-dlq.md), [ADR-004](ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md)

## Contexto e Problema

Com a outbox ([ADR-001](ADR-001-outbox-no-mysql.md)) e as retentativas ([ADR-003](ADR-003-retry-com-backoff-exponencial-e-dlq.md)), existem cenários em que o cliente recebe o mesmo evento mais de uma vez. Um exemplo: o cliente processa a requisição, mas a resposta não chega ao worker dentro do timeout de 10 s ([09:42] Diego), e o worker tenta de novo. É preciso definir qual garantia de entrega a plataforma oferece e como o cliente lida com duplicatas ([09:24] Diego, [09:25] Bruno).

## Fatores de Decisão

- Nenhum evento pode ser perdido ([09:06] Diego).
- Complexidade compatível com um time pequeno ([09:07] Diego).
- Seguir o padrão de mercado que os clientes já conhecem ([09:25] Diego).
- O cliente precisa de um identificador estável para reconhecer repetições ([09:25] Bruno).

## Alternativas Consideradas

1. **Exactly-once**: garantir que cada evento seja processado uma única vez.
2. **At-least-once com identificador único do evento**, com a deduplicação feita pelo cliente.

## Decisão

A plataforma garante entrega **at-least-once**: todo evento é entregue, mas pode chegar mais de uma vez ([09:24] Diego). Fechado em [09:26] Larissa: "At-least-once com X-Event-Id pra dedup do lado do cliente. Decisão".

Cada evento recebe um **UUID gerado quando entra na outbox**, enviado no header **`X-Event-Id`** e também no corpo. O identificador é único por evento e se repete em todas as retentativas. O cliente deduplica por ele ([09:25] Diego, [09:43] Diego).

**Interpretação registrada:** quando uma mudança de status interessa a mais de um endpoint do mesmo cliente, cada endpoint tem sua própria entrega, mas todas carregam o mesmo `X-Event-Id`, porque se trata do mesmo evento. As entregas se distinguem pelo header que identifica o endpoint ([09:44] Sofia, [09:45] Diego).

O PM vai destacar essa responsabilidade do cliente no portal do desenvolvedor ([09:26] Marcos).

## Prós e Contras das Alternativas

### Exactly-once
- ✅ O cliente não precisa tratar duplicatas.
- ❌ Exige coordenação dos dois lados, "muito mais complexo" ([09:25] Diego).
- ❌ Não é praticado pelos provedores de referência do mercado ([09:25] Diego).

### At-least-once com X-Event-Id (escolhida)
- ✅ Padrão de mercado ("Stripe faz assim, GitHub faz assim", [09:25] Diego).
- ✅ Combina naturalmente com outbox e retry: reenviar é sempre seguro do lado da plataforma.
- ✅ "Resolve 99% dos casos" ([09:25] Diego).
- ❌ Transfere ao cliente a responsabilidade de deduplicar ([09:25] Sofia).

## Consequências

### Positivas
- Nenhum evento é perdido por timeout ou falha de rede: na dúvida, a plataforma reenvia.
- O identificador estável também serve para correlacionar o histórico de entregas, a DLQ e os logs.
- A implementação continua simples, sem protocolo de confirmação em duas fases.

### Negativas
- Clientes que não deduplicam podem processar o mesmo evento duas vezes, por exemplo registrando "pedido enviado" em dobro.
- A responsabilidade do cliente precisa ser comunicada com destaque, o que depende de documentação externa ([09:26] Marcos).
- Duplicatas também podem surgir de replays manuais da DLQ ([ADR-003](ADR-003-retry-com-backoff-exponencial-e-dlq.md)).

### Trade-off explícito
A plataforma abre mão de **simplicidade para o cliente** (não precisar deduplicar) em troca de **simplicidade e confiabilidade do lado da plataforma**. É o mesmo equilíbrio adotado pelos principais provedores de webhooks.

## Referências

- `prisma/schema.prisma`: todos os modelos usam identificadores UUID, padrão seguido pelo identificador do evento ([09:51] Larissa).
- Transcrição: [09:06] Diego, [09:24] Diego, [09:25] Bruno, [09:25] Diego, [09:25] Sofia, [09:26] Marcos, [09:26] Larissa, [09:42] Diego, [09:43] Diego, [09:44] Diego, [09:44] Sofia, [09:45] Diego, [09:48] Larissa.
