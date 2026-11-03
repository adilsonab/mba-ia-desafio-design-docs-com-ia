# ADR-003: Retry com backoff exponencial e Dead Letter Queue em tabela separada

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-002](ADR-002-worker-separado-com-polling.md), [ADR-005](ADR-005-entrega-at-least-once-com-x-event-id.md), [ADR-006](ADR-006-reuso-dos-padroes-existentes.md)

## Contexto e Problema

Endpoints de clientes ficam fora do ar, lentos ou com erro. A equipe já teve cliente com duas horas de indisponibilidade em manutenção planejada ([09:16] Diego). O worker ([ADR-002](ADR-002-worker-separado-com-polling.md)) precisa de uma política para falhas: quantas vezes tentar de novo, com que intervalo, e o que fazer com um evento que nunca é entregue, sem perdê-lo nem deixá-lo pendurado para sempre.

## Fatores de Decisão

- Cobrir indisponibilidades reais de várias horas ([09:16] Diego).
- Evitar eventos pendurados indefinidamente quando o cliente some ([09:15] Diego).
- Manter a outbox principal limpa para a leitura do worker ([09:18] Diego).
- Preservar evidência para debug e reprocessamento ([09:18] Diego).
- Reprocessamento é ação sensível, restrita a administradores ([09:36] Sofia).

## Alternativas Consideradas

1. **Retry indefinido** com backoff.
2. **3 tentativas** de reenvio.
3. **5 tentativas de reenvio com backoff exponencial**, seguidas de DLQ em **tabela separada**.

Para o destino das falhas definitivas, também se considerou **marcar o evento como "falhou" na própria outbox** ([09:17] Larissa).

## Decisão

Cada entrega que falha (erro HTTP, timeout ou indisponibilidade) é reprogramada com **backoff exponencial em 5 tentativas de reenvio**, com os intervalos **1 min → 5 min → 30 min → 2 h → 12 h** ([09:17] Diego; fechado em [09:17] Larissa: "Decidido: 5 tentativas, backoff 1m/5m/30m/2h/12h").

**Interpretação registrada:** as 5 tentativas são **reenvios após a falha do envio inicial**. Assim, os 5 intervalos são todos usados, há até 6 chamadas HTTP no pior caso, e a janela entre a primeira falha e a última tentativa é de cerca de 14,6 h. Isso coincide com "quase 15 horas" ([09:17] Diego) e com "uma janela de até 12 ou 24 horas" ([09:15] Diego). Contar 5 envios no total deixaria o intervalo de 12 h sem uso e reduziria a janela a ~2,6 h, contradizendo essas falas.

**Evidência contrária, a confirmar no design review:** no resumo de fechamento, a Larissa diz "1m/5m/30m/2h/12h, **total 5 tentativas**, depois DLQ" ([09:48] Larissa), e todos confirmam ([09:49] Diego, [09:49] Bruno). Lida ao pé da letra, essa fala favorece os 5 envios no total. A leitura adotada aqui se mantém porque é a única em que os cinco intervalos e as "quase 15 horas" fecham ao mesmo tempo. Mas a reunião se contradiz nesse ponto, e a contagem precisa ser confirmada na sessão de revisão de design ([09:50] Larissa).

Esgotadas as tentativas, a entrega é considerada **falha permanente** e movida para uma **tabela de dead letter separada**, com o payload, o motivo da falha e o momento ([09:15] Diego, [09:18] Diego).

O reprocessamento é **manual**, por um endpoint administrativo que recoloca o evento na outbox como pendente ([09:18] Diego). Ele exige **papel ADMIN** e registra em log **quem executou o replay**, para auditoria ([09:36] Sofia, [09:36] Larissa).

## Prós e Contras das Alternativas

### Retry indefinido
- ✅ Nunca desiste de entregar.
- ❌ Evento fica pendurado para sempre se o cliente sumiu ([09:15] Diego).
- ❌ Fila cresce sem limite e sem sinal claro de falha *(análise do autor)*.

### 3 tentativas
- ✅ Detecta falha mais rápido ("mais agressivo", [09:16] Bruno).
- ❌ Cobre só ~30 minutos; mataria o evento numa manutenção de 2 h ([09:16] Diego).

### 5 reenvios com backoff + DLQ separada (escolhida)
- ✅ Janela de ~15 h cobre manutenções planejadas longas.
- ✅ Fim determinístico: todo evento termina entregue ou na DLQ.
- ✅ DLQ separada mantém a outbox enxuta e preserva evidência ([09:18] Diego).
- ❌ Cliente que volta depois de ~15 h depende de replay manual.
- ❌ Mais uma tabela e um endpoint administrativo para manter.

### "Falhou" na própria outbox
- ✅ Uma tabela a menos.
- ❌ Mistura falhas definitivas com a fila de trabalho do worker; leitura menos limpa ([09:18] Diego).

## Consequências

### Positivas
- Indisponibilidades de até ~15 h são absorvidas sem intervenção humana. O PM considerou aceitável que falhas além disso sejam problema do cliente ([09:17] Marcos).
- Nenhum evento se perde: o que não é entregue fica na DLQ, com motivo, pronto para replay.
- O replay fica protegido por papel ADMIN e é auditável.

### Negativas
- Uma entrega pode atrasar até ~15 h antes de ir para a DLQ.
- Retentativas aumentam a chance de o cliente receber o mesmo evento mais de uma vez, coberto pela garantia at-least-once ([ADR-005](ADR-005-entrega-at-least-once-com-x-event-id.md)).
- Não há aviso proativo ao cliente quando o endpoint dele falha repetidamente. Notificação por e-mail foi adiada para uma próxima fase ([09:37] Larissa).
- Reprocessamento depende de ação humana de um administrador.

### Trade-off explícito
Troca-se **persistência ilimitada** (retry infinito) por **término previsível com recuperação manual**. A janela de ~15 h equilibra a cobertura de indisponibilidades reais com a necessidade de não manter eventos pendurados.

## Referências

- `src/middlewares/auth.middleware.ts:49-61`: `requireRole`, reutilizado para restringir o replay a ADMIN.
- `prisma/schema.prisma:11-14`: papéis `ADMIN` e `OPERATOR`.
- `src/shared/logger/index.ts`: logger usado para o registro de auditoria do replay.
- Transcrição: [09:14] Larissa, [09:15] Diego, [09:16] Bruno, [09:16] Diego, [09:17] Diego, [09:17] Marcos, [09:17] Larissa, [09:18] Diego, [09:19] Larissa, [09:35] Diego, [09:36] Sofia, [09:36] Larissa, [09:42] Diego, [09:48] Larissa, [09:49] Diego, [09:49] Bruno, [09:50] Larissa.
