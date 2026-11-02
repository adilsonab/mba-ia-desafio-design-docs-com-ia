# ADR-006: Reuso dos padrões existentes do projeto no módulo de webhooks

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-001](ADR-001-outbox-no-mysql.md), [ADR-002](ADR-002-worker-separado-com-polling.md), [ADR-003](ADR-003-retry-com-backoff-exponencial-e-dlq.md)

## Contexto e Problema

A feature de webhooks introduz um domínio novo (configuração de endpoints, outbox, entregas, DLQ) e um processo novo (o worker). O OMS já tem padrões consolidados: módulos por domínio com rotas, controller, service, repository e schemas; hierarquia de erros com códigos padronizados; middleware de erro centralizado; logger estruturado; validação com Zod; e controle de acesso por papel ([09:27] Bruno, [09:28] Bruno, [09:29] Bruno).

A questão é se o novo módulo segue esses padrões ou introduz abordagens próprias para erros, logs, organização e autorização.

## Fatores de Decisão

- Consistência de código para o time que mantém o OMS ([09:27] Bruno).
- O tratamento centralizado de erros deve funcionar sem alteração ([09:29] Bruno).
- Evitar dependências novas ("Não vamos botar nada novo", [09:29] Bruno).
- Integração mínima e explícita com o serviço de pedidos ([09:41] Diego).

## Alternativas Consideradas

1. **Abordagem própria para o módulo**: classes de erro, logging e organização específicos.
2. **Reuso máximo dos padrões existentes**, com o webhook como "módulo igual aos outros".

Para a integração com pedidos, também se considerou **injetar um repositório de webhooks inteiro** no serviço de pedidos ([09:41] Bruno).

## Decisão

**Reuso máximo do que já existe** ([09:30] Larissa: "Decisão: reuso máximo do que já existe. AppError, Pino, error middleware, padrão de módulos, padrão de schemas Zod, padrão de códigos de erro. Webhook fica como módulo igual aos outros."):

- **Estrutura de módulo:** novo módulo de webhooks em `src/modules/`, com a mesma divisão dos módulos existentes (como `src/modules/orders/`). A lógica de processamento do worker fica num arquivo dentro desse módulo, e o ponto de entrada do worker fica ao lado de `src/server.ts` ([09:27] Bruno, [09:28] Bruno).
- **Erros:** reutilizar `AppError` e suas subclasses de `src/shared/errors/`, com códigos de erro em maiúsculas e **prefixo `WEBHOOK_`**, no mesmo estilo de `INSUFFICIENT_STOCK` e `INVALID_STATUS_TRANSITION` ([09:28] Bruno, [09:29] Larissa).
- **Tratamento de erros:** o middleware centralizado (`src/middlewares/error.middleware.ts`) trata os novos erros sem modificação ([09:29] Bruno).
- **Logs:** o logger Pino existente (`src/shared/logger/index.ts`), sem bibliotecas novas ([09:29] Bruno).
- **Validação:** schemas Zod, como nos demais módulos ([09:30] Larissa).
- **Autorização:** o replay da DLQ reutiliza `requireRole` (`src/middlewares/auth.middleware.ts`) com papel ADMIN ([09:36] Larissa).
- **Identificadores:** UUID, como em todo o projeto ([09:51] Larissa).
- **Integração com pedidos:** uma **função** que recebe o cliente da transação corrente e registra o evento, chamada pela transação de mudança de status de `src/modules/orders/order.service.ts`, em vez de injetar um repositório inteiro ([09:41] Bruno, [09:41] Diego).

## Prós e Contras das Alternativas

### Abordagem própria
- ✅ Liberdade para otimizar o módulo isoladamente.
- ❌ Duas formas de fazer a mesma coisa na base de código.
- ❌ Exigiria adaptar o middleware de erro e o logging.

### Reuso máximo (escolhida)
- ✅ Respostas de erro no mesmo formato de toda a API, já entendido pelos clientes.
- ✅ Zero dependências novas; curva de aprendizado nula para o time.
- ✅ Integração com pedidos por função que recebe a transação: acoplamento mínimo e atomicidade preservada ([ADR-001](ADR-001-outbox-no-mysql.md)).
- ❌ O módulo herda limitações atuais dos padrões, como o fato de `requireRole` estar em uso numa única rota hoje.

### Injetar repositório inteiro no serviço de pedidos
- ✅ Segue a injeção por construtor já usada no projeto.
- ❌ Acopla mais do que o necessário; "função pura recebendo o tx" basta ([09:41] Diego).

## Consequências

### Positivas
- O módulo de webhooks fica indistinguível, em estrutura, dos demais, o que facilita revisão e manutenção.
- Erros `WEBHOOK_*` saem no mesmo envelope de resposta já usado por toda a API.
- A alteração no fluxo de pedidos se limita a uma chamada dentro da transação existente.

### Negativas
- O módulo herda fragilidades do código atual: `requireRole` hoje protege uma única rota (`src/modules/users/user.routes.ts`), e o cadastro público aceita criar usuários ADMIN (`src/modules/auth/auth.schemas.ts`). A proteção do replay fica tão forte quanto esse controle.
- Os padrões atuais não incluem métricas nem tracing. Observabilidade além de logs terá de ser introduzida pelo próprio módulo.
- O worker, sendo outro processo, reutiliza os padrões, mas precisa da sua própria instância de cliente de banco ([09:30] Bruno).

### Trade-off explícito
Troca-se a **liberdade de desenho do novo módulo** por **consistência e custo zero de adoção**, aceitando herdar as limitações conhecidas dos padrões atuais.

## Referências

- `src/shared/errors/http-errors.ts`: `AppError` e subclasses (`InsufficientStockError`, `InvalidStatusTransitionError`, `NotFoundError`, `ConflictError`).
- `src/middlewares/error.middleware.ts`: tratamento centralizado de AppError, Zod e Prisma.
- `src/middlewares/auth.middleware.ts:49-61`: `requireRole`.
- `src/modules/orders/order.service.ts:131-178`: transação de mudança de status, ponto de integração.
- `src/shared/logger/index.ts`: logger Pino.
- Transcrição: [09:27] Bruno, [09:28] Bruno, [09:28] Diego, [09:29] Larissa, [09:29] Bruno, [09:29] Diego, [09:30] Bruno, [09:30] Larissa, [09:36] Larissa, [09:40] Bruno, [09:41] Bruno, [09:41] Diego, [09:48] Larissa, [09:51] Larissa.
