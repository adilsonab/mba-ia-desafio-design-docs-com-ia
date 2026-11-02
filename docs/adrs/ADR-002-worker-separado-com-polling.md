# ADR-002: Worker em processo separado com polling de 2 segundos

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-001](ADR-001-outbox-no-mysql.md), [ADR-003](ADR-003-retry-com-backoff-exponencial-e-dlq.md), [ADR-006](ADR-006-reuso-dos-padroes-existentes.md)

## Contexto e Problema

Com a outbox no MySQL ([ADR-001](ADR-001-outbox-no-mysql.md)), alguém precisa ler os eventos pendentes e fazer as chamadas HTTP aos clientes. Duas perguntas ficaram abertas: como o leitor descobre que há eventos novos, e onde ele roda.

A aplicação hoje tem um único processo e um único ponto de entrada, o servidor HTTP (`src/server.ts`), sem scheduler nem processo de background. Os clientes consideram "tempo real" qualquer entrega abaixo de 10 segundos ([09:02] Marcos) e nunca pediram ordem global de eventos ([09:14] Marcos).

## Fatores de Decisão

- Latência de entrega abaixo de 10 segundos ([09:02] Marcos).
- MySQL não oferece notificação nativa a processos externos ([09:09] Diego).
- O ciclo de vida da entrega não pode depender de reinícios da API ([09:11] Diego).
- Manter a mesma stack e o mesmo banco ([09:11] Bruno, [09:11] Diego).
- Ordem de entrega por pedido é suficiente; ordem global não é requisito ([09:12] Diego, [09:14] Marcos).

## Alternativas Consideradas

1. **Trigger do banco** para acordar o worker de forma reativa.
2. **Worker dentro do processo da API.**
3. **Worker em processo separado, lendo a outbox por polling a cada 2 segundos.**

## Decisão

O worker roda como **processo separado** da API, com ponto de entrada próprio ao lado do servidor existente e script de execução dedicado ([09:11] Diego, [09:11] Larissa). Usa o **mesmo banco e a mesma stack**, mas com **instância própria do cliente Prisma**, porque o cliente é por processo ([09:11] Bruno, [09:30] Bruno).

O worker faz **polling em loop a cada 2 segundos**: busca em lote pequeno os eventos pendentes mais antigos, processa e marca o resultado ([09:08] Diego, [09:09] Diego). A latência de até 2 segundos no pior caso foi aceita ([09:10] Marcos, [09:10] Larissa).

Roda **um único worker**. A ordem de entrega é a ordem de criação na outbox, o que garante sequência **por pedido** apenas enquanto houver um só worker. Isso fica documentado como **limitação conhecida** ([09:12] Diego, [09:13] Larissa).

## Prós e Contras das Alternativas

### Trigger do banco
- ✅ Seria reativo, sem espera de ciclo.
- ❌ MySQL não tem listener nativo como o NOTIFY/LISTEN do Postgres; trigger só executa SQL ([09:09] Diego).
- ❌ Avisar o worker exigiria improviso (escrever em arquivo, chamar endpoint), "fica esquisito" ([09:09] Diego).

### Worker dentro da API
- ✅ Um processo a menos para implantar.
- ❌ Se a API reinicia, o worker para junto ([09:11] Diego).
- ❌ Carga de entrega concorre com o atendimento HTTP.

### Processo separado com polling (escolhida)
- ✅ Polling de 2 s cumpre com folga o limite de 10 s ([09:09] Diego).
- ✅ Ciclo de vida independente da API.
- ✅ Simples: mesma linguagem, mesmo banco, mesmo ORM.
- ❌ Consultas periódicas ao banco mesmo sem eventos.
- ❌ Novo processo para implantar e monitorar.

## Consequências

### Positivas
- Entregas continuam durante reinícios ou deploys da API.
- Nenhuma tecnologia nova: o worker reaproveita configuração, logger e padrões do projeto ([ADR-006](ADR-006-reuso-dos-padroes-existentes.md)).
- Latência previsível: no máximo um ciclo de 2 s até a primeira tentativa.

### Negativas
- Latência mínima de 2 s no pior caso, aceita explicitamente ([09:10] Larissa).
- **Sem garantia de ordem global**, e a ordem por pedido vale só com um único worker ([09:13] Larissa).
- Um único worker limita a vazão. Escalar para vários workers (particionando por pedido ou com lock pessimista) foi adiado como "problema do futuro" ([09:13] Diego).
- Duas conexões ao banco (API e worker) passam a disputar o mesmo MySQL.

### Trade-off explícito
Aceita-se **latência de até 2 s e vazão limitada a um worker** em troca de **simplicidade operacional e ordem por pedido** sem coordenação entre processos.

## Referências

- `src/server.ts`: ponto de entrada atual, modelo para o novo ponto de entrada do worker.
- `src/config/database.ts`: criação do cliente Prisma, reutilizável pelo worker.
- `package.json`: scripts atuais, onde entrará o script do worker.
- Transcrição: [09:08] Larissa, [09:09] Diego, [09:09] Bruno, [09:10] Marcos, [09:10] Larissa, [09:11] Diego, [09:11] Larissa, [09:11] Bruno, [09:12] Diego, [09:13] Diego, [09:13] Larissa, [09:14] Marcos, [09:28] Bruno, [09:30] Bruno.
