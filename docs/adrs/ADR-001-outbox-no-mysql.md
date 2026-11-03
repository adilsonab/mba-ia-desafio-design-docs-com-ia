# ADR-001: Padrão Outbox no MySQL para eventos de webhook

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-002](ADR-002-worker-separado-com-polling.md), [ADR-005](ADR-005-entrega-at-least-once-com-x-event-id.md), [ADR-006](ADR-006-reuso-dos-padroes-existentes.md)

## Contexto e Problema

Três clientes B2B pediram para ser notificados quando o status de seus pedidos muda; hoje fazem polling em `GET /orders`, o que torna a integração lenta e cara para eles ([09:00] Marcos). O OMS não tem nenhum mecanismo de eventos, filas ou chamadas HTTP de saída.

Toda mudança de status passa por uma única transação de banco no serviço de pedidos, que valida a transição, movimenta estoque, atualiza o pedido e grava o histórico de status ([09:04] Bruno; `src/modules/orders/order.service.ts:131-178`). A questão é onde e como originar a notificação sem comprometer essa transação e sem perder eventos: se o status mudou, o cliente precisa ser avisado; se a mudança foi desfeita, nenhum aviso pode sair.

## Fatores de Decisão

- Uma chamada HTTP a um cliente lento não pode travar a mudança de status de outros pedidos ([09:04] Bruno).
- A indisponibilidade do cliente não pode desfazer uma mudança de status já válida ([09:04] Bruno).
- Consistência total entre "status mudou" e "evento registrado" ([09:06] Diego, [09:40] Bruno).
- Time pequeno: evitar infraestrutura nova para operar ([09:07] Diego).
- Latência aceitável pelos clientes: abaixo de 10 segundos ([09:02] Marcos).

## Alternativas Consideradas

1. **Disparo síncrono** da chamada HTTP dentro da transação de mudança de status.
2. **Fila externa** (Redis Streams / Redis Cluster).
3. **Outbox no MySQL existente**: registrar o evento numa tabela de saída dentro da mesma transação; um processo separado faz a entrega.

## Decisão

Adotar o **padrão Outbox no MySQL já usado pela aplicação** ([09:06] Diego; fechado em [09:08] Larissa: "Tá decidido então: outbox em MySQL").

A gravação do evento na outbox acontece **dentro da mesma transação** que atualiza o pedido e o histórico de status. Se a gravação na outbox falhar, a transação inteira sofre rollback: não pode existir mudança de status sem evento correspondente ([09:40] Bruno, [09:41] Diego). A entrega HTTP fica fora da transação, a cargo de um worker ([ADR-002](ADR-002-worker-separado-com-polling.md)).

A tabela de outbox terá índices por estado do evento e por data de criação, para leitura eficiente dos pendentes ([09:08] Diego). O arquivamento de eventos entregues fica fora do escopo desta feature ([09:08] Diego).

## Prós e Contras das Alternativas

### Disparo síncrono
- ✅ Simples; latência mínima.
- ❌ Cliente lento trava a mudança de status de outros pedidos ([09:04] Bruno).
- ❌ Cliente fora do ar forçaria rollback da mudança de status, o que é inaceitável ([09:04] Bruno).
- ❌ Descartado por consenso: "Síncrono está fora de questão" ([09:06] Diego).

### Fila externa (Redis Streams / Cluster)
- ✅ Infraestrutura feita para mensageria; escala melhor *(análise do autor)*.
- ❌ Exige subir e operar infraestrutura nova ([09:07] Larissa).
- ❌ "Overengineering" para um time pequeno ([09:07] Diego).
- ❌ Gravar no banco e publicar na fila são duas operações separadas, e o risco de inconsistência entre elas permanece *(análise do autor)*.

### Outbox no MySQL (escolhida)
- ✅ Atomicidade: evento e mudança de status são confirmados ou desfeitos juntos ([09:06] Diego).
- ✅ Nenhuma infraestrutura nova: mesmo banco, mesma stack.
- ❌ Eventos acumulados na tabela podem deixar o worker lento ([09:07] Bruno). A mitigação acordada é ler só os pendentes, em lote pequeno, com índices por estado e data de criação ([09:08] Diego).
- ❌ Exige um processo leitor (worker) e política de limpeza futura.

## Consequências

### Positivas
- Elimina a inconsistência entre estado do pedido e eventos emitidos: "Não tem inconsistência possível" ([09:06] Diego).
- A transação de mudança de status não passa a depender da rede nem da disponibilidade dos clientes.
- A operação continua sem componentes novos para monitorar, o que é adequado ao tamanho do time.

### Negativas
- A transação de mudança de status fica um pouco mais longa (uma escrita a mais) e passa a poder falhar por causa da outbox.
- A latência de entrega passa a depender do ciclo do worker (ver [ADR-002](ADR-002-worker-separado-com-polling.md)), não é mais imediata.
- A tabela cresce continuamente até que exista arquivamento, adiado para fora desta feature ([09:08] Diego).

### Trade-off explícito
Troca-se latência mínima e simplicidade do disparo direto por **consistência garantida e isolamento de falhas**, sem custo de infraestrutura nova. O banco MySQL passa a ser também o "barramento" de eventos. A reunião não quantificou o volume; a aposta é que índices e leitura em lote bastam ([09:08] Diego), e o arquivamento futuro limita o crescimento da tabela.

## Referências

- `src/modules/orders/order.service.ts:131-178`: transação de mudança de status onde o evento será registrado.
- `prisma/schema.prisma:116-131`: histórico de status, gravado na mesma transação.
- `src/config/database.ts`: cliente Prisma sobre o MySQL existente.
- Transcrição: [09:03] Larissa, [09:04] Bruno, [09:06] Diego, [09:07] Larissa, [09:07] Diego, [09:07] Bruno, [09:08] Diego, [09:08] Larissa, [09:40] Bruno, [09:41] Diego, [09:48] Larissa.
