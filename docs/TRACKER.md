# Tracker de Rastreabilidade

Referência cruzada entre cada item registrado nos documentos e sua origem: a transcrição da reunião (`TRANSCRICAO.md`) ou o código-fonte.

- **Fonte `TRANSCRICAO`**: a localização é a fala principal, no formato `[hh:mm] Nome`. Outras falas relacionadas estão citadas no próprio documento.
- **Fonte `CODIGO`**: a localização é o caminho do arquivo. Quando relevante, as linhas aparecem no resumo.
- **Decisão de desenho (derivada)**: detalhe de implementação marcado com **[D]** no FDD. A reunião não o fixou literalmente; a linha aponta para a decisão da qual ele deriva.
- **Interpretação**: leitura de um ponto ambíguo da reunião, registrada como tal no RFC (§5) e nos ADRs.

| ID | Documento | Tipo | Conteúdo (resumo) | Fonte | Localização |
| --- | --- | --- | --- | --- | --- |
| PRD-CTX-01 | `docs/PRD.md` | Contexto | Pedido formal de 3 clientes B2B (Atlas, MaxDistribuição, Nova Cargo) por notificação de status | TRANSCRICAO | [09:00] Marcos |
| PRD-PROB-01 | `docs/PRD.md` | Problema | Clientes fazem polling em `GET /orders`; integração lenta e cara | TRANSCRICAO | [09:00] Marcos |
| PRD-PROB-02 | `docs/PRD.md` | Restrição de negócio | Atlas pode migrar para concorrente se não houver entrega | TRANSCRICAO | [09:00] Marcos |
| PRD-PROB-03 | `docs/PRD.md` | Restrição | Prazo pedido: fim de novembro | TRANSCRICAO | [09:45] Marcos |
| PRD-PROB-04 | `docs/PRD.md` | Requisito Não Funcional | "Tempo real" para o cliente = menos de 10 s | TRANSCRICAO | [09:02] Marcos |
| PRD-PUB-01 | `docs/PRD.md` | Público-alvo | Usuários do OMS que representam o cliente usam a API autenticada | TRANSCRICAO | [09:32] Marcos |
| PRD-PUB-02 | `docs/PRD.md` | Público-alvo | Administrador reprocessa falhas definitivas | TRANSCRICAO | [09:36] Sofia |
| PRD-PUB-03 | `docs/PRD.md` | Público-alvo | PM documenta a integração no portal do desenvolvedor | TRANSCRICAO | [09:40] Marcos |
| PRD-META-01 | `docs/PRD.md` | Metadado | Escopo aprovado; desenho técnico em revisão antes de codar | TRANSCRICAO | [09:50] Larissa |
| PRD-CEN-01 | `docs/PRD.md` | Cenário de uso | Cliente assina só SHIPPED e DELIVERED | TRANSCRICAO | [09:33] Marcos |
| PRD-CEN-02 | `docs/PRD.md` | Cenário de uso | Endpoint em manutenção de 2 h recebe após reenvios | TRANSCRICAO | [09:16] Diego |
| PRD-CEN-03 | `docs/PRD.md` | Cenário de uso | Indisponibilidade > ~15 h vai para fila de falhas e replay manual | TRANSCRICAO | [09:18] Diego |
| PRD-CEN-04 | `docs/PRD.md` | Cenário de uso | Cliente ignora notificação repetida pelo ID do evento | TRANSCRICAO | [09:25] Diego |
| PRD-CEN-05 | `docs/PRD.md` | Cenário de uso | Cliente troca segredo vazado; antigo vale 24 h | TRANSCRICAO | [09:21] Sofia |
| PRD-CEN-06 | `docs/PRD.md` | Cenário de uso | Integrador diagnostica pelas últimas 100 entregas | TRANSCRICAO | [09:34] Marcos |
| PRD-OBJ-01 | `docs/PRD.md` | Objetivo / Métrica | p95 da latência de notificação < 10 s (sujeito ao risco do cliente lento) | TRANSCRICAO | [09:02] Marcos |
| PRD-OBJ-02 | `docs/PRD.md` | Objetivo / Métrica | Zero mudanças de status sem evento | TRANSCRICAO | [09:06] Diego |
| PRD-OBJ-03 | `docs/PRD.md` | Objetivo / Métrica | Janela de reenvio automático de ~15 h | TRANSCRICAO | [09:17] Diego |
| PRD-OBJ-04 | `docs/PRD.md` | Objetivo / Métrica | 3 de 3 clientes solicitantes em produção até fim de novembro | TRANSCRICAO | [09:45] Marcos |
| PRD-OBJ-05 | `docs/PRD.md` | Objetivo / Métrica | Atlas retida após a entrega | TRANSCRICAO | [09:00] Marcos |
| PRD-OUT-01 | `docs/PRD.md` | Fora de escopo (adiado) | Aviso por e-mail quando o webhook falha | TRANSCRICAO | [09:37] Larissa |
| PRD-OUT-02 | `docs/PRD.md` | Fora de escopo (descartado) | Dashboard visual para o cliente | TRANSCRICAO | [09:40] Larissa |
| PRD-OUT-03 | `docs/PRD.md` | Fora de escopo (adiado) | Rate limiting de saída | TRANSCRICAO | [09:39] Larissa |
| PRD-OUT-04 | `docs/PRD.md` | Fora de escopo | Webhooks de entrada (cliente → OMS) | TRANSCRICAO | [09:02] Marcos |
| PRD-OUT-05 | `docs/PRD.md` | Fora de escopo | Garantia de ordem global | TRANSCRICAO | [09:13] Larissa |
| PRD-OUT-06 | `docs/PRD.md` | Fora de escopo (descartado) | Entrega exactly-once | TRANSCRICAO | [09:25] Diego |
| PRD-OUT-07 | `docs/PRD.md` | Fora de escopo (adiado) | Restrição de papel no CRUD de webhooks | TRANSCRICAO | [09:37] Sofia |
| PRD-OUT-08 | `docs/PRD.md` | Fora de escopo | Arquivamento das notificações entregues da outbox (~30 dias) | TRANSCRICAO | [09:08] Diego |
| PRD-FR-01 | `docs/PRD.md` | Requisito Funcional | Notificar o cliente via HTTP a cada mudança de status | TRANSCRICAO | [09:00] Marcos |
| PRD-FR-02 | `docs/PRD.md` | Requisito Funcional | Cadastrar webhook (cliente, URL, status de interesse) | TRANSCRICAO | [09:31] Marcos |
| PRD-FR-03 | `docs/PRD.md` | Requisito Funcional | Segredo gerado pela plataforma e devolvido na criação | TRANSCRICAO | [09:31] Marcos |
| PRD-FR-04 | `docs/PRD.md` | Requisito Funcional | Editar, remover e listar webhooks de um cliente | TRANSCRICAO | [09:33] Bruno |
| PRD-FR-05 | `docs/PRD.md` | Requisito Funcional | Webhook recebe só os status escolhidos | TRANSCRICAO | [09:33] Marcos |
| PRD-FR-06 | `docs/PRD.md` | Requisito Funcional | Troca de segredo com convivência de 24 h | TRANSCRICAO | [09:21] Sofia |
| PRD-FR-07 | `docs/PRD.md` | Requisito Funcional | Notificação assinada (origem e integridade) | TRANSCRICAO | [09:19] Sofia |
| PRD-FR-08 | `docs/PRD.md` | Requisito Funcional | Identificador único do evento para deduplicação | TRANSCRICAO | [09:25] Diego |
| PRD-FR-09 | `docs/PRD.md` | Requisito Funcional | Notificação identifica o webhook que a originou | TRANSCRICAO | [09:44] Sofia |
| PRD-FR-10 | `docs/PRD.md` | Requisito Funcional | Conteúdo essencial do pedido, sem itens | TRANSCRICAO | [09:43] Diego |
| PRD-FR-11 | `docs/PRD.md` | Requisito Funcional | Até 5 reenvios automáticos com intervalos crescentes | TRANSCRICAO | [09:17] Larissa |
| PRD-FR-11-EC | `docs/PRD.md` | Interpretação | Contagem de reenvios com falas conflitantes ("total 5 tentativas" no resumo) | TRANSCRICAO | [09:48] Larissa |
| PRD-FR-12 | `docs/PRD.md` | Requisito Funcional | Falhas definitivas vão para fila de falhas com motivo | TRANSCRICAO | [09:18] Diego |
| PRD-FR-13 | `docs/PRD.md` | Requisito Funcional | Administrador reenvia item da fila de falhas | TRANSCRICAO | [09:18] Diego |
| PRD-FR-14 | `docs/PRD.md` | Requisito Funcional | Registrar quem executou o reenvio manual | TRANSCRICAO | [09:36] Sofia |
| PRD-FR-15 | `docs/PRD.md` | Requisito Funcional | Histórico das últimas 100 entregas por webhook | TRANSCRICAO | [09:34] Marcos |
| PRD-NFR-01 | `docs/PRD.md` | Requisito Não Funcional | Latência < 10 s; mínima de até 2 s aceita | TRANSCRICAO | [09:10] Larissa |
| PRD-NFR-02 | `docs/PRD.md` | Requisito Não Funcional | Falha de notificação nunca afeta a mudança de status | TRANSCRICAO | [09:04] Bruno |
| PRD-NFR-03 | `docs/PRD.md` | Requisito Não Funcional | Toda mudança de status confirmada gera notificação | TRANSCRICAO | [09:40] Bruno |
| PRD-NFR-04 | `docs/PRD.md` | Requisito Não Funcional | Entrega at-least-once | TRANSCRICAO | [09:24] Diego |
| PRD-NFR-05 | `docs/PRD.md` | Restrição | Somente URLs HTTPS | TRANSCRICAO | [09:23] Sofia |
| PRD-NFR-06 | `docs/PRD.md` | Restrição | Limite de 64 KB, erro sem truncar | TRANSCRICAO | [09:24] Larissa |
| PRD-NFR-07 | `docs/PRD.md` | Requisito Não Funcional | Timeout de 10 s para resposta do cliente | TRANSCRICAO | [09:42] Diego |
| PRD-NFR-08 | `docs/PRD.md` | Requisito Não Funcional | Segredo exclusivo por webhook | TRANSCRICAO | [09:21] Sofia |
| PRD-NFR-09 | `docs/PRD.md` | Restrição | Ordem garantida só por pedido e enquanto não houver reenvio | TRANSCRICAO | [09:13] Larissa |
| PRD-NFR-10 | `docs/PRD.md` | Restrição | Reprocessamento restrito a ADMIN | TRANSCRICAO | [09:36] Sofia |
| PRD-NFR-11 | `docs/PRD.md` | Restrição | Sem infraestrutura nova | TRANSCRICAO | [09:07] Diego |
| PRD-NFR-12 | `docs/PRD.md` | Restrição | Revisão de segurança ≥ 2 dias úteis antes do lançamento | TRANSCRICAO | [09:46] Sofia |
| PRD-DEC-01 | `docs/PRD.md` | Trade-off | Notificação assíncrona registrada com a mudança de status (ADR-001) | TRANSCRICAO | [09:08] Larissa |
| PRD-DEC-02 | `docs/PRD.md` | Trade-off | Processo dedicado verificando a cada 2 s (ADR-002) | TRANSCRICAO | [09:10] Larissa |
| PRD-DEC-03 | `docs/PRD.md` | Trade-off | 5 reenvios em ~15 h + fila de falhas (ADR-003) | TRANSCRICAO | [09:17] Larissa |
| PRD-DEC-04 | `docs/PRD.md` | Trade-off | Assinatura com segredo por webhook (ADR-004) | TRANSCRICAO | [09:22] Sofia |
| PRD-DEC-05 | `docs/PRD.md` | Trade-off | Repetição possível; cliente deduplica (ADR-005) | TRANSCRICAO | [09:26] Larissa |
| PRD-DEC-06 | `docs/PRD.md` | Trade-off | Reuso dos padrões do OMS (ADR-006) | TRANSCRICAO | [09:30] Larissa |
| PRD-DEP-01 | `docs/PRD.md` | Dependência | Fluxo atual de mudança de status | CODIGO | `src/modules/orders/order.service.ts` |
| PRD-DEP-02 | `docs/PRD.md` | Dependência | Controle de acesso por papel (ADMIN) | CODIGO | `src/middlewares/auth.middleware.ts` |
| PRD-DEP-03 | `docs/PRD.md` | Dependência | Banco MySQL atual | TRANSCRICAO | [09:07] Diego |
| PRD-DEP-04 | `docs/PRD.md` | Dependência | Revisão de segurança da Sofia | TRANSCRICAO | [09:46] Sofia |
| PRD-DEP-05 | `docs/PRD.md` | Dependência | Documentação no portal do desenvolvedor | TRANSCRICAO | [09:26] Marcos |
| PRD-DEP-06 | `docs/PRD.md` | Dependência | Cliente implementa verificação e deduplicação | TRANSCRICAO | [09:25] Sofia |
| PRD-DEP-07 | `docs/PRD.md` | Dependência | Confirmação do prazo com os clientes | TRANSCRICAO | [09:47] Marcos |
| PRD-RISK-01 | `docs/PRD.md` | Risco | Perder a Atlas por atraso | TRANSCRICAO | [09:00] Marcos |
| PRD-RISK-02 | `docs/PRD.md` | Risco | Cliente não deduplica | TRANSCRICAO | [09:26] Marcos |
| PRD-RISK-03 | `docs/PRD.md` | Risco | Vazamento de segredo (já ocorreu) | TRANSCRICAO | [09:22] Diego |
| PRD-RISK-04 | `docs/PRD.md` | Risco | Cadastro público aceita papel ADMIN | CODIGO | `src/modules/auth/auth.schemas.ts` |
| PRD-RISK-05 | `docs/PRD.md` | Risco | Rajadas de notificações sobrecarregam o cliente | TRANSCRICAO | [09:38] Diego |
| PRD-RISK-06 | `docs/PRD.md` | Risco | Cliente fora do ar > ~15 h sem aviso | TRANSCRICAO | [09:37] Larissa |
| PRD-RISK-07 | `docs/PRD.md` | Risco | Qualquer autenticado gerencia webhooks de qualquer cliente | TRANSCRICAO | [09:37] Sofia |
| PRD-RISK-08 | `docs/PRD.md` | Risco | Um cliente lento atrasa as notificações dos outros | TRANSCRICAO | [09:42] Diego |
| PRD-AC-01 | `docs/PRD.md` | Critério de aceitação | Notificação de SHIPPED em < 10 s | TRANSCRICAO | [09:02] Marcos |
| PRD-AC-02 | `docs/PRD.md` | Critério de aceitação | Status fora da lista não notifica | TRANSCRICAO | [09:34] Bruno |
| PRD-AC-03 | `docs/PRD.md` | Critério de aceitação | 5 reenvios em ~15 h, depois fila de falhas | TRANSCRICAO | [09:17] Larissa |
| PRD-AC-04 | `docs/PRD.md` | Critério de aceitação | Replay por ADMIN com mesmo ID e autor registrado; OPERATOR negado | TRANSCRICAO | [09:36] Sofia |
| PRD-AC-05 | `docs/PRD.md` | Critério de aceitação | URL `http://` recusada | TRANSCRICAO | [09:23] Sofia |
| PRD-AC-06 | `docs/PRD.md` | Critério de aceitação | Segredo exibido só na criação/troca | TRANSCRICAO | [09:31] Marcos |
| PRD-AC-07 | `docs/PRD.md` | Critério de aceitação | Segredo antigo válido por 24 h após a troca | TRANSCRICAO | [09:21] Sofia |
| PRD-AC-08 | `docs/PRD.md` | Critério de aceitação | Histórico limitado às 100 últimas entregas | TRANSCRICAO | [09:34] Marcos |
| PRD-AC-09 | `docs/PRD.md` | Critério de aceitação | Falha de envio não afeta a mudança de status | TRANSCRICAO | [09:04] Bruno |
| PRD-AC-10 | `docs/PRD.md` | Critério de aceitação | Itens fora de escopo ausentes da entrega | TRANSCRICAO | [09:48] Larissa |
| PRD-TEST-01 | `docs/PRD.md` | Estratégia de testes | Testes de integração no padrão existente (Vitest + Supertest + MySQL) | CODIGO | `tests/orders.test.ts` |
| PRD-TEST-02 | `docs/PRD.md` | Estratégia de testes | Revisão de código de segurança antes do deploy | TRANSCRICAO | [09:46] Sofia |
| PRD-TEST-03 | `docs/PRD.md` | Estratégia de testes | Validação com os clientes via portal e confirmação | TRANSCRICAO | [09:49] Marcos |
| RFC-META-01 | `docs/RFC.md` | Metadado | Revisores = participantes; documento de design aberto pela Tech Lead | TRANSCRICAO | [09:50] Larissa |
| RFC-CTX-01 | `docs/RFC.md` | Contexto | Clientes B2B fazem polling; risco de churn da Atlas | TRANSCRICAO | [09:00] Marcos |
| RFC-CTX-02 | `docs/RFC.md` | Contexto | Transação de mudança de status já é pesada | TRANSCRICAO | [09:04] Bruno |
| RFC-CTX-03 | `docs/RFC.md` | Contexto | Mudança de status em transação única na máquina de estados | CODIGO | `src/modules/orders/order.status.ts` |
| RFC-CTX-04 | `docs/RFC.md` | Contexto | Prazo: "fim do trimestre" e depois "fim de novembro"; adotado o mais restritivo | TRANSCRICAO | [09:45] Marcos |
| RFC-PROP-01 | `docs/RFC.md` | Decisão | Evento gravado na outbox na mesma transação | TRANSCRICAO | [09:06] Diego |
| RFC-PROP-02 | `docs/RFC.md` | Decisão | Worker separado, polling 2 s, timeout 10 s | TRANSCRICAO | [09:09] Diego |
| RFC-PROP-03 | `docs/RFC.md` | Decisão | 5 reenvios 1m/5m/30m/2h/12h + DLQ + replay ADMIN | TRANSCRICAO | [09:17] Larissa |
| RFC-PROP-04 | `docs/RFC.md` | Decisão | HMAC-SHA256, secret por endpoint, rotação 24 h, HTTPS, 64 KB | TRANSCRICAO | [09:22] Sofia |
| RFC-PROP-05 | `docs/RFC.md` | Decisão | At-least-once com `X-Event-Id` | TRANSCRICAO | [09:26] Larissa |
| RFC-PROP-06 | `docs/RFC.md` | Requisito Funcional | Superfície de API: CRUD, histórico, replay | TRANSCRICAO | [09:33] Bruno |
| RFC-PROP-07 | `docs/RFC.md` | Decisão | Módulo igual aos outros, reuso de padrões | TRANSCRICAO | [09:30] Larissa |
| RFC-PROP-08 | `docs/RFC.md` | Requisito Funcional | Rotação da secret na superfície de API | TRANSCRICAO | [09:21] Sofia |
| RFC-ALT-01 | `docs/RFC.md` | Alternativa descartada | Disparo síncrono na transação de status | TRANSCRICAO | [09:04] Bruno |
| RFC-ALT-02 | `docs/RFC.md` | Alternativa descartada | Redis Streams / Redis Cluster | TRANSCRICAO | [09:07] Diego |
| RFC-ALT-03 | `docs/RFC.md` | Alternativa descartada | Trigger do banco acordando o worker | TRANSCRICAO | [09:09] Diego |
| RFC-ALT-04 | `docs/RFC.md` | Alternativa descartada | Worker dentro do processo da API | TRANSCRICAO | [09:11] Diego |
| RFC-ALT-05 | `docs/RFC.md` | Alternativa descartada | Retry indefinido / apenas 3 tentativas | TRANSCRICAO | [09:16] Diego |
| RFC-ALT-06 | `docs/RFC.md` | Alternativa descartada | Exactly-once | TRANSCRICAO | [09:25] Diego |
| RFC-ALT-07 | `docs/RFC.md` | Alternativa descartada | Secret global | TRANSCRICAO | [09:21] Sofia |
| RFC-OPEN-01 | `docs/RFC.md` | Questão em aberto | Rate limiting de saída: observar e decidir depois | TRANSCRICAO | [09:39] Larissa |
| RFC-OPEN-02 | `docs/RFC.md` | Questão em aberto | Aviso ao cliente quando o webhook falha (próxima fase) | TRANSCRICAO | [09:37] Larissa |
| RFC-OPEN-03 | `docs/RFC.md` | Questão em aberto | Escala para múltiplos workers | TRANSCRICAO | [09:13] Diego |
| RFC-OPEN-04 | `docs/RFC.md` | Questão em aberto | Endurecer permissão do CRUD | TRANSCRICAO | [09:37] Sofia |
| RFC-OPEN-05 | `docs/RFC.md` | Questão em aberto | Arquivamento da outbox | TRANSCRICAO | [09:08] Diego |
| RFC-OPEN-06 | `docs/RFC.md` | Interpretação | "5 tentativas" = 5 reenvios após o envio inicial (~14,6 h) | TRANSCRICAO | [09:17] Diego |
| RFC-OPEN-06-EC | `docs/RFC.md` | Interpretação | Evidência contrária: resumo final diz "total 5 tentativas" | TRANSCRICAO | [09:48] Larissa |
| RFC-OPEN-07 | `docs/RFC.md` | Interpretação | `customer_id` no body (escrita) e na query (listagem) | TRANSCRICAO | [09:32] Larissa |
| RFC-OPEN-08 | `docs/RFC.md` | Interpretação | Uma entrada de outbox por webhook, mesmo `X-Event-Id` | TRANSCRICAO | [09:34] Bruno |
| RFC-OPEN-09 | `docs/RFC.md` | Questão em aberto | Ordem por pedido se perde com retries; levar ao design review | TRANSCRICAO | [09:12] Diego |
| RFC-OPEN-10 | `docs/RFC.md` | Questão em aberto | Cliente lento segurando o worker: paralelizar entre pedidos ou aceitar e monitorar | TRANSCRICAO | [09:42] Diego |
| RFC-IMP-01 | `docs/RFC.md` | Impacto | Revisão de segurança ≥ 2 dias úteis antes do deploy | TRANSCRICAO | [09:46] Sofia |
| RFC-RISK-01 | `docs/RFC.md` | Risco | Cliente não deduplica | TRANSCRICAO | [09:26] Marcos |
| RFC-RISK-02 | `docs/RFC.md` | Risco | Mudanças de status concorrentes sem lock da linha | CODIGO | `src/modules/orders/order.service.ts` |
| RFC-RISK-03 | `docs/RFC.md` | Risco | Vazão limitada a um worker | TRANSCRICAO | [09:12] Diego |
| RFC-RISK-04 | `docs/RFC.md` | Risco | Cadastro público aceita ADMIN, enfraquecendo o replay | CODIGO | `src/modules/auth/auth.schemas.ts` |
| RFC-RISK-05 | `docs/RFC.md` | Risco | Sem vínculo usuário↔customer; CRUD aberto | TRANSCRICAO | [09:37] Sofia |
| RFC-RISK-06 | `docs/RFC.md` | Risco | Vazamento de secret pelo cliente | TRANSCRICAO | [09:22] Diego |
| RFC-RISK-07 | `docs/RFC.md` | Risco | Prazo de 3 sprints vs. fim de novembro | TRANSCRICAO | [09:46] Larissa |
| FDD-OT-01 | `docs/FDD.md` | Objetivo técnico | Primeira tentativa em ~2 s, abaixo de 10 s | TRANSCRICAO | [09:10] Larissa |
| FDD-OT-02 | `docs/FDD.md` | Objetivo técnico | Atomicidade entre status e evento | TRANSCRICAO | [09:06] Diego |
| FDD-OT-03 | `docs/FDD.md` | Objetivo técnico | Nenhuma chamada HTTP dentro da transação | TRANSCRICAO | [09:04] Bruno |
| FDD-OT-04 | `docs/FDD.md` | Objetivo técnico | Todo evento termina entregue ou na DLQ | TRANSCRICAO | [09:17] Larissa |
| FDD-OT-05 | `docs/FDD.md` | Objetivo técnico | Toda requisição assinada com HMAC-SHA256 | TRANSCRICAO | [09:22] Sofia |
| FDD-OT-06 | `docs/FDD.md` | Objetivo técnico | Nenhuma dependência nova | TRANSCRICAO | [09:29] Bruno |
| FDD-EXC-01 | `docs/FDD.md` | Exclusão | Webhooks de entrada | TRANSCRICAO | [09:02] Marcos |
| FDD-EXC-02 | `docs/FDD.md` | Exclusão | E-mail ao cliente | TRANSCRICAO | [09:37] Larissa |
| FDD-EXC-03 | `docs/FDD.md` | Exclusão | Rate limiting | TRANSCRICAO | [09:39] Larissa |
| FDD-EXC-04 | `docs/FDD.md` | Exclusão | Dashboard visual | TRANSCRICAO | [09:40] Larissa |
| FDD-EXC-05 | `docs/FDD.md` | Exclusão | Múltiplos workers / ordem global | TRANSCRICAO | [09:13] Diego |
| FDD-EXC-06 | `docs/FDD.md` | Exclusão | Arquivamento da outbox | TRANSCRICAO | [09:08] Diego |
| FDD-EXC-07 | `docs/FDD.md` | Exclusão | Restrição de papel no CRUD | TRANSCRICAO | [09:37] Sofia |
| FDD-EXC-08 | `docs/FDD.md` | Exclusão | Evento na criação do pedido (só `order.status_changed`) | TRANSCRICAO | [09:43] Diego |
| FDD-DADOS-01 | `docs/FDD.md` | Decisão | Configuração guarda url + secret + customer + ativo | TRANSCRICAO | [09:21] Bruno |
| FDD-DADOS-02 | `docs/FDD.md` | Decisão | Tabela `webhook_outbox` | TRANSCRICAO | [09:06] Diego |
| FDD-DADOS-03 | `docs/FDD.md` | Decisão | Índices em status e created_at; estados pendente/processando/falhou/entregue | TRANSCRICAO | [09:08] Diego |
| FDD-DADOS-04 | `docs/FDD.md` | Decisão | Tabela `webhook_dead_letter` com payload, motivo e timestamp | TRANSCRICAO | [09:18] Diego |
| FDD-DADOS-05 | `docs/FDD.md` | Decisão de desenho (derivada) | Tabela de histórico de entregas por tentativa | TRANSCRICAO | [09:34] Marcos |
| FDD-DADOS-06 | `docs/FDD.md` | Decisão | IDs UUID, padrão do projeto | TRANSCRICAO | [09:51] Larissa |
| FDD-DADOS-07 | `docs/FDD.md` | Decisão | Payload snapshot gravado na inserção | TRANSCRICAO | [09:52] Larissa |
| FDD-DADOS-08 | `docs/FDD.md` | Restrição | Padrão de models (uuid, `@@map`, coluna Json em `Customer.address`) | CODIGO | `prisma/schema.prisma` |
| FDD-DADOS-09 | `docs/FDD.md` | Interpretação | Uma linha de outbox por webhook interessado | TRANSCRICAO | [09:34] Bruno |
| FDD-FLUXO-01 | `docs/FDD.md` | Decisão | `publishWebhookEvent(tx, ...)` chamada no `changeStatus` | TRANSCRICAO | [09:41] Bruno |
| FDD-FLUXO-02 | `docs/FDD.md` | Decisão | Filtro de status na inserção | TRANSCRICAO | [09:34] Bruno |
| FDD-FLUXO-03 | `docs/FDD.md` | Restrição | Falha na outbox desfaz a mudança de status | TRANSCRICAO | [09:40] Bruno |
| FDD-FLUXO-04 | `docs/FDD.md` | Decisão | Entry point `src/worker.ts` e `npm run worker` | TRANSCRICAO | [09:11] Larissa |
| FDD-FLUXO-05 | `docs/FDD.md` | Decisão | Lógica do worker em arquivo do módulo | TRANSCRICAO | [09:28] Bruno |
| FDD-FLUXO-06 | `docs/FDD.md` | Decisão | Worker com PrismaClient próprio, mesma `DATABASE_URL` | TRANSCRICAO | [09:30] Bruno |
| FDD-FLUXO-07 | `docs/FDD.md` | Decisão | Polling a cada 2 s em lote pequeno | TRANSCRICAO | [09:09] Diego |
| FDD-FLUXO-08 | `docs/FDD.md` | Decisão | Single-worker, ordem por `created_at` | TRANSCRICAO | [09:12] Diego |
| FDD-FLUXO-09 | `docs/FDD.md` | Requisito Não Funcional | Timeout de 10 s = falha e retry | TRANSCRICAO | [09:42] Diego |
| FDD-FLUXO-10 | `docs/FDD.md` | Decisão de desenho (derivada) | Recuperação de `PROCESSING` no startup (seguro por at-least-once) | TRANSCRICAO | [09:24] Diego |
| FDD-FLUXO-11 | `docs/FDD.md` | Decisão de desenho (derivada) | Payload > 64 KB vai direto para DLQ, checado no worker | TRANSCRICAO | [09:24] Larissa |
| FDD-FLUXO-12 | `docs/FDD.md` | Decisão | Tabela de backoff 1m/5m/30m/2h/12h | TRANSCRICAO | [09:17] Diego |
| FDD-FLUXO-13 | `docs/FDD.md` | Decisão | Esgotadas as tentativas, move para DLQ | TRANSCRICAO | [09:15] Diego |
| FDD-FLUXO-14 | `docs/FDD.md` | Decisão | Replay recoloca na outbox como pendente | TRANSCRICAO | [09:18] Diego |
| FDD-FLUXO-15 | `docs/FDD.md` | Requisito Funcional | Log de auditoria de quem fez o replay | TRANSCRICAO | [09:36] Sofia |
| FDD-FLUXO-16 | `docs/FDD.md` | Decisão de desenho (derivada) | Replay duplicado retorna 409 | TRANSCRICAO | [09:25] Diego |
| FDD-FLUXO-17 | `docs/FDD.md` | Decisão | Rotação: anterior válida por 24 h | TRANSCRICAO | [09:21] Sofia |
| FDD-FLUXO-18 | `docs/FDD.md` | Decisão de desenho (derivada) | Dupla assinatura durante a convivência de secrets | TRANSCRICAO | [09:21] Sofia |
| FDD-FLUXO-19 | `docs/FDD.md` | Decisão de desenho (derivada) | Redirects não seguidos (envio só ao destino cadastrado) | TRANSCRICAO | [09:19] Sofia |
| FDD-CONTRATO-01 | `docs/FDD.md` | Contrato | `POST /api/v1/webhooks`; secret devolvida na criação | TRANSCRICAO | [09:31] Marcos |
| FDD-CONTRATO-02 | `docs/FDD.md` | Contrato | `GET /api/v1/webhooks?customerId=` | TRANSCRICAO | [09:33] Bruno |
| FDD-CONTRATO-03 | `docs/FDD.md` | Contrato | `PATCH /api/v1/webhooks/:id` | TRANSCRICAO | [09:33] Bruno |
| FDD-CONTRATO-04 | `docs/FDD.md` | Contrato | `DELETE /api/v1/webhooks/:id` | TRANSCRICAO | [09:33] Bruno |
| FDD-CONTRATO-05 | `docs/FDD.md` | Contrato | `GET /api/v1/webhooks/:id/deliveries` (últimas 100) | TRANSCRICAO | [09:34] Marcos |
| FDD-CONTRATO-06 | `docs/FDD.md` | Contrato (rota derivada) | `POST /api/v1/webhooks/:id/secret/rotate` | TRANSCRICAO | [09:21] Sofia |
| FDD-CONTRATO-07 | `docs/FDD.md` | Contrato | `POST /api/v1/admin/webhooks/dead-letter/:id/replay` (ADMIN) | TRANSCRICAO | [09:35] Diego |
| FDD-CONTRATO-08 | `docs/FDD.md` | Contrato | Headers `X-Event-Id`, `X-Signature`, `X-Timestamp`, `Content-Type` | TRANSCRICAO | [09:44] Diego |
| FDD-CONTRATO-09 | `docs/FDD.md` | Contrato | Header `X-Webhook-Id` | TRANSCRICAO | [09:44] Sofia |
| FDD-CONTRATO-10 | `docs/FDD.md` | Contrato | Payload JSON `order.status_changed` sem items | TRANSCRICAO | [09:43] Diego |
| FDD-CONTRATO-11 | `docs/FDD.md` | Restrição | Envelope de erro `{ error: { code, message, details? } }` | CODIGO | `src/middlewares/error.middleware.ts` |
| FDD-CONTRATO-12 | `docs/FDD.md` | Restrição | Formato paginado `{ data, pagination }` | CODIGO | `src/shared/http/response.ts` |
| FDD-CONTRATO-13 | `docs/FDD.md` | Restrição | API de gestão em camelCase (ex.: `toStatus`) | CODIGO | `src/modules/orders/order.schemas.ts` |
| FDD-ERRO-01 | `docs/FDD.md` | Código de erro | `WEBHOOK_NOT_FOUND` (404) | TRANSCRICAO | [09:28] Bruno |
| FDD-ERRO-02 | `docs/FDD.md` | Código de erro | `WEBHOOK_INVALID_URL` (400) | TRANSCRICAO | [09:28] Bruno |
| FDD-ERRO-03 | `docs/FDD.md` | Código de erro | `WEBHOOK_CUSTOMER_NOT_FOUND` (404), prefixo do módulo | TRANSCRICAO | [09:29] Larissa |
| FDD-ERRO-04 | `docs/FDD.md` | Código de erro | `WEBHOOK_DEAD_LETTER_NOT_FOUND` (404) | TRANSCRICAO | [09:29] Larissa |
| FDD-ERRO-05 | `docs/FDD.md` | Código de erro | `WEBHOOK_DEAD_LETTER_ALREADY_REPLAYED` (409) | TRANSCRICAO | [09:29] Larissa |
| FDD-ERRO-06 | `docs/FDD.md` | Código de erro | `WEBHOOK_PAYLOAD_TOO_LARGE` (motivo na DLQ) | TRANSCRICAO | [09:24] Larissa |
| FDD-ERRO-07 | `docs/FDD.md` | Código de erro | `WEBHOOK_DELIVERY_TIMEOUT` | TRANSCRICAO | [09:42] Diego |
| FDD-ERRO-08 | `docs/FDD.md` | Código de erro | `WEBHOOK_DELIVERY_HTTP_ERROR` / `WEBHOOK_DELIVERY_NETWORK_ERROR` | TRANSCRICAO | [09:15] Diego |
| FDD-ERRO-09 | `docs/FDD.md` | Código de erro | `WEBHOOK_MAX_ATTEMPTS_EXCEEDED` | TRANSCRICAO | [09:17] Larissa |
| FDD-ERRO-10 | `docs/FDD.md` | Restrição | `NotFoundError` fixa `NOT_FOUND` → 404 do módulo usam `AppError` | CODIGO | `src/shared/errors/http-errors.ts` |
| FDD-ERRO-11 | `docs/FDD.md` | Restrição | `validate` converte Zod em `VALIDATION_ERROR` → HTTPS checado no service | CODIGO | `src/middlewares/validate.middleware.ts` |
| FDD-ERRO-12 | `docs/FDD.md` | Decisão | `WEBHOOK_SECRET_REQUIRED` excluído: secret sempre gerada pelo servidor | TRANSCRICAO | [09:31] Marcos |
| FDD-RES-01 | `docs/FDD.md` | Decisão | Shutdown do worker no padrão SIGINT/SIGTERM do servidor | CODIGO | `src/server.ts` |
| FDD-RES-02 | `docs/FDD.md` | Decisão de desenho (derivada) | Cliente fora do ar não bloqueia os demais (reagendamento por linha) | TRANSCRICAO | [09:04] Bruno |
| FDD-RES-03 | `docs/FDD.md` | Requisito Não Funcional | Reinício da API não afeta entregas | TRANSCRICAO | [09:11] Diego |
| FDD-OBS-01 | `docs/FDD.md` | Observabilidade | Logs estruturados com o Pino existente, sem lib nova | TRANSCRICAO | [09:29] Bruno |
| FDD-OBS-02 | `docs/FDD.md` | Observabilidade | Log de auditoria `webhook_dead_letter_replayed` com `userId` | TRANSCRICAO | [09:36] Sofia |
| FDD-OBS-03 | `docs/FDD.md` | Observabilidade | Métrica de latência p95 < 10 s | TRANSCRICAO | [09:02] Marcos |
| FDD-OBS-04 | `docs/FDD.md` | Observabilidade | Secrets em `redactPaths` do logger | CODIGO | `src/shared/logger/index.ts` |
| FDD-OBS-05 | `docs/FDD.md` | Observabilidade | Correlação `X-Request-Id` → `eventId` → entregas | CODIGO | `src/middlewares/request-logger.middleware.ts` |
| FDD-INT-01 | `docs/FDD.md` | Integração | `changeStatus` chama `publishWebhookEvent(tx, ...)` após o histórico | CODIGO | `src/modules/orders/order.service.ts` |
| FDD-INT-02 | `docs/FDD.md` | Integração | Controller passa `req.id` ao service | CODIGO | `src/modules/orders/order.controller.ts` |
| FDD-INT-03 | `docs/FDD.md` | Integração | Máquina de estados inalterada; enum `OrderStatus` em `events` | CODIGO | `src/modules/orders/order.status.ts` |
| FDD-INT-04 | `docs/FDD.md` | Integração | Wiring manual em `buildControllers` | CODIGO | `src/app.ts` |
| FDD-INT-05 | `docs/FDD.md` | Integração | Registro de `/webhooks` e `/admin/webhooks` | CODIGO | `src/routes/index.ts` |
| FDD-INT-06 | `docs/FDD.md` | Integração | `authenticate` + `requireRole('ADMIN')` no replay | CODIGO | `src/middlewares/auth.middleware.ts` |
| FDD-INT-07 | `docs/FDD.md` | Integração | Reuso de `AppError` | CODIGO | `src/shared/errors/app-error.ts` |
| FDD-INT-08 | `docs/FDD.md` | Integração | Reuso de `BadRequestError`, `ConflictError` | CODIGO | `src/shared/errors/http-errors.ts` |
| FDD-INT-09 | `docs/FDD.md` | Integração | Error middleware sem alteração | CODIGO | `src/middlewares/error.middleware.ts` |
| FDD-INT-10 | `docs/FDD.md` | Integração | Schemas Zod via `validate` | CODIGO | `src/middlewares/validate.middleware.ts` |
| FDD-INT-11 | `docs/FDD.md` | Integração | Logger existente + redaction de secrets | CODIGO | `src/shared/logger/index.ts` |
| FDD-INT-12 | `docs/FDD.md` | Integração | `paginated()` na listagem | CODIGO | `src/shared/http/response.ts` |
| FDD-INT-13 | `docs/FDD.md` | Integração | Worker importa o `prisma` exportado (instância própria por processo) | CODIGO | `src/config/database.ts` |
| FDD-INT-19 | `docs/FDD.md` | Restrição | Worker herda a exigência de `JWT_SECRET` ao importar o `env` | CODIGO | `src/config/env.ts` |
| FDD-OBS-06 | `docs/FDD.md` | Restrição | Heartbeat em `info`: `LOG_LEVEL` padrão é `info`, `debug` não seria emitido | CODIGO | `src/config/env.ts` |
| FDD-RISK-10 | `docs/FDD.md` | Risco | Cliente lento segura o worker sequencial (até 10 s por entrega) | TRANSCRICAO | [09:42] Diego |
| FDD-RISK-11 | `docs/FDD.md` | Risco | Mesmo problema de cliente lento travando os outros, agora no worker | TRANSCRICAO | [09:04] Bruno |
| FDD-FLUXO-20 | `docs/FDD.md` | Decisão de desenho (derivada) | `requestId` como 5º parâmetro de `publishWebhookEvent` | TRANSCRICAO | [09:41] Bruno |
| FDD-INT-20 | `docs/FDD.md` | Interpretação | Histórico "últimos 100" contado em tentativas, não em eventos | TRANSCRICAO | [09:34] Marcos |
| FDD-ERRO-13 | `docs/FDD.md` | Restrição | Códigos citados na reunião: `WEBHOOK_NOT_FOUND`, `WEBHOOK_INVALID_URL`; demais são [D] | TRANSCRICAO | [09:28] Bruno |
| RFC-RISK-08 | `docs/RFC.md` | Risco | Cliente lento segura o worker | TRANSCRICAO | [09:04] Bruno |
| FDD-INT-14 | `docs/FDD.md` | Integração | Novas variáveis no `envSchema` | CODIGO | `src/config/env.ts` |
| FDD-INT-15 | `docs/FDD.md` | Integração | `src/server.ts` como modelo do `src/worker.ts` | CODIGO | `src/server.ts` |
| FDD-INT-16 | `docs/FDD.md` | Integração | Novos models e relação em `Customer` | CODIGO | `prisma/schema.prisma` |
| FDD-INT-17 | `docs/FDD.md` | Integração | Scripts `worker` / `worker:dev` | CODIGO | `package.json` |
| FDD-INT-18 | `docs/FDD.md` | Integração | Limpeza das novas tabelas no `beforeEach` antes de `customer` e `user` (FK `replayedById`) | CODIGO | `tests/setup.ts` |
| FDD-DEP-01 | `docs/FDD.md` | Dependência | MySQL 8 já usado | CODIGO | `docker-compose.yml` |
| FDD-DEP-02 | `docs/FDD.md` | Dependência | Node ≥ 20 (`fetch`, `crypto` nativos) | CODIGO | `package.json` |
| FDD-DEP-03 | `docs/FDD.md` | Dependência | Revisão de segurança antes do deploy | TRANSCRICAO | [09:46] Sofia |
| FDD-RISK-01 | `docs/FDD.md` | Risco | Retries podem inverter a ordem por pedido | TRANSCRICAO | [09:12] Diego |
| FDD-RISK-02 | `docs/FDD.md` | Risco | `changeStatus` sem lock de linha | CODIGO | `src/modules/orders/order.service.ts` |
| FDD-RISK-03 | `docs/FDD.md` | Risco | Secret em texto puro para poder assinar | TRANSCRICAO | [09:46] Sofia |
| FDD-RISK-04 | `docs/FDD.md` | Risco | Cadastro público aceita ADMIN | CODIGO | `src/modules/auth/auth.schemas.ts` |
| FDD-RISK-05 | `docs/FDD.md` | Risco | CRUD aberto a qualquer autenticado | TRANSCRICAO | [09:37] Sofia |
| FDD-RISK-06 | `docs/FDD.md` | Risco | `X-Timestamp` fora da assinatura (HMAC só do corpo) | TRANSCRICAO | [09:22] Sofia |
| FDD-RISK-07 | `docs/FDD.md` | Risco | Crescimento das tabelas sem arquivamento | TRANSCRICAO | [09:08] Diego |
| FDD-RISK-08 | `docs/FDD.md` | Risco | Worker único parado | TRANSCRICAO | [09:11] Diego |
| FDD-RISK-09 | `docs/FDD.md` | Risco | `tests/setup.ts` falha por FK | CODIGO | `tests/setup.ts` |
| FDD-AC-01 | `docs/FDD.md` | Critério de aceite técnico | N linhas para N webhooks interessados, mesmo `eventId` | TRANSCRICAO | [09:34] Bruno |
| FDD-AC-02 | `docs/FDD.md` | Critério de aceite técnico | Sem webhook interessado, nenhuma linha | TRANSCRICAO | [09:34] Bruno |
| FDD-AC-03 | `docs/FDD.md` | Critério de aceite técnico | Falha na outbox desfaz pedido, histórico e estoque | TRANSCRICAO | [09:40] Bruno |
| FDD-AC-04 | `docs/FDD.md` | Critério de aceite técnico | Entrega < 10 s | TRANSCRICAO | [09:02] Marcos |
| FDD-AC-05 | `docs/FDD.md` | Critério de aceite técnico | 5 headers e assinatura válida | TRANSCRICAO | [09:44] Diego |
| FDD-AC-06 | `docs/FDD.md` | Critério de aceite técnico | Sequência de backoff e DLQ após 5º reenvio | TRANSCRICAO | [09:17] Larissa |
| FDD-AC-07 | `docs/FDD.md` | Critério de aceite técnico | Timeout de 10 s conta como falha | TRANSCRICAO | [09:42] Diego |
| FDD-AC-08 | `docs/FDD.md` | Critério de aceite técnico | > 64 KB vai para DLQ sem chamada | TRANSCRICAO | [09:24] Larissa |
| FDD-AC-09 | `docs/FDD.md` | Critério de aceite técnico | Replay: 202 ADMIN, 403 OPERATOR, 409 repetido, log com `userId` | TRANSCRICAO | [09:36] Sofia |
| FDD-AC-10 | `docs/FDD.md` | Critério de aceite técnico | URL `http://` → 400 `WEBHOOK_INVALID_URL` | TRANSCRICAO | [09:23] Sofia |
| FDD-AC-11 | `docs/FDD.md` | Critério de aceite técnico | Secret só em criação/rotação, nunca em log | TRANSCRICAO | [09:31] Marcos |
| FDD-AC-12 | `docs/FDD.md` | Critério de aceite técnico | Duas assinaturas por 24 h após rotação | TRANSCRICAO | [09:21] Sofia |
| FDD-AC-13 | `docs/FDD.md` | Critério de aceite técnico | Histórico com no máximo 100 itens | TRANSCRICAO | [09:34] Marcos |
| FDD-AC-14 | `docs/FDD.md` | Critério de aceite técnico | Worker reiniciado reprocessa sem perda | TRANSCRICAO | [09:24] Diego |
| FDD-AC-15 | `docs/FDD.md` | Critério de aceite técnico | Suíte de testes existente continua passando | CODIGO | `tests/orders.test.ts` |
| ADR-001 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Decisão | Outbox no MySQL existente, mesma transação | TRANSCRICAO | [09:08] Larissa |
| ADR-001-ALT-01 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Alternativa descartada | Disparo síncrono | TRANSCRICAO | [09:06] Diego |
| ADR-001-ALT-02 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Alternativa descartada | Redis Streams / Cluster (overengineering) | TRANSCRICAO | [09:07] Diego |
| ADR-001-CTX-01 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Contexto | Transação de status onde o evento será gravado | CODIGO | `src/modules/orders/order.service.ts` |
| ADR-001-CONS-01 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Trade-off | Consistência e isolamento de falhas em troca de latência | TRANSCRICAO | [09:06] Diego |
| ADR-001-CONS-02 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Trade-off | Eventos acumulados podem deixar o worker lento; mitigado com índices e lote | TRANSCRICAO | [09:07] Bruno |
| ADR-001-CONS-03 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Consequência | Transação de status não depende da rede nem do cliente | TRANSCRICAO | [09:04] Bruno |
| ADR-001-CONS-04 | `docs/adrs/ADR-001-outbox-no-mysql.md` | Consequência | Tabela cresce até existir arquivamento (adiado) | TRANSCRICAO | [09:08] Diego |
| ADR-002 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Decisão | Worker separado, polling 2 s | TRANSCRICAO | [09:10] Larissa |
| ADR-002-ALT-01 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Alternativa descartada | Trigger do banco (MySQL sem NOTIFY/LISTEN) | TRANSCRICAO | [09:09] Diego |
| ADR-002-ALT-02 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Alternativa descartada | Worker no processo da API | TRANSCRICAO | [09:11] Diego |
| ADR-002-CONS-01 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Trade-off | Sem ordem global; ordem por pedido só com single-worker | TRANSCRICAO | [09:13] Larissa |
| ADR-002-CONS-02 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Trade-off | Escala para vários workers adiada | TRANSCRICAO | [09:13] Diego |
| ADR-002-CONS-03 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Risco | Retry pode inverter a ordem por pedido; questão para o design review | TRANSCRICAO | [09:50] Larissa |
| ADR-002-CONS-04 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Consequência | Entregas continuam durante reinícios da API | TRANSCRICAO | [09:11] Diego |
| ADR-002-CONS-05 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Consequência | Latência mínima de 2 s aceita explicitamente | TRANSCRICAO | [09:10] Larissa |
| ADR-002-CONS-06 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Consequência | Cliente lento atrasa os demais no worker sequencial | TRANSCRICAO | [09:04] Bruno |
| ADR-002-CTX-01 | `docs/adrs/ADR-002-worker-separado-com-polling.md` | Contexto | Único entry point atual é o servidor HTTP | CODIGO | `src/server.ts` |
| ADR-003 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Decisão | 5 reenvios, backoff 1m/5m/30m/2h/12h | TRANSCRICAO | [09:17] Larissa |
| ADR-003-INT-01 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Interpretação | 5 reenvios após o envio inicial (~14,6 h) | TRANSCRICAO | [09:17] Diego |
| ADR-003-INT-02 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Interpretação | Evidência contrária: "total 5 tentativas" no resumo, confirmado por todos | TRANSCRICAO | [09:48] Larissa |
| ADR-003-DEC-02 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Decisão | DLQ em tabela separada | TRANSCRICAO | [09:18] Diego |
| ADR-003-DEC-03 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Decisão | Replay manual restrito a ADMIN via `requireRole` | TRANSCRICAO | [09:36] Larissa |
| ADR-003-ALT-01 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Alternativa descartada | Retry indefinido | TRANSCRICAO | [09:15] Diego |
| ADR-003-ALT-02 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Alternativa descartada | Apenas 3 tentativas | TRANSCRICAO | [09:16] Bruno |
| ADR-003-ALT-03 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Alternativa descartada | "Falhou" na própria outbox | TRANSCRICAO | [09:17] Larissa |
| ADR-003-CONS-01 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Trade-off | Falhas > 15 h aceitas como problema do cliente | TRANSCRICAO | [09:17] Marcos |
| ADR-003-CONS-02 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Consequência | Nenhum evento se perde: a DLQ guarda payload e motivo | TRANSCRICAO | [09:18] Diego |
| ADR-003-CONS-03 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Consequência | Sem aviso proativo ao cliente; e-mail adiado | TRANSCRICAO | [09:37] Larissa |
| ADR-003-CONS-04 | `docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md` | Consequência | Replay restrito a ADMIN e auditável | TRANSCRICAO | [09:36] Sofia |
| ADR-004 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Decisão | HMAC-SHA256 sobre o corpo, secret por endpoint, rotação 24 h | TRANSCRICAO | [09:22] Sofia |
| ADR-004-DEC-02 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Decisão | SHA-256 como algoritmo padrão de mercado | TRANSCRICAO | [09:20] Sofia |
| ADR-004-ALT-01 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Alternativa descartada | Secret global | TRANSCRICAO | [09:21] Sofia |
| ADR-004-DEC-03 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Requisito Não Funcional | Somente HTTPS (requisito relacionado, não decisão arquitetural) | TRANSCRICAO | [09:23] Sofia |
| ADR-004-DEC-04 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Decisão | Secret gerada pela plataforma | TRANSCRICAO | [09:31] Marcos |
| ADR-004-CONS-01 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Consequência | Vazamento contido a um endpoint e resolvido por rotação | TRANSCRICAO | [09:22] Diego |
| ADR-004-CONS-02 | `docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md` | Consequência | Secrets exigem revisão de segurança de pelo menos 2 dias úteis | TRANSCRICAO | [09:46] Sofia |
| ADR-005 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Decisão | At-least-once com `X-Event-Id` | TRANSCRICAO | [09:26] Larissa |
| ADR-005-DEC-02 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Decisão | UUID gerado na entrada da outbox | TRANSCRICAO | [09:25] Diego |
| ADR-005-ALT-01 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Alternativa descartada | Exactly-once | TRANSCRICAO | [09:25] Diego |
| ADR-005-ALT-02 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Alternativa descartada | Stripe e GitHub como referência de at-least-once | TRANSCRICAO | [09:25] Diego |
| ADR-005-INT-01 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Interpretação | Mesmo `X-Event-Id` em todas as entregas do evento; distinguidas por `X-Webhook-Id` | TRANSCRICAO | [09:44] Sofia |
| ADR-005-CONS-01 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Trade-off | Responsabilidade de dedup transferida ao cliente | TRANSCRICAO | [09:25] Sofia |
| ADR-005-CONS-02 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Consequência | Responsabilidade do cliente destacada no portal | TRANSCRICAO | [09:26] Marcos |
| ADR-005-CONS-03 | `docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md` | Consequência | Timeout de 10 s pode gerar reenvio de evento já processado | TRANSCRICAO | [09:42] Diego |
| ADR-006 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Decisão | Reuso máximo: AppError, Pino, error middleware, módulos, Zod | TRANSCRICAO | [09:30] Larissa |
| ADR-006-DEC-02 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Decisão | Prefixo `WEBHOOK_` nos códigos de erro | TRANSCRICAO | [09:29] Larissa |
| ADR-006-DEC-03 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Decisão | Módulo em `src/modules/webhooks` | TRANSCRICAO | [09:27] Bruno |
| ADR-006-DEC-04 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Decisão | Função recebendo `tx` em vez de injetar repositório | TRANSCRICAO | [09:41] Diego |
| ADR-006-CONS-01 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Trade-off | Observabilidade só com logs e tabelas, sem biblioteca nova | TRANSCRICAO | [09:29] Bruno |
| ADR-006-CONS-02 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Consequência | Erros `WEBHOOK_*` tratados pelo middleware sem alteração | TRANSCRICAO | [09:29] Bruno |
| ADR-006-CONS-03 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Consequência | Replay herda a fragilidade do cadastro público aceitar ADMIN | CODIGO | `src/modules/auth/auth.schemas.ts` |
| ADR-006-CONS-04 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Consequência | Worker reutiliza os padrões com instância própria do banco | TRANSCRICAO | [09:30] Bruno |
| ADR-006-COD-01 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Restrição | Hierarquia `AppError` e classes de erro existentes | CODIGO | `src/shared/errors/http-errors.ts` |
| ADR-006-COD-02 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Restrição | Error middleware centralizado | CODIGO | `src/middlewares/error.middleware.ts` |
| ADR-006-COD-03 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Restrição | `requireRole` usado numa única rota hoje | CODIGO | `src/modules/users/user.routes.ts` |
| ADR-006-COD-04 | `docs/adrs/ADR-006-reuso-dos-padroes-existentes.md` | Restrição | Logger Pino existente | CODIGO | `src/shared/logger/index.ts` |
