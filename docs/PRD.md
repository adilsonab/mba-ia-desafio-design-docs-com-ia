# PRD — Sistema de Webhooks de Notificação de Pedidos

| Campo | Valor |
| --- | --- |
| **Autor** | Adilson Barbosa |
| **Product Manager** | Marcos |
| **Status** | Escopo aprovado na reunião técnica (resumo final em [09:48] Larissa); desenho técnico em revisão antes do início da implementação ([09:50] Larissa) |
| **Data** | 02-11-2026 |
| **Documentos relacionados** | [RFC](RFC.md) · [FDD](FDD.md) · [ADRs](adrs/README.md) · [Tracker](TRACKER.md) |

## 1. Resumo e contexto

Os clientes B2B do OMS passarão a receber **notificações automáticas (webhooks) sempre que o status de um pedido deles mudar**, sem precisar consultar a API periodicamente. Cada cliente cadastra um ou mais endereços HTTPS e escolhe quais status quer receber (por exemplo, só "enviado" e "entregue"). A plataforma entrega cada notificação normalmente em segundos, assinada digitalmente, com novas tentativas automáticas se o cliente estiver fora do ar.

A feature nasce de um pedido formal de três clientes B2B: Atlas Comercial, MaxDistribuição e Nova Cargo ([09:00] Marcos). O OMS ainda não tem nenhum mecanismo de notificação externa.

## 2. Problema e motivação

- **Hoje os clientes fazem polling.** Eles chamam `GET /orders` de tempos em tempos para descobrir se algo mudou, e isso deixa a integração **lenta e cara** para eles ([09:00] Marcos).
- **Risco comercial concreto.** A Atlas Comercial sinalizou que pode **migrar para um concorrente** se a solução não for entregue no prazo ([09:00] Marcos). O prazo pedido é **fim de novembro** ([09:45] Marcos).
- **Expectativa de "tempo real".** Para os clientes, qualquer atualização em **menos de 10 segundos** já é tempo real. O que importa é não precisar ficar consultando ([09:02] Marcos).

## 3. Público-alvo e cenários de uso

| Persona | Quem é | O que precisa |
| --- | --- | --- |
| **Integrador do cliente B2B** | Desenvolvedor dos sistemas da Atlas, MaxDistribuição, Nova Cargo e futuros clientes | Receber eventos confiáveis e verificáveis; configurar e diagnosticar a própria integração |
| **Usuário que representa o cliente** | Usuário do OMS que acessa a API em nome do cliente ([09:32] Marcos) | Cadastrar, editar e remover webhooks e consultar o histórico de entregas |
| **Administrador da plataforma** | Usuário com papel ADMIN | Reprocessar notificações que falharam definitivamente, com rastro de auditoria ([09:36] Sofia) |
| **PM** | Marcos | Documentar a integração no portal do desenvolvedor ([09:26] Marcos, [09:40] Marcos) |

**Cenários** (ilustrativos: as situações vêm das falas citadas; os clientes não foram nomeados nelas):

1. **Acompanhar entregas.** Um cliente cadastra um webhook só para "SHIPPED" e "DELIVERED". Quando um pedido dele é despachado, o sistema dele recebe a notificação, sem consultar a API ([09:33] Marcos).
2. **Cliente em manutenção.** O endpoint de um cliente fica 2 horas fora do ar numa manutenção planejada, como já aconteceu com um cliente da plataforma. As notificações são reenviadas automaticamente e chegam quando o sistema volta ([09:16] Diego).
3. **Cliente fora do ar por muito tempo.** O endpoint de um cliente fica indisponível por mais de ~15 h. As notificações vão para uma fila de falhas. Quando o problema é resolvido, um administrador as reenvia ([09:17] Marcos, [09:18] Diego).
4. **Notificação repetida.** Um reenvio faz o cliente receber o mesmo evento duas vezes. Ele reconhece a repetição pelo identificador único do evento e a ignora ([09:25] Diego).
5. **Segredo vazado.** O cliente vaza o segredo de assinatura num log. Ele gera um novo segredo pela API, e o antigo continua válido por 24 h para dar tempo de migrar ([09:21] Sofia, [09:22] Diego).
6. **Diagnóstico.** O integrador vê, nas últimas 100 entregas, quais falharam, o que foi enviado, o que o sistema dele respondeu e quanto tempo levou ([09:34] Marcos).

## 4. Objetivos e métricas de sucesso

| # | Objetivo | Métrica | Meta | Origem |
| --- | --- | --- | --- | --- |
| O-1 | Notificar em "tempo real" | Tempo entre a mudança de status e a primeira tentativa de entrega | **p95 < 10 s** (ver o risco "cliente lento" na seção 10) | [09:02] Marcos, [09:10] Larissa |
| O-2 | Não perder nenhuma notificação | Mudanças de status que deveriam notificar e não geraram evento | **0** | [09:06] Diego, [09:40] Bruno |
| O-3 | Tolerar indisponibilidade do cliente | Janela de reenvio automático antes da fila de falhas | **~15 h** (5 reenvios) | [09:17] Diego, [09:17] Marcos |
| O-4 | Atender os clientes solicitantes no prazo | Clientes solicitantes com webhook em produção | **3 de 3** (Atlas, MaxDistribuição, Nova Cargo) até **fim de novembro** | [09:00] Marcos, [09:45] Marcos |
| O-5 | Reter a conta em risco | Atlas Comercial ativa após a entrega | **Sem migração para concorrente** | [09:00] Marcos |

O-4 combina o pedido dos três clientes com o prazo da Atlas; a meta "3 de 3" é a leitura deste PRD para esse pedido. A redução do polling em `GET /orders` é o efeito esperado ([09:00] Marcos), mas a reunião não fixou meta numérica, então ela será acompanhada sem alvo.

## 5. Escopo

### 5.1 Incluso

- Cadastro, edição, listagem e remoção de webhooks por cliente, com escolha dos status de interesse.
- Notificação automática de **mudanças de status de pedido**.
- Assinatura digital de cada notificação, com segredo exclusivo por webhook e troca de segredo sem interrupção.
- Reenvio automático com intervalos crescentes e fila de falhas definitivas.
- Reprocessamento manual da fila de falhas por administradores, com auditoria.
- Histórico das últimas 100 entregas por webhook.

### 5.2 Fora de escopo

| Item | Situação | Origem |
| --- | --- | --- |
| **Aviso por e-mail** ao cliente quando o webhook falha repetidamente | **Adiado** para uma próxima fase, depois de medir o impacto | [09:37] Marcos, [09:37] Larissa |
| **Dashboard visual** para o cliente ver seus webhooks | **Descartado** nesta fase; é projeto separado do time de frontend | [09:39] Marcos, [09:40] Larissa |
| **Limite de taxa de envio** (rate limiting) por cliente | **Adiado**: observar e decidir depois | [09:38] Diego, [09:39] Larissa |
| **Webhooks de entrada** (cliente enviando para o OMS) | **Fora do escopo**: o cliente só recebe | [09:02] Marcos |
| **Garantia de ordem global** entre eventos | **Não oferecida**; os clientes não pediram | [09:13] Larissa, [09:14] Marcos |
| **Entrega exatamente uma vez** (exactly-once) | **Descartado**; o cliente deduplica | [09:25] Diego |
| **Restrição de papel** no cadastro de webhooks | **Adiado**: "mais pra frente a gente pode endurecer" | [09:37] Sofia |
| **Arquivamento** das notificações já entregues (~30 dias) | **Fora desta feature**. Não afeta o histórico de entregas consultável pelo cliente | [09:08] Diego |

## 6. Requisitos funcionais

| ID | Requisito | Origem |
| --- | --- | --- |
| PRD-FR-01 | O sistema deve notificar o cliente, via HTTP, sempre que o status de um pedido dele mudar | [09:00] Marcos, [09:03] Sofia |
| PRD-FR-02 | O usuário autenticado deve poder **cadastrar** um webhook informando o cliente, a URL e a lista de status de interesse | [09:31] Marcos, [09:32] Larissa |
| PRD-FR-03 | O segredo de assinatura deve ser **gerado pela plataforma** e mostrado ao usuário na criação | [09:31] Marcos |
| PRD-FR-04 | O usuário deve poder **editar**, **remover** e **listar** os webhooks de um cliente | [09:33] Bruno |
| PRD-FR-05 | Cada webhook deve receber **apenas os status que escolheu** | [09:33] Marcos, [09:34] Bruno |
| PRD-FR-06 | O usuário deve poder **trocar o segredo** de um webhook; o anterior continua válido por **24 h** | [09:21] Sofia |
| PRD-FR-07 | Cada notificação deve ser **assinada** para o cliente comprovar origem e integridade | [09:19] Sofia, [09:22] Sofia |
| PRD-FR-08 | Cada notificação deve trazer um **identificador único do evento** para o cliente reconhecer repetições | [09:25] Diego, [09:26] Larissa |
| PRD-FR-09 | Cada notificação deve identificar **qual webhook cadastrado** a originou | [09:44] Sofia |
| PRD-FR-10 | A notificação deve conter os dados essenciais do pedido e da mudança (pedido, número, status anterior e novo, cliente, valor total, momento), **sem os itens** do pedido | [09:43] Diego |
| PRD-FR-11 | Notificações que falharem devem ser **reenviadas automaticamente** até 5 vezes, com intervalos crescentes. *A contagem (5 reenvios além do envio inicial, ou 5 envios no total) tem falas conflitantes na reunião e será confirmada no design review; ver [RFC](RFC.md), questão 6* | [09:15] Diego, [09:17] Larissa, [09:48] Larissa |
| PRD-FR-12 | Esgotados os reenvios, a notificação deve ir para uma **fila de falhas** com o motivo | [09:15] Diego, [09:18] Diego |
| PRD-FR-13 | Um **administrador** deve poder reenviar manualmente um item da fila de falhas | [09:18] Diego, [09:36] Larissa |
| PRD-FR-14 | O sistema deve registrar **quem** executou cada reenvio manual | [09:36] Sofia |
| PRD-FR-15 | O usuário deve poder consultar as **últimas 100 entregas** de um webhook, com sucesso ou falha, conteúdo enviado, resposta e tempo de resposta. *Se "100" conta tentativas ou eventos é uma interpretação a confirmar; ver [FDD](FDD.md), histórico de entregas* | [09:34] Marcos |

## 7. Requisitos não funcionais

| ID | Requisito | Origem |
| --- | --- | --- |
| PRD-NFR-01 | Latência de notificação **< 10 s**; latência mínima de até 2 s aceita | [09:02] Marcos, [09:10] Larissa |
| PRD-NFR-02 | Uma notificação lenta ou falha **nunca** pode atrasar ou desfazer a mudança de status do pedido | [09:04] Bruno |
| PRD-NFR-03 | Toda mudança de status confirmada que deva notificar **gera** a notificação, sem exceção | [09:40] Bruno, [09:41] Diego |
| PRD-NFR-04 | Garantia de entrega **at-least-once**: pode haver repetição, nunca perda silenciosa | [09:24] Diego |
| PRD-NFR-05 | URLs de webhook devem ser **HTTPS**; HTTP é recusado | [09:23] Sofia |
| PRD-NFR-06 | Notificações acima de **64 KB** não são enviadas (erro, sem truncar) | [09:23] Sofia, [09:24] Larissa |
| PRD-NFR-07 | O cliente tem **10 s** para responder a cada notificação | [09:42] Diego |
| PRD-NFR-08 | Segredo **exclusivo por webhook**; o vazamento de um não afeta os outros | [09:21] Sofia |
| PRD-NFR-09 | Ordem garantida apenas **por pedido**, e só enquanto não houver reenvio: uma notificação em reenvio pode ser ultrapassada pela seguinte do mesmo pedido (em discussão no design review; [RFC](RFC.md), questão 9) | [09:12] Diego, [09:13] Larissa |
| PRD-NFR-10 | Reprocessamento da fila de falhas restrito ao papel **ADMIN** | [09:36] Sofia |
| PRD-NFR-11 | Sem infraestrutura nova; a solução usa o banco e a stack atuais | [09:07] Diego, [09:30] Larissa |
| PRD-NFR-12 | **Revisão de segurança** de pelo menos 2 dias úteis antes do lançamento | [09:46] Sofia |

## 8. Decisões e trade-offs principais

| Decisão | Trade-off aceito | Detalhe |
| --- | --- | --- |
| Notificação **assíncrona**, registrada junto com a mudança de status | Alguns segundos de atraso em troca de nunca travar nem perder uma mudança de status | [ADR-001](adrs/ADR-001-outbox-no-mysql.md) |
| Processo dedicado que verifica novos eventos **a cada 2 s** | Até 2 s de latência e um único processador, em troca de simplicidade e zero infraestrutura nova | [ADR-002](adrs/ADR-002-worker-separado-com-polling.md) |
| **5 reenvios em ~15 h**, depois fila de falhas com reenvio manual | Falhas longas exigem ação de um administrador, em troca de nenhum evento pendurado para sempre | [ADR-003](adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md) |
| **Assinatura com segredo por webhook** e troca com 24 h de convivência | Mais segredos para proteger, em troca de vazamentos isolados | [ADR-004](adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md) |
| **Pode haver repetição**; o cliente deduplica pelo ID do evento | Mais responsabilidade para o cliente, em troca de nenhuma perda e de um padrão de mercado | [ADR-005](adrs/ADR-005-entrega-at-least-once-com-x-event-id.md) |
| **Reuso** dos padrões técnicos do OMS | Herda as limitações atuais, em troca de entrega mais rápida e consistente | [ADR-006](adrs/ADR-006-reuso-dos-padroes-existentes.md) |

## 9. Dependências

| Dependência | Tipo | Origem |
| --- | --- | --- |
| Fluxo atual de mudança de status de pedidos e a máquina de estados | Interna (código) | [09:40] Bruno; `src/modules/orders/order.service.ts` |
| Controle de acesso por papel já existente (ADMIN) | Interna (código) | [09:36] Larissa; `src/middlewares/auth.middleware.ts` |
| Banco MySQL atual | Infraestrutura existente | [09:07] Diego |
| Revisão de segurança da Sofia (≥ 2 dias úteis) | Pessoas / processo | [09:46] Sofia, [09:49] Sofia |
| Documentação no portal do desenvolvedor (at-least-once, integração via API) | Produto (Marcos) | [09:26] Marcos, [09:40] Marcos |
| Clientes implementarem a verificação de assinatura e a deduplicação | Externa | [09:25] Diego, [09:25] Sofia |
| Confirmação do prazo com os clientes | Produto (Marcos) | [09:47] Marcos, [09:49] Marcos |

## 10. Riscos e mitigação

Probabilidade e impacto são estimativas do autor; a reunião não classificou os riscos.

| Risco | Probabilidade (estimativa do autor) | Impacto (estimativa do autor) | Mitigação |
| --- | --- | --- | --- |
| **Um cliente lento atrasa as notificações dos outros**: as entregas saem uma de cada vez, e cada cliente tem até 10 s para responder ([09:42] Diego) | Média | Alto | Decisão no design review: enviar em paralelo para pedidos diferentes, ou aceitar e monitorar o tempo de espera da fila. Detalhes no [FDD](FDD.md) |
| **Perder a Atlas Comercial** por atraso | Média | Alto | Escopo enxuto (sem e-mail, dashboard e rate limit); 3 sprints com a revisão de segurança já reservada; prazo confirmado com os clientes ([09:46] Larissa, [09:47] Marcos) |
| **Cliente processar a mesma notificação duas vezes** por não deduplicar | Média | Médio | Destaque no portal do desenvolvedor ([09:26] Marcos); ID do evento estável em todas as repetições |
| **Vazamento do segredo** de um cliente | Média | Alto | Segredo exclusivo por webhook e troca pela API com 24 h de convivência ([09:21] Sofia); já houve caso real ([09:22] Diego) |
| **Reenvio manual indevido**: hoje o cadastro público de usuários aceita o papel ADMIN (`src/modules/auth/auth.schemas.ts`) | Média | Alto | Pré-requisito a tratar na revisão de segurança antes do lançamento |
| **Cliente sobrecarregado** por rajadas de notificações | Baixa | Médio | Monitorar o volume por cliente; rate limiting já registrado como ponto em aberto ([09:39] Larissa) |
| **Cliente fora do ar por mais de ~15 h** | Baixa | Médio | Fila de falhas preserva o evento e o administrador reenvia; o aviso por e-mail está previsto para a próxima fase ([09:37] Larissa) |
| **Qualquer usuário autenticado gerencia webhooks de qualquer cliente** | Média | Médio | Aceito nesta fase ([09:37] Sofia); restrição de papel adiada |

## 11. Critérios de aceitação

1. **Dado** um webhook ativo para "SHIPPED", **quando** um pedido do cliente muda para SHIPPED, **então** o endpoint recebe a notificação em menos de 10 s.
2. **Dado** um webhook que só ouve "DELIVERED", **quando** o pedido muda para PAID, **então** nenhuma notificação é enviada a ele.
3. **Dado** um endpoint fora do ar, **quando** ocorre uma mudança de status, **então** a notificação é reenviada até 5 vezes ao longo de ~15 h e, se continuar falhando, aparece na fila de falhas com o motivo.
4. **Dado** um item na fila de falhas, **quando** um ADMIN pede o reenvio, **então** a notificação volta a ser enviada com o **mesmo** identificador de evento e o nome do administrador fica registrado. Se quem pede é um OPERATOR, o pedido é negado.
5. **Dado** um cadastro com URL `http://`, **então** a plataforma recusa com erro de validação.
6. **Dado** um webhook criado, **então** o segredo é exibido apenas na criação e na troca, e toda notificação vem assinada com ele.
7. **Dado** que o cliente trocou o segredo, **então** por 24 h notificações assinadas que conferem com o segredo antigo continuam válidas para ele, e depois só o novo vale.
8. **Dado** um webhook com entregas, **quando** o usuário consulta o histórico, **então** vê no máximo as 100 últimas, com resultado, conteúdo, resposta e tempo.
9. **Dado** que o envio da notificação falha, **então** a mudança de status do pedido **não** é afetada.
10. Os itens fora de escopo (seção 5.2) **não** estão presentes na entrega.

## 12. Estratégia de testes e validação

| Nível | O que valida | Como |
| --- | --- | --- |
| **Unitário** | Cálculo dos intervalos de reenvio; filtro de status; assinatura; limite de 64 KB | Funções puras do módulo, com Vitest (já usado em `tests/`) |
| **Integração** | Cadastro, edição, listagem, remoção, troca de segredo, histórico, permissão ADMIN no reenvio, recusa de HTTP | Testes de API com Supertest contra MySQL real, no padrão de `tests/orders.test.ts` |
| **Atomicidade** | Falha ao registrar a notificação desfaz a mudança de status; mudança desfeita não notifica | Teste de integração forçando erro dentro da transação |
| **Ponta a ponta** | Entrega < 10 s, headers e assinatura, reenvios, fila de falhas, reenvio manual | Worker real + endpoint receptor de teste respondendo 200, 503 ou com atraso > 10 s |
| **Resiliência** | Worker reiniciado no meio de um lote não perde eventos | Encerrar e religar o worker durante o processamento |
| **Segurança** | Geração e guarda de segredos, assinatura, exposição do segredo, controle de papel | Revisão de código da Sofia, ≥ 2 dias úteis antes do deploy ([09:46] Sofia) |
| **Validação de produto** | Os três clientes conseguem integrar a partir da documentação | Documentação no portal ([09:40] Marcos) e confirmação com os clientes ([09:49] Marcos) |
| **Acompanhamento pós-lançamento** | Latência p95, volume na fila de falhas, volume por cliente (insumo para rate limiting e e-mail) | Métricas descritas no [FDD §9](FDD.md#9-observabilidade) |
