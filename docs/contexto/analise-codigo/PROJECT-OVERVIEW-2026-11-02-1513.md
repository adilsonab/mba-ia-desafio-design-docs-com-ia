# OMS (Order Management System) - Project Overview

**Generated on**: 2026-11-02 15:13

## Summary

API REST em Node.js + TypeScript (Express 4) com MySQL via Prisma 5. Cinco módulos de negócio (auth, users, customers, products, orders), cada um em camadas routes → controller → service → repository, montados manualmente em `src/app.ts` (`buildControllers`) e expostos sob `/api/v1` (`src/routes/index.ts`). Único processo/entry point: `src/server.ts`.

O núcleo de domínio é o módulo de pedidos: uma máquina de estados (`src/modules/orders/order.status.ts`) e o método `OrderService.changeStatus` (`src/modules/orders/order.service.ts:131-178`), que numa única transação Prisma valida a transição, debita/repõe estoque, atualiza o pedido e grava uma linha de auditoria em `order_status_history`.

Não existe nenhum mecanismo de eventos, filas, outbox, worker, scheduler ou cliente HTTP de saída. Também não existem métricas nem tracing; a observabilidade se limita a logs Pino estruturados e `X-Request-Id`.

## Architecture Overview

- Camadas por módulo, sem container de DI; `OrderService` recebe o `PrismaClient` diretamente para transações.
- Middlewares globais em ordem (`src/app.ts:60-75`): JSON parser (1 MB) → request logger → `/health` → `/api/v1` → 404 → error middleware.
- Autenticação JWT (`authenticate`) em customers/products/orders; `requireRole` (`src/middlewares/auth.middleware.ts:49-61`) usado apenas em `GET /users/:id` (ADMIN).
- Erros: `AppError` + 9 subclasses (`src/shared/errors/`), códigos UPPER_SNAKE_CASE passados inline; resposta padrão `{ error: { code, message, details? } }` pelo `src/middlewares/error.middleware.ts`.
- Configuração validada com Zod em `src/config/env.ts` (falha → exit 1).
- Persistência: 7 models, 2 enums, tabelas snake_case via `@@map`; numeração de pedidos por contador de linha única.

## Dependencies Health

- Prisma 5.22 (duas majors atrás), Express 4.21.1, Zod 3.23.8, Vitest 2.1.4 com vulnerabilidades reportadas pelo `npm audit`; ESLint 8 e Node 20 em fim de vida.
- `pino-http` declarado e nunca importado.
- Observação: IDs de CVE do relatório de dependências não foram verificados de forma independente.

## Components Analyzed

- **OrdersModule**: máquina de estados, regras de estoque (débito em PENDING→PAID, reposição em cancelamento de PAID/PROCESSING), transação de `changeStatus`, histórico de status, numeração `ORD-NNNNNN`.
- **ErrorHandling**: hierarquia `AppError`, 14 códigos distintos, mapeamento de Zod e Prisma P2002/P2025; apenas erros 500 são logados.
- **AuthAndAuthorization**: JWT com claims `{sub,email,role}`; `requireRole` com uso único; cadastro público aceita `role: ADMIN`.
- **Observability**: logger Pino com redaction, `X-Request-Id`, linha `http_request` por requisição; sem métricas/tracing; request id não propaga para serviços.
- **PersistenceLayer**: schema, cascades, ausência de CHECK constraints, transações bypassando repositórios.
- **CompositionAndConfig**: wiring manual, rotas, env vars, validação Zod, paginação, infraestrutura de testes.

## Critical Findings

### Security Risks
- Registro público permite criar ADMIN (`src/modules/auth/auth.schemas.ts:7`).
- Nenhuma checagem de papel em pedidos/produtos/clientes.
- `X-Request-Id` de entrada aceito sem validação.

### Technical Debt
- Erros P2003, JSON malformado e payload grande resultam em 500.
- Códigos de erro sem catálogo central; `BadRequestError` não usado.
- Testes apagam todas as tabelas do `DATABASE_URL` configurado; sem testes unitários nem ferramenta de cobertura.

### Single Points of Failure
- `changeStatus` sem lock de linha: mudanças concorrentes no mesmo pedido podem ambas ser aplicadas (estoque duplicado, histórico duplicado).
- Contador de linha única serializa a criação de pedidos.
- `/health` não verifica o banco.

## Reports Index

See [MANIFEST.md](./MANIFEST.md) for complete list of all generated reports.
