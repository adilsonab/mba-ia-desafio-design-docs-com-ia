# Transcrição classificada — Webhooks de Notificação de Pedidos

Material de trabalho (etapa 2 — contextualização). Cada item cita a fala de origem em `[hh:mm] Nome`.
Itens sem timestamp não entram. Ganchos com o código foram conferidos contra `prisma/schema.prisma`, `package.json` e os relatórios em [analise-codigo/](analise-codigo/).

Participantes: Larissa (Tech Lead), Marcos (PM), Bruno (Eng. Pleno, Pedidos), Diego (Eng. Sênior, Plataforma), Sofia (Segurança).

---

## 0. Contexto e problema

| ID | Item | Origem |
| --- | --- | --- |
| T-CTX-01 | Três clientes B2B (Atlas Comercial, MaxDistribuição, Nova Cargo) pediram notificação de mudança de status de pedido | [09:00] Marcos |
| T-CTX-02 | Hoje fazem polling em `GET /orders`, o que deixa a integração lenta e cara para eles | [09:00] Marcos |
| T-CTX-03 | Risco comercial: Atlas pode migrar para concorrente se não houver entrega até fim do trimestre | [09:00] Marcos |
| T-CTX-04 | "Tempo real" para os clientes = qualquer coisa abaixo de 10 segundos | [09:02] Marcos |
| T-CTX-05 | Clientes nunca pediram ordering global; querem saber se cada pedido mudou | [09:14] Marcos |
| T-CTX-06 | Prazo: Atlas quer para fim de novembro; estimativa de 3 sprints incluindo revisão de segurança | [09:45] Marcos, [09:46] Larissa, [09:47] Larissa |
| T-CTX-07 | Time pequeno — argumento contra subir infraestrutura nova | [09:07] Diego |

## 1. Decisões fechadas

| ID | Decisão | Origem (proposta → fechamento) | ADR candidato |
| --- | --- | --- | --- |
| T-DEC-01 | Entrega assíncrona via **padrão Outbox no MySQL existente**, tabela `webhook_outbox` gravada na **mesma transação** da mudança de status | [09:06] Diego → [09:08] Larissa ("Tá decidido então: outbox em MySQL"); reforço [09:40] Bruno, [09:41] Diego | Outbox no MySQL |
| T-DEC-02 | Worker lê a outbox por **polling a cada 2 s**, eventos pendentes mais antigos, em batch pequeno; latência mínima de 2 s aceita | [09:08] Diego, [09:09] Diego → [09:10] Marcos, [09:10] Larissa ("Vamos registrar isso como uma decisão") | Worker em polling |
| T-DEC-03 | Worker em **processo separado** da API (`src/worker.ts`, `npm run worker`), mesmo banco e mesma stack | [09:11] Diego, [09:11] Larissa, [09:11] Diego | Worker em polling / processo separado |
| T-DEC-04 | Worker abre **PrismaClient próprio** (mesma `DATABASE_URL`, instância nova por processo) | [09:29] Diego (pergunta) → [09:30] Bruno | Worker / reuso |
| T-DEC-05 | **Single-worker**; ordem garantida apenas por `order_id` e enquanto houver um único worker (limitação conhecida) | [09:12] Diego → [09:13] Larissa ("Documentamos como limitação conhecida") | Worker em polling |
| T-DEC-06 | **Retry com backoff exponencial**: 5 tentativas, intervalos 1m / 5m / 30m / 2h / 12h (~15 h); depois falha permanente → DLQ | [09:15] Diego, [09:17] Diego → [09:17] Larissa ("Decidido: 5 tentativas…") | Retry + DLQ |
| T-DEC-07 | **DLQ em tabela separada** `webhook_dead_letter` com payload, motivo da falha e timestamp | [09:18] Diego; confirmado no resumo [09:48] Larissa | Retry + DLQ |
| T-DEC-08 | **Replay manual da DLQ** via `POST /admin/webhooks/dead-letter/:id/replay`, recoloca na outbox como pendente | [09:18] Diego → [09:19] Larissa ("Anota também"); [09:35] Diego | Retry + DLQ |
| T-DEC-09 | Replay exige **role ADMIN**, reaproveitando `requireRole` existente | [09:36] Sofia → [09:36] Larissa ("Decidido…") | Reuso de padrões |
| T-DEC-10 | **HMAC-SHA256 sobre o corpo do request**, assinatura no header `X-Signature` | [09:20] Sofia, [09:20] Sofia → [09:22] Sofia ("Decidido…") | HMAC |
| T-DEC-11 | **Secret única por endpoint** de webhook (não global) | [09:21] Sofia → [09:22] Sofia | HMAC |
| T-DEC-12 | **Rotação de secret** via API; secret antiga válida por **24 h** em paralelo | [09:21] Sofia → [09:22] Sofia | HMAC |
| T-DEC-13 | Garantia **at-least-once**; cliente deduplica por **`X-Event-Id`** (UUID gerado na entrada da outbox, único por evento) | [09:24] Diego, [09:25] Diego → [09:26] Larissa ("Decisão") | At-least-once |
| T-DEC-14 | **Reuso máximo dos padrões existentes**: AppError, Pino, error middleware, módulo em `src/modules/webhooks`, schemas Zod, códigos de erro | [09:27] Bruno, [09:28] Bruno, [09:29] Bruno → [09:30] Larissa ("Decisão: reuso máximo…") | Reuso de padrões |
| T-DEC-15 | Códigos de erro com **prefixo `WEBHOOK_`** (ex.: `WEBHOOK_NOT_FOUND`, `WEBHOOK_INVALID_URL`, `WEBHOOK_SECRET_REQUIRED`) | [09:28] Bruno → [09:29] Larissa | Reuso de padrões |
| T-DEC-16 | **Filtro de eventos aplicado na inserção** da outbox: se nenhum webhook do customer quer aquele status, nada é inserido | [09:33] Marcos, [09:34] Bruno → [09:34] Diego ("Concordo") | (secundária — FDD) |
| T-DEC-17 | Integração via função **`publishWebhookEvent(tx, order, fromStatus, toStatus)`** que recebe o tx client; chamada por `order.service`; falha na outbox → rollback | [09:40] Bruno, [09:41] Bruno → [09:41] Diego | Outbox / reuso |
| T-DEC-18 | IDs da outbox em **UUID**, seguindo o padrão do projeto | [09:51] Diego (pergunta) → [09:51] Larissa | (secundária — FDD) |
| T-DEC-19 | Outbox guarda o **payload renderizado (snapshot) na inserção**, não só o `order_id` | [09:51] Bruno (pergunta) → [09:52] Larissa, [09:52] Diego, [09:52] Bruno ("Decidido") | (secundária — candidato a ADR) |
| T-DEC-20 | Estrutura: lógica do worker em arquivo do módulo (`webhook.worker.ts` ou `webhook.processor.ts`) | [09:28] Bruno → [09:28] Diego ("Beleza") | Reuso de padrões |

## 2. Requisitos funcionais

| ID | Requisito | Origem |
| --- | --- | --- |
| T-RF-01 | Notificar o cliente quando o status de um pedido dele muda (webhook **outbound** apenas) | [09:00] Marcos, [09:02] Marcos, [09:03] Sofia |
| T-RF-02 | Cadastrar webhook: `POST`, campos `url` e lista de status desejados; **secret gerada pela plataforma e devolvida na criação** | [09:31] Marcos |
| T-RF-03 | Endpoint autenticado com JWT do sistema; **`customer_id` vai no body ou no path, não vem do JWT** | [09:32] Marcos, [09:32] Larissa |
| T-RF-04 | Editar (`PATCH`), remover (`DELETE`) e listar (`GET`) webhooks de um customer | [09:33] Bruno |
| T-RF-05 | Filtro por endpoint: lista dos status que o webhook quer ouvir (ex.: só SHIPPED e DELIVERED) | [09:33] Bruno, [09:33] Marcos |
| T-RF-06 | Configuração armazena url + secret + customer_id + estado ativo | [09:21] Bruno → [09:21] Sofia ("Sim") |
| T-RF-07 | Rotação de secret pelo cliente via API | [09:21] Sofia |
| T-RF-08 | Histórico de entregas: `GET /webhooks/:id/deliveries` — últimas 100 entregas com sucesso/falha, payload, response, tempo de resposta | [09:34] Marcos |
| T-RF-09 | Replay manual de item da DLQ: `POST /admin/webhooks/dead-letter/:id/replay` | [09:18] Diego, [09:35] Diego |
| T-RF-10 | Registrar em log **quem executou o replay**, para auditoria | [09:36] Sofia |
| T-RF-11 | Worker envia eventos pendentes, marca como entregue, reprograma em falha, move para DLQ após esgotar tentativas | [09:08] Diego, [09:15] Diego |
| T-RF-12 | Payload JSON: `event_id`, `event_type` (`order.status_changed`), timestamp ISO 8601, `order_id`, `order_number`, `from_status`, `to_status`, `customer_id`, campos básicos da order (ex.: `total_cents`); **sem items** | [09:43] Diego, [09:44] Bruno |
| T-RF-13 | Headers do envio: `X-Event-Id`, `X-Signature`, `X-Timestamp`, `X-Webhook-Id`, `Content-Type: application/json` | [09:44] Diego, [09:44] Sofia, [09:45] Diego |

## 3. Requisitos não funcionais / restrições

| ID | Item | Origem |
| --- | --- | --- |
| T-RNF-01 | Latência de notificação < 10 s (polling de 2 s atende) | [09:02] Marcos, [09:09] Diego |
| T-RNF-02 | Envio HTTP **não pode** ocorrer dentro da transação de `changeStatus` (cliente lento não pode travar mudança de status; falha do cliente não pode dar rollback) | [09:04] Bruno, [09:04] Bruno, [09:06] Diego |
| T-RNF-03 | Se a inserção na outbox falhar, a mudança de status sofre rollback — nunca status mudar sem evento | [09:40] Bruno, [09:41] Diego |
| T-RNF-04 | Timeout do HTTP call do worker: **10 s**; estourou = falha → retry | [09:42] Sofia, [09:42] Diego |
| T-RNF-05 | URL do webhook deve ser **HTTPS**; `http` é recusado com erro de validação no schema Zod | [09:23] Sofia |
| T-RNF-06 | Limite de payload **64 KB**; acima disso, erro (não trunca) | [09:23] Sofia, [09:24] Diego, [09:24] Larissa |
| T-RNF-07 | Tabela outbox com índice em `status` (pendente, processando, falhou, entregue) e em `created_at` | [09:08] Diego |
| T-RNF-08 | Worker lê pendentes em batch pequeno, por ordem de `created_at` | [09:08] Diego, [09:12] Diego |
| T-RNF-09 | `X-Timestamp` existe para o cliente poder detectar replay attack | [09:44] Diego |
| T-RNF-10 | Sem novas bibliotecas de log: Pino existente | [09:29] Bruno |
| T-RNF-11 | Revisão de segurança da Sofia (≥ 2 dias úteis) antes do deploy, foco em HMAC e geração de secret | [09:46] Sofia, [09:47] Larissa, [09:49] Sofia |
| T-RNF-12 | CRUD de configuração aceita qualquer role autenticada (por enquanto) | [09:36] Marcos → [09:37] Sofia |

## 4. Descartado (com motivo)

| ID | Alternativa descartada | Motivo | Origem |
| --- | --- | --- | --- |
| T-DESC-01 | Disparo **síncrono** dentro do service de orders | Transação já pesada; cliente lento trava status de outros pedidos; não dá para fazer rollback do status se o cliente estiver fora | [09:03] Larissa (pergunta), [09:04] Bruno, [09:04] Bruno, [09:06] Diego |
| T-DESC-02 | **Redis Streams / Redis Cluster** (fila externa) | Exige subir infra nova; time pequeno; overengineering | [09:07] Larissa, [09:07] Diego |
| T-DESC-03 | **Trigger do banco** para acordar o worker | MySQL não tem NOTIFY/LISTEN; trigger só executa SQL; improviso seria "esquisito"; polling já atende < 10 s | [09:09] Bruno, [09:09] Diego |
| T-DESC-04 | Worker **dentro do processo da API** | Se a API reinicia, perde o worker | [09:11] Diego |
| T-DESC-05 | **Retry indefinido** com backoff | Evento fica pendurado para sempre se o cliente sumiu | [09:15] Diego |
| T-DESC-06 | **3 tentativas** | Cobre só ~30 min; já houve cliente com 2 h de manutenção | [09:16] Bruno, [09:16] Diego |
| T-DESC-07 | DLQ como status `failed` na própria outbox | Tabela separada deixa a leitura da outbox mais limpa e serve de evidência para debug/reprocessamento | [09:17] Larissa (pergunta), [09:18] Diego |
| T-DESC-08 | **Secret global** da plataforma | Se vaza uma, vaza tudo | [09:21] Sofia |
| T-DESC-09 | **Exactly-once** | Exigiria coordenação dos dois lados, muito mais complexo; at-least-once + event_id resolve 99% | [09:25] Diego |
| T-DESC-10 | **Truncar** payload acima do limite | Se chegou nesse tamanho, tem algo errado → erro | [09:23] Sofia |
| T-DESC-11 | `customer_id` **implícito do JWT** | JWT é do usuário operador, não do cliente | [09:31] Marcos (proposta) → [09:32] Bruno, [09:32] Larissa (reversão) |
| T-DESC-12 | Filtrar eventos **na hora do envio** | Filtrar na inserção economiza linhas | [09:34] Diego (pergunta), [09:34] Bruno |
| T-DESC-13 | Injetar **repository inteiro** do webhook no `OrderService` | Função pura recebendo `tx` é suficiente | [09:41] Bruno, [09:41] Diego |
| T-DESC-14 | Enviar **items** do pedido no payload | Infla o payload; cliente consulta `GET /orders/:id` | [09:43] Diego |
| T-DESC-15 | Guardar só `order_id` e **renderizar no envio** | Pedido pode mudar depois; evento deve refletir o estado no momento da mudança | [09:52] Larissa |
| T-DESC-16 | ID **auto incremental** na outbox | Projeto usa UUID em tudo | [09:51] Larissa |

## 5. Adiado / em aberto / fora de escopo

| ID | Item | Situação | Origem |
| --- | --- | --- | --- |
| T-ADI-01 | **Notificação por e-mail** ao cliente quando o webhook falha repetidamente | Fora de escopo nesta fase; "talvez próxima fase, depois que a gente medir o impacto" | [09:37] Marcos, [09:37] Larissa, [09:38] Marcos |
| T-ADI-02 | **Rate limiting** de envio por cliente | Ponto em aberto: "observar e decidir depois" | [09:38] Diego, [09:39] Diego, [09:39] Larissa |
| T-ADI-03 | **Dashboard visual** para o cliente | Fora de escopo; projeto separado do time de frontend | [09:39] Marcos, [09:40] Larissa |
| T-ADI-04 | **Escalar para múltiplos workers** (particionar por `order_id` ou lock pessimista) | Problema do futuro | [09:13] Bruno, [09:13] Diego |
| T-ADI-05 | **Arquivamento** de linhas entregues após ~30 dias | Fora do escopo desta feature | [09:08] Diego |
| T-ADI-06 | **Endurecer permissões** do CRUD de configuração | "Mais pra frente a gente pode endurecer" | [09:37] Sofia |
| T-ADI-07 | Ordering global | Não é garantido; limitação conhecida | [09:13] Larissa, [09:14] Marcos |
| T-ADI-08 | Portal do desenvolvedor documentando at-least-once e integração | Ação do PM, fora do escopo de engenharia | [09:26] Marcos, [09:40] Marcos |

## 6. Ganchos com o código (verificados)

| ID | Menção na reunião | Origem | Existe no código? |
| --- | --- | --- | --- |
| T-COD-01 | Transação de mudança de status atualiza `orders`, insere em `order_status_history`, mexe em estoque | [09:04] Bruno, [09:40] Bruno | ✅ `src/modules/orders/order.service.ts:131-178` (`changeStatus`); tabelas `orders` e `order_status_history` em `prisma/schema.prisma` (`@@map`). Obs.: o campo é `stockQuantity` no Prisma (Bruno disse `stock_quantity`) |
| T-COD-02 | Entry point existente `src/server.ts`; novo `src/worker.ts` + `npm run worker` | [09:11] Larissa | ✅ `src/server.ts` existe; `src/worker.ts` e script `worker` **não existem** (a criar). Scripts atuais em `package.json`: dev, build, start, db:*, test, lint, format |
| T-COD-03 | Padrão de módulos em `src/modules` (controller, service, repository, routes, schemas) | [09:27] Bruno | ✅ 5 módulos com essa estrutura; `src/modules/webhooks` a criar |
| T-COD-04 | `AppError`, `InsufficientStockError`, `InvalidStatusTransitionError`, códigos `INSUFFICIENT_STOCK`, `INVALID_STATUS_TRANSITION` | [09:28] Bruno | ✅ `src/shared/errors/app-error.ts`, `src/shared/errors/http-errors.ts` |
| T-COD-05 | Logger Pino no projeto inteiro | [09:29] Bruno | ✅ `src/shared/logger/index.ts` |
| T-COD-06 | Error middleware centralizado trata AppError, Zod e Prisma | [09:29] Bruno | ✅ `src/middlewares/error.middleware.ts` (Prisma: só P2002 e P2025) |
| T-COD-07 | Pool/cliente Prisma compartilhado | [09:29] Diego | ✅ `src/config/database.ts` |
| T-COD-08 | `requireRole` existente | [09:36] Larissa | ✅ `src/middlewares/auth.middleware.ts:49-61`; role `ADMIN` no enum `UserRole` (`prisma/schema.prisma:11-14`) |
| T-COD-09 | Schemas Zod para validação (https) | [09:23] Sofia, [09:30] Larissa | ✅ `src/middlewares/validate.middleware.ts` + `*.schemas.ts` |
| T-COD-10 | "Tudo é uuid" | [09:51] Larissa | ✅ Todos os models usam `@id @default(uuid()) @db.Char(36)`, exceto `order_number_sequence` (Int, linha única) |
| T-COD-11 | `GET /orders` e `GET /orders/:id` | [09:00] Marcos, [09:43] Diego | ✅ `src/modules/orders/order.routes.ts:16-17` |
| T-COD-12 | `order_number`, `total_cents` no payload | [09:43] Diego | ✅ `orderNumber`, `totalCents` em `prisma/schema.prisma` (Order). Nomes snake_case são do contrato do payload, não do schema |
| T-COD-13 | JWT do usuário operador; usuários que representam o cliente | [09:32] Bruno, [09:32] Marcos | ✅ JWT com claims `{sub,email,role}` (`src/modules/auth/auth.service.ts`); **não há** vínculo user↔customer no schema |

## 7. Ambiguidades (precisam de decisão sua ao redigir)

| ID | Ambiguidade | Falas | Sugestão de tratamento |
| --- | --- | --- | --- |
| T-AMB-01 | **"5 tentativas" com 5 intervalos de backoff.** 1m/5m/30m/2h/12h são 5 esperas, o que implica 1 envio inicial + 5 retries = 6 envios. Mas "total 5 tentativas" pode significar 5 envios (só 4 intervalos usados) | [09:15] Diego, [09:17] Diego ("~15 h entre primeira falha e última tentativa" = soma dos 5 intervalos ≈ 14,6 h), [09:17] Larissa, [09:48] Larissa | Interpretar como 5 **retries** após a primeira falha (consistente com a soma de ~15 h) e registrar a interpretação explicitamente; levar como questão em aberto no RFC |
| T-AMB-02 | **`customer_id` no body ou no path?** | [09:32] Larissa ("passado no body ou no path") | Não decidido; escolher no FDD e marcar como questão em aberto no RFC |
| T-AMB-03 | **Secret gerada pela plataforma** vs. código de erro `WEBHOOK_SECRET_REQUIRED` | [09:31] Marcos vs. [09:28] Bruno | Secret é gerada pelo servidor; `WEBHOOK_SECRET_REQUIRED` foi exemplo ilustrativo ("etc.") — usar só se houver cenário real (ex.: worker encontra endpoint sem secret) |
| T-AMB-04 | **Uma linha de outbox por evento ou por webhook?** Filtro é por webhook, `X-Webhook-Id` é por envio, mas `X-Event-Id` é "único por evento" | [09:06] Diego, [09:25] Diego, [09:34] Bruno, [09:44] Sofia | Não decidido; FDD precisa escolher (ex.: uma linha por par evento×webhook com o mesmo `event_id`) e declarar como interpretação |
| T-AMB-05 | **Criação de pedido dispara webhook?** Só se falou em mudança de status (`order.status_changed`); a criação grava histórico `null → PENDING` no código | [09:00] Marcos, [09:43] Diego; código `order.service.ts:106-113` | Não discutido → fora do escopo explícito; não inventar. Pode ir como questão em aberto |
| T-AMB-06 | **Rotação: secret nova gerada pelo servidor?** "Endpoint pro cliente conseguir pedir nova secret" | [09:21] Sofia | Implica geração pelo servidor (coerente com T-RF-02); rota exata não foi definida |
| T-AMB-07 | **Quem é o "cliente" autenticado** — não há vínculo user↔customer no schema | [09:32] Marcos, [09:32] Larissa; `prisma/schema.prisma` | Por isso o `customer_id` vai explícito; risco: qualquer usuário autenticado gerencia webhooks de qualquer customer (aceito "por enquanto", [09:37] Sofia) |
| T-AMB-08 | **Prazo**: "fim do trimestre" vs. "fim de novembro" | [09:00] Marcos, [09:45] Marcos | Usar "fim de novembro" (mais recente e específico) |

### Resoluções (revisão humana, 2026-11-02)

| ID | Resolução adotada nos documentos |
| --- | --- |
| T-AMB-01 | **Decidido:** "5 tentativas de reenvio (retries) após a falha do envio inicial", usando os 5 intervalos 1m/5m/30m/2h/12h (~14,6 h) — até 6 chamadas HTTP no pior caso. Coerente com [09:17] Diego ("quase 15 horas") e [09:15] Diego ("janela de até 12 ou 24 horas"). Alternativa rejeitada: 5 envios no total (12h sem uso, janela ~2,6 h) |
| T-AMB-02 | `customer_id` no **body** nas escritas (`POST`); na listagem (`GET`) via **query string** `customer_id`, já que GET não tem body |
| T-AMB-03 | Secret sempre gerada pelo servidor; `WEBHOOK_SECRET_REQUIRED` só entra na matriz de erros se houver cenário real |
| T-AMB-04 | **Uma linha de outbox por webhook interessado**; linhas originadas da mesma mudança de status compartilham o mesmo `event_id` (`X-Event-Id`); retry, DLQ e histórico de entregas são por linha |
| T-AMB-05 | Criação de pedido **não** dispara webhook (não discutido); registrar como questão em aberto no RFC |
| T-AMB-06 | Rotação gera nova secret no servidor; rota definida no FDD como interpretação |
| T-AMB-07 | Risco registrado: sem vínculo user↔customer, qualquer usuário autenticado gerencia webhooks de qualquer customer (aceito por enquanto, [09:37] Sofia) |
| T-AMB-08 | Prazo de referência: fim de novembro ([09:45] Marcos) |

---

## Candidatos a ADR (mapa para a etapa 3)

| # | ADR candidato | Itens | Exigido pelo desafio? |
| --- | --- | --- | --- |
| 1 | Padrão Outbox no MySQL | T-DEC-01, T-DEC-17, T-DESC-01, T-DESC-02 | ✅ |
| 2 | Worker em processo separado com polling de 2 s | T-DEC-02, T-DEC-03, T-DEC-04, T-DEC-05, T-DESC-03, T-DESC-04 | ✅ |
| 3 | Retry com backoff exponencial e DLQ em tabela separada | T-DEC-06, T-DEC-07, T-DEC-08, T-DESC-05, T-DESC-06, T-DESC-07 | ✅ |
| 4 | HMAC-SHA256 com secret por endpoint e rotação | T-DEC-10, T-DEC-11, T-DEC-12, T-DESC-08 | ✅ |
| 5 | At-least-once com `X-Event-Id` | T-DEC-13, T-DESC-09 | ✅ |
| 6 | Reuso dos padrões existentes do projeto | T-DEC-14, T-DEC-15, T-DEC-09, T-DEC-20 | ✅ |
| 7 | Payload como snapshot na inserção (opcional) | T-DEC-19, T-DESC-15, T-DESC-14 | Secundária |
| 8 | Filtro de eventos na inserção da outbox (opcional) | T-DEC-16, T-DESC-12 | Secundária |
