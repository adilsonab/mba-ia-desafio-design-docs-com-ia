# Architectural Analysis Report

- Project: `order-management-api` (Order Management System REST API)
- Analysis date: 2026-11-02
- Scope: entire project root
- Excluded folders: `node_modules`, `dist`, `.git`, `docs`
- Files analyzed: 45 TypeScript files (39 in `src/`, 4 in `tests/`, `prisma/seed.ts`, `vitest.config.ts`), Prisma schema and migration, configuration files (`package.json`, `tsconfig*.json`, `vitest.config.ts`, `docker-compose.yml`, `.env.example`, `.eslintrc.json`, `.prettierrc`), `README.md` (challenge statement) and `TRANSCRICAO.md` (used only as context; no requirements are derived from it in this report)

All line references below are to the files as present at commit `e7f6311` (clean working tree).

---

## 1. Executive Summary

The repository contains a single-process, monolithic REST API written in TypeScript (ES modules, Node.js >= 20) on top of Express 4.21.1, with MySQL 8.0 as the only data store, accessed through Prisma ORM 5.22.0. Input validation is done with Zod 3.23.8, authentication with JWT (`jsonwebtoken` 9.0.2) and `bcrypt` 5.1.1, and structured logging with Pino 9.5.0.

The code is organized as a **modular monolith with a layered architecture inside each module** (routes -> controller -> service -> repository -> Prisma). Five feature modules exist under `src/modules/`: `auth`, `users`, `customers`, `products` and `orders`. Cross-cutting concerns live in `src/middlewares/` (authentication/authorization, validation, request logging, centralized error handling) and `src/shared/` (error hierarchy, HTTP pagination helpers, logger). Composition is done by **manual constructor dependency injection** in a single composition root, `buildControllers` in `src/app.ts:26-53`.

The architecturally most significant component is the **orders module**, which implements:

- An explicit, table-driven **order state machine** in `src/modules/orders/order.status.ts:3-10` (`PENDING -> PAID -> PROCESSING -> SHIPPED -> DELIVERED`, with `CANCELLED` reachable from `PENDING`, `PAID` and `PROCESSING`).
- A single **interactive Prisma transaction** in `OrderService.changeStatus` (`src/modules/orders/order.service.ts:126-179`) that validates the transition, debits or replenishes stock, updates the order and appends an `order_status_history` audit row atomically.

Key findings:

- There is **no eventing, message queue, outbox, background worker, scheduler, outbound HTTP client or webhook mechanism** anywhere in `src/`, `tests/` or `prisma/`. A case-insensitive search for `webhook`, `event`, `emit`, `queue`, `outbox`, `fetch(`, `axios` returned no matches. All side effects of a status change happen synchronously inside the request/transaction, and the only process entry point is `src/server.ts`.
- The error model is consistent: an `AppError` base class carrying `statusCode`, `errorCode` and optional `details` (`src/shared/errors/app-error.ts:3-16`), HTTP-specific subclasses (`src/shared/errors/http-errors.ts`), and a centralized error middleware that serializes everything into an `{ error: { code, message, details? } }` envelope (`src/middlewares/error.middleware.ts:14-65`).
- Role-based authorization exists (`requireRole` in `src/middlewares/auth.middleware.ts:49-61`) but is applied to exactly one route (`GET /api/v1/users/:id`, `src/modules/users/user.routes.ts:15`). All customer, product and order endpoints (including order deletion and status changes) require only authentication.
- The public `POST /api/v1/auth/register` endpoint accepts a `role` field that can be `ADMIN` (`src/modules/auth/auth.schemas.ts:7`, `src/modules/auth/auth.routes.ts:10`), which allows unauthenticated creation of administrator accounts.
- Infrastructure artifacts are limited to a `docker-compose.yml` that provisions MySQL only. There is no application Dockerfile, no CI/CD configuration and no Kubernetes manifests.
- Tests are integration tests (Vitest + Supertest) that run the real Express app against a real MySQL database, serially, wiping all tables before each test (`tests/setup.ts:8-16`).

---

## 2. System Overview

### 2.1 Directory structure

```
project-root/
├── src/
│   ├── server.ts                    # Process entry point: HTTP listen + graceful shutdown
│   ├── app.ts                       # Express app factory + composition root (manual DI)
│   ├── config/
│   │   ├── env.ts                   # Zod-validated environment configuration (fail-fast)
│   │   └── database.ts              # PrismaClient singleton factory
│   ├── routes/
│   │   └── index.ts                 # /api/v1 router aggregator
│   ├── middlewares/
│   │   ├── auth.middleware.ts       # authenticate (JWT) + requireRole (RBAC)
│   │   ├── validate.middleware.ts   # Zod validation of body/query/params
│   │   ├── request-logger.middleware.ts  # Request id + access log via Pino
│   │   └── error.middleware.ts      # Centralized error -> HTTP translation
│   ├── shared/
│   │   ├── errors/                  # AppError hierarchy + barrel (index.ts)
│   │   ├── http/response.ts         # Pagination response helpers
│   │   └── logger/index.ts          # Pino logger singleton
│   └── modules/
│       ├── auth/        # routes, controller, service, schemas (no repository)
│       ├── users/       # routes, controller, service, repository, schemas
│       ├── customers/   # routes, controller, service, repository, schemas
│       ├── products/    # routes, controller, service, repository, schemas
│       └── orders/      # routes, controller, service, repository, schemas, status (state machine)
├── prisma/
│   ├── schema.prisma                # MySQL data model (7 models, 2 enums)
│   ├── migrations/20260519182739_init/migration.sql
│   ├── migrations/migration_lock.toml
│   └── seed.ts                      # Development seed data
├── tests/
│   ├── setup.ts                     # Global DB lifecycle (connect, truncate, disconnect)
│   ├── helpers/factories.ts         # App + data factories, login helper
│   ├── auth.test.ts                 # 7 integration tests
│   └── orders.test.ts               # 8 integration tests
├── docker-compose.yml               # MySQL 8.0 container only
├── .env.example                     # Environment template
├── package.json / package-lock.json
├── tsconfig.json / tsconfig.build.json
├── vitest.config.ts
├── .eslintrc.json / .prettierrc / .prettierignore
├── README.md                        # Challenge statement
└── TRANSCRICAO.md                   # Meeting transcript (context only)
```

### 2.2 Architectural patterns identified

Multiple patterns coexist; each is documented separately with evidence.

| Pattern | Evidence |
|---------|----------|
| Modular monolith (feature-based modules) | `src/modules/{auth,users,customers,products,orders}` each own their routes, controller, service and schemas; single deployable process started by `src/server.ts` |
| Layered architecture per module | Routes (`*.routes.ts`) -> Controller (`*.controller.ts`) -> Service (`*.service.ts`) -> Repository (`*.repository.ts`) -> Prisma |
| Repository pattern | `UserRepository`, `CustomerRepository`, `ProductRepository`, `OrderRepository` wrap `PrismaClient` |
| Manual constructor dependency injection / composition root | `buildControllers(prisma)` in `src/app.ts:26-53`; router factories `build*Router(controller)` |
| App factory | `buildApp(deps)` in `src/app.ts:55-76`, reused by tests (`tests/helpers/factories.ts:10-15`) |
| Explicit finite state machine | Transition table in `src/modules/orders/order.status.ts:3-10` |
| Transaction script (interactive transaction) | `this.prisma.$transaction(async (tx) => ...)` in `src/modules/orders/order.service.ts:58` and `:131` |
| Audit trail (append-only history table) | `OrderStatusHistory` model (`prisma/schema.prisma:116-131`) written on create (`order.service.ts:106-113`) and on every status change (`order.service.ts:159-167`) |
| Centralized exception handling with typed error codes | `AppError` hierarchy + `errorMiddleware` |
| Schema-first validation middleware | `validate({ body, query, params })` in `src/middlewares/validate.middleware.ts:11-37` |
| Singleton infrastructure clients | `prisma` (`src/config/database.ts:10`), `logger` (`src/shared/logger/index.ts:32`), `env` (`src/config/env.ts:27`) |

No evidence was found of hexagonal/ports-and-adapters, CQRS, event sourcing, domain events, or microservices.

---

## 3. Critical Components Analysis

### 3.1 How coupling is measured

**Afferent coupling (Ca)** is the number of other project source files that depend on (import) a component; a high Ca means many parts of the system rely on it, so changes to it propagate widely. **Efferent coupling (Ce)** is the number of other project source files that a component itself imports; a high Ce means the component depends on many others and is sensitive to their changes. In this report both metrics were determined by statically parsing every `import ... from '...'` statement in `src/**/*.ts` and counting distinct internal (project-relative) files. Only production code under `src/` is counted in the main figures; dependencies from `tests/` are listed separately in parentheses where they exist. Third-party packages (Express, Prisma, Zod, etc.) are not counted in Ce, but are named in the role column where relevant. `type`-only imports are counted because they still represent a compile-time dependency.

### 3.2 Component inventory

| Component | Type | Location | Afferent Coupling | Efferent Coupling | Architectural Role |
|-----------|------|----------|-------------------|-------------------|-------------------|
| Server bootstrap | Entry point | src/server.ts | 0 | 4 | Starts HTTP listener on `env.PORT`, registers SIGINT/SIGTERM shutdown (lines 6-27) |
| App factory / Composition root | Application assembly | src/app.ts | 1 (+1 test) | 17 | Builds Express app, wires all repositories/services/controllers, registers 404 and error middleware (lines 26-76) |
| API Router aggregator | Routing | src/routes/index.ts | 1 | 10 | Mounts `/auth`, `/users`, `/customers`, `/products`, `/orders` under `/api/v1` (lines 21-31) |
| Env config | Configuration | src/config/env.ts | 5 | 0 | Zod-validated env vars, exits process on invalid config (lines 3-27) |
| Database client (Prisma) | Infrastructure | src/config/database.ts | 1 (+3 tests) | 1 | `PrismaClient` singleton (line 10) |
| Pino Logger | Infrastructure / cross-cutting | src/shared/logger/index.ts | 3 | 1 | Structured JSON logger with redaction (lines 4-32) |
| AppError hierarchy (errors barrel) | Shared kernel | src/shared/errors/index.ts, app-error.ts, http-errors.ts | 11 | 2 (barrel) | Typed errors with HTTP status and error code |
| Response helpers | Shared utility | src/shared/http/response.ts | 3 | 0 | `paginated()` / `buildPagination()` response shape |
| Auth middleware (authenticate, requireRole) | Middleware / security | src/middlewares/auth.middleware.ts | 5 | 2 | JWT verification, `req.user` population, RBAC guard |
| Validate middleware | Middleware | src/middlewares/validate.middleware.ts | 5 | 1 | Zod parsing of body/query/params, raises `ValidationError` |
| Request logger middleware | Middleware / observability | src/middlewares/request-logger.middleware.ts | 1 | 1 | Request id (`X-Request-Id`) and access log on `finish` |
| Error middleware | Middleware / cross-cutting | src/middlewares/error.middleware.ts | 1 | 2 | Translates `AppError`, `ZodError`, Prisma `P2002`/`P2025` and unknown errors to JSON |
| AuthRoutes | Routing | src/modules/auth/auth.routes.ts | 1 | 4 | `POST /register`, `POST /login`, `GET /me` |
| AuthController | Controller | src/modules/auth/auth.controller.ts | 3 | 3 | HTTP adapter for auth flows |
| AuthService | Service | src/modules/auth/auth.service.ts | 2 | 5 | Credential check (bcrypt) and JWT signing |
| AuthSchemas | Validation schema | src/modules/auth/auth.schemas.ts | 2 | 0 | `registerSchema`, `loginSchema` |
| UserRoutes | Routing | src/modules/users/user.routes.ts | 1 | 3 | `GET /:id` (ADMIN only) |
| UserController | Controller | src/modules/users/user.controller.ts | 3 | 1 | HTTP adapter for users |
| UserService | Service | src/modules/users/user.service.ts | 4 | 3 | User creation (bcrypt hash), lookup, `toPublic` projection |
| UserRepository | Repository | src/modules/users/user.repository.ts | 2 | 0 | `users` table access |
| UserSchemas | Validation schema | src/modules/users/user.schemas.ts | 1 | 0 | `createUserSchema` type source; `userIdParamSchema` is unused |
| CustomerRoutes | Routing | src/modules/customers/customer.routes.ts | 1 | 4 | CRUD routes, authenticated |
| CustomerController | Controller | src/modules/customers/customer.controller.ts | 3 | 2 | HTTP adapter for customers |
| CustomerService | Service | src/modules/customers/customer.service.ts | 2 | 4 | Customer CRUD, email uniqueness |
| CustomerRepository | Repository | src/modules/customers/customer.repository.ts | 2 | 0 | `customers` table access, search, pagination |
| CustomerSchemas | Validation schema | src/modules/customers/customer.schemas.ts | 3 | 0 | Create/update/list schemas, address shape |
| ProductRoutes | Routing | src/modules/products/product.routes.ts | 1 | 4 | CRUD routes, authenticated |
| ProductController | Controller | src/modules/products/product.controller.ts | 3 | 2 | HTTP adapter for products |
| ProductService | Service | src/modules/products/product.service.ts | 2 | 4 | Product CRUD, SKU uniqueness |
| ProductRepository | Repository | src/modules/products/product.repository.ts | 2 | 0 | `products` table access |
| ProductSchemas | Validation schema | src/modules/products/product.schemas.ts | 3 | 0 | Create/update/list schemas |
| OrderRoutes | Routing | src/modules/orders/order.routes.ts | 1 | 4 | List, get, create, `PATCH /:id/status`, delete; authenticated only |
| OrderController | Controller | src/modules/orders/order.controller.ts | 3 | 3 | HTTP adapter; passes `req.user.id` as actor |
| OrderService | Core domain service | src/modules/orders/order.service.ts | 2 | 5 | Order creation, status transitions, stock control, audit history, order numbering |
| OrderStatus state machine | Domain policy | src/modules/orders/order.status.ts | 1 | 0 | Transition table and stock side-effect rules |
| OrderRepository | Repository | src/modules/orders/order.repository.ts | 2 | 0 | Read/list/delete of orders with relations |
| OrderSchemas | Validation schema | src/modules/orders/order.schemas.ts | 3 | 0 | `createOrderSchema`, `updateOrderStatusSchema`, `listOrdersQuerySchema` |
| Prisma schema and migration | Data model | prisma/schema.prisma, prisma/migrations/20260519182739_init/migration.sql | n/a (generated `@prisma/client` imported by 13 src files) | n/a | MySQL tables, enums, FKs, indexes |
| Seed script | Tooling | prisma/seed.ts | 0 | 0 (uses own `PrismaClient`) | Development data; writes statuses and history directly |
| Test setup | Test infrastructure | tests/setup.ts | 0 (loaded by Vitest) | 1 | Connect, wipe all tables before each test, disconnect |
| Test factories | Test infrastructure | tests/helpers/factories.ts | 2 (tests) | 2 | Cached app, user/customer/product factories, login helper |

### 3.3 Module-level coupling summary

| Module | Afferent (files outside module that import it) | Efferent (files outside module it imports) | Notes |
|--------|------------------------------------------------|--------------------------------------------|-------|
| orders | 2 (`src/app.ts`, `src/routes/index.ts`) | 5 (errors barrel, response helpers, auth middleware, validate middleware, Prisma client types) | Service accesses `customer`, `product`, `orderNumberSequence` tables directly through the transaction client, bypassing the customers and products modules |
| users | 4 (`src/app.ts`, `src/routes/index.ts`, `auth.controller.ts`, `auth.service.ts`) | 3 (errors, auth middleware, validate middleware) | Only module consumed by another module (auth) |
| auth | 2 (`src/app.ts`, `src/routes/index.ts`) | 6 (users repository, users service, env, errors, auth middleware, validate middleware) | Has no repository of its own; depends on users module |
| customers | 2 | 4 (errors, response helpers, auth middleware, validate middleware) | Self-contained |
| products | 2 | 4 (errors, response helpers, auth middleware, validate middleware) | Self-contained; `findManyByIds` (line 47) is unused |

### 3.4 Detailed description of components relevant to the order lifecycle

#### 3.4.1 Order state machine (`src/modules/orders/order.status.ts`)

- Transition table (lines 3-10), typed as `Readonly<Record<OrderStatus, ReadonlyArray<OrderStatus>>>`, keyed by the Prisma-generated `OrderStatus` enum:

  | From | Allowed targets |
  |------|-----------------|
  | PENDING | PAID, CANCELLED |
  | PAID | PROCESSING, CANCELLED |
  | PROCESSING | SHIPPED, CANCELLED |
  | SHIPPED | DELIVERED |
  | DELIVERED | (terminal) |
  | CANCELLED | (terminal) |

- `canTransition(from, to)` (lines 12-14) - used by `OrderService.changeStatus` (`order.service.ts:147`).
- `allowedTransitions(from)` (lines 16-18) and `isTerminal(status)` (lines 20-22) - exported but not referenced anywhere in `src/` or `tests/`.
- Stock rules: `STOCK_DEBIT_TRANSITION` constant (lines 24-27) and `shouldDebitStock` (lines 29-31) return true only for `PENDING -> PAID`; `shouldReplenishStock` (lines 33-37) returns true for `PAID -> CANCELLED` and `PROCESSING -> CANCELLED`. `PENDING -> CANCELLED` neither debits nor replenishes.
- The module is pure (no I/O, no internal imports), with Ca = 1 (only `OrderService`).

#### 3.4.2 `OrderService.changeStatus` transaction (`src/modules/orders/order.service.ts:126-179`)

Execution sequence inside a single interactive Prisma transaction (`this.prisma.$transaction(async (tx) => { ... })`, line 131):

1. Load the order with its items: `tx.order.findUnique({ where: { id }, include: { items: true } })` (lines 132-135). Throws `NotFoundError('Order')` if absent (line 136).
2. Same-status guard: if `from === to`, throws `ConflictError` with code `INVALID_STATUS_TRANSITION` and details `{ from, to }` (lines 140-146).
3. State machine guard: `if (!canTransition(from, to)) throw new InvalidStatusTransitionError(from, to)` (lines 147-149).
4. Stock side effects: `debitStock(tx, order.items)` when `shouldDebitStock` (lines 151-153); `replenishStock(tx, order.items)` when `shouldReplenishStock` (lines 154-156).
   - `debitStock` (lines 204-231) reads products, collects all shortages and throws `InsufficientStockError(unavailable)` (code `INSUFFICIENT_STOCK`, HTTP 422) before decrementing each product with `{ decrement: quantity }`.
   - `replenishStock` (lines 233-243) increments each product with `{ increment: quantity }`.
5. Status update: `tx.order.update({ where: { id }, data: { status: to } })` (line 158).
6. Audit row: `tx.orderStatusHistory.create({ data: { orderId, fromStatus, toStatus, changedById: userId, reason: input.reason ?? null } })` (lines 159-167).
7. Re-read the order with items (product id/sku/name), ordered history and customer (id/name/email) (lines 169-176) and return it (line 177).

Any thrown error rolls back the whole transaction, so stock movements, status update and history insertion are all-or-nothing. The method performs no logging, no external calls and no post-commit hooks; the transaction's return value is the only output. The actor (`userId`) comes from `req.user.id` in `OrderController.changeStatus` (`src/modules/orders/order.controller.ts:38-46`). The input is validated by `updateOrderStatusSchema` (`toStatus: z.nativeEnum(OrderStatus)`, `reason: string max 500`, `src/modules/orders/order.schemas.ts:18-21`) on route `PATCH /api/v1/orders/:id/status` (`src/modules/orders/order.routes.ts:19-23`).

No explicit row lock (`SELECT ... FOR UPDATE`) or isolation level is set; the transaction runs with the MySQL default isolation level. This is noted as a risk in Section 6.

#### 3.4.3 Status-history auditing

- Table `order_status_history` (`prisma/schema.prisma:116-131`; `migration.sql:87-99`): `id`, `orderId`, `fromStatus` (nullable), `toStatus`, `changedAt` (default now), `changedById` (FK to `users`), `reason` (VARCHAR 500, nullable). Indexed on `orderId` and `changedAt`.
- Written in two places in application code:
  - `OrderService.create` nested write: `fromStatus: null`, `toStatus: PENDING`, `reason: 'order created'` (`order.service.ts:106-113`).
  - `OrderService.changeStatus` (`order.service.ts:159-167`).
- Also written directly by `prisma/seed.ts:307-320`, which synthesizes history paths without going through the state machine or stock logic.
- Read through `OrderRepository.findByIdWithRelations` (`src/modules/orders/order.repository.ts:47-60`), ordered by `changedAt asc`, and exposed in `GET /api/v1/orders/:id` responses.
- The history FK to `orders` is `ON DELETE CASCADE` (`schema.prisma:125`, `migration.sql:122`), so deleting an order (allowed in `PENDING`/`CANCELLED`, `order.service.ts:181-192`) also deletes its audit trail.

#### 3.4.4 Error classes and error-code pattern (`src/shared/errors/`)

- `AppError` (`app-error.ts:3-16`): extends `Error`; public readonly `statusCode`, `errorCode`, `details` (`ErrorDetails = Record<string, unknown> | unknown[] | undefined`, line 1).
- Subclasses (`http-errors.ts`):

  | Class | HTTP | Default code | Lines | Customizable code |
  |-------|------|--------------|-------|-------------------|
  | BadRequestError | 400 | BAD_REQUEST | 3-7 | yes (not used anywhere) |
  | ValidationError | 400 | VALIDATION_ERROR | 9-13 | no |
  | UnauthorizedError | 401 | UNAUTHORIZED | 15-19 | no |
  | ForbiddenError | 403 | FORBIDDEN | 21-25 | no |
  | NotFoundError | 404 | NOT_FOUND | 27-31 | no (message is `${resource} not found`) |
  | ConflictError | 409 | CONFLICT | 33-37 | yes |
  | UnprocessableEntityError | 422 | UNPROCESSABLE_ENTITY | 39-43 | yes |
  | InvalidStatusTransitionError (extends ConflictError) | 409 | INVALID_STATUS_TRANSITION | 45-53 | no; details `{ from, to }` |
  | InsufficientStockError (extends UnprocessableEntityError) | 422 | INSUFFICIENT_STOCK | 55-63 | no; details `{ unavailable }` |

- Barrel export: `src/shared/errors/index.ts:1-13`. All consumers import from the barrel.
- Pattern: error codes are UPPER_SNAKE_CASE string literals; domain-specific codes are produced either by dedicated subclasses or by passing a custom `code` argument to `ConflictError`/`UnprocessableEntityError`. Codes found in the code base:
  - `EMAIL_ALREADY_USED` (`src/modules/users/user.service.ts:24`; `src/modules/customers/customer.service.ts:32,48`)
  - `SKU_ALREADY_USED` (`src/modules/products/product.service.ts:33,50`)
  - `INACTIVE_PRODUCT` (`src/modules/orders/order.service.ts:68-72`)
  - `INVALID_STATUS_TRANSITION` (`order.service.ts:141-145` and `http-errors.ts:49`)
  - `INVALID_ORDER_STATE_FOR_DELETE` (`order.service.ts:185-189`)
  - `INSUFFICIENT_STOCK` (`http-errors.ts:59`)
  - Middleware-generated: `VALIDATION_ERROR`, `CONFLICT`, `NOT_FOUND`, `INTERNAL_SERVER_ERROR` (`error.middleware.ts:29,42,50,63`).
- There is no central registry/enum of error codes; codes are inline string literals.

#### 3.4.5 `requireRole` middleware (`src/middlewares/auth.middleware.ts`)

- `AuthUser` type with `role: 'ADMIN' | 'OPERATOR'` (lines 6-10); Express `Request` is augmented with `user?: AuthUser` and `id?: string` (lines 12-17).
- `authenticate` (lines 27-47): requires `Authorization: Bearer <token>`, verifies with `jwt.verify(token, env.JWT_SECRET)` and sets `req.user` from claims `sub`, `email`, `role`. Failures yield `UnauthorizedError`.
- `requireRole(...roles)` (lines 49-61): returns a middleware that responds `UnauthorizedError` if `req.user` is missing and `ForbiddenError('Insufficient permissions')` (403, `FORBIDDEN`) if the role is not in the allowed list. It must be placed after `authenticate`.
- Usage: only `src/modules/users/user.routes.ts:12-18` (`authenticate, requireRole('ADMIN'), validate(...)`). `authenticate` is applied router-wide in customers (`customer.routes.ts:14`), products (`product.routes.ts:14`) and orders (`order.routes.ts:14`), and per-route for `GET /auth/me` (`auth.routes.ts:12`).
- The role is trusted from the JWT payload; it is not re-read from the database.

#### 3.4.6 Centralized error middleware (`src/middlewares/error.middleware.ts`)

Registered last in `src/app.ts:73`, after a catch-all 404 handler that raises `NotFoundError` (`src/app.ts:69-71`). Resolution order:

1. `AppError` -> `err.statusCode` with `{ error: { code: err.errorCode, message, details? } }` (lines 15-24). Not logged.
2. `ZodError` -> 400 `VALIDATION_ERROR` with formatted issues (lines 26-35). Normally unreachable from routes because `validate` already converts Zod errors into `ValidationError` (`validate.middleware.ts:26-33`).
3. `Prisma.PrismaClientKnownRequestError` `P2002` -> 409 `CONFLICT` with target fields (lines 38-47); `P2025` -> 404 `NOT_FOUND` (lines 48-53). Other Prisma codes (for example `P2003` foreign key violations) fall through.
4. Anything else -> logged with `logger.error({ err, requestId, method, path }, 'Unhandled error in request')` and 500 `INTERNAL_SERVER_ERROR` (lines 56-64).

Controllers follow a uniform `try { ... } catch (err) { next(err) }` pattern to forward errors (for example `order.controller.ts:9-55`).

#### 3.4.7 Pino logger (`src/shared/logger/index.ts`)

- `createLogger()` (lines 13-30): level from `env.LOG_LEVEL`; redaction of `req.headers.authorization`, `req.headers.cookie`, `*.password`, `*.passwordHash`, `*.token`, `*.accessToken` with censor `[REDACTED]` (lines 4-11, 16-19); base fields `service: 'order-management-api'`, `env` (line 20); ISO timestamps (line 21); `pino-pretty` transport only in `development` (lines 22-28).
- Singleton export `logger` (line 32), consumed by `src/server.ts` (lifecycle events `server_started`, `shutdown_initiated`, `http_server_closed`, `bootstrap_failed`), `request-logger.middleware.ts` (event `http_request` with `requestId`, `method`, `path`, `statusCode`, `durationMs`, `userId`) and `error.middleware.ts`.
- No child loggers per request or module; services and repositories do not log. `pino-http` is declared as a dependency (`package.json`) but is not imported anywhere.
- Request correlation: `X-Request-Id` is taken from the incoming header or generated with `uuid` v4, stored on `req.id` and echoed in the response header (`request-logger.middleware.ts:6-8`).

#### 3.4.8 Response helpers (`src/shared/http/response.ts`)

- Types `Pagination` (`page`, `pageSize`, `total`, `totalPages`) and `PaginatedResponse<T>` (`{ data, pagination }`) (lines 1-11).
- `buildPagination` (lines 13-20) and `paginated` (lines 22-24).
- Used by `CustomerService.list`, `ProductService.list` and `OrderService.list`. Non-list responses are written directly as JSON entities by controllers (`res.status(...).json(entity)`); there is no generic success envelope.

---

## 4. Dependency Mapping

### 4.1 High-level dependencies

```
server.ts
  -> app.ts (buildApp)
  -> config/env.ts, config/database.ts, shared/logger

app.ts (composition root)
  -> middlewares/request-logger -> shared/logger -> config/env
  -> routes/index.ts -> modules/*/ *.routes.ts
  -> modules/*/ repositories, services, controllers (instantiation)
  -> middlewares/error.middleware -> shared/errors, shared/logger

Per module (layered):
  *.routes.ts -> middlewares/auth (authenticate [, requireRole]) -> config/env, shared/errors
              -> middlewares/validate -> shared/errors
              -> *.schemas.ts (Zod)
              -> *.controller.ts -> *.service.ts -> *.repository.ts -> PrismaClient -> MySQL
                                                -> shared/errors
                                                -> shared/http/response (list endpoints)

Cross-module:
  auth.service.ts   -> users/user.repository.ts, users/user.service.ts
  auth.controller.ts-> users/user.service.ts
  order.service.ts  -> (via Prisma tx, at data level) customers, products, order_number_sequence tables
```

### 4.2 Orders request flow (status change)

```
PATCH /api/v1/orders/:id/status
  -> requestLogger (request id, access log on finish)
  -> express.json (1mb limit)
  -> authenticate (JWT)                         [no requireRole]
  -> validate({ params: orderIdParamSchema, body: updateOrderStatusSchema })
  -> OrderController.changeStatus (req.user.id as actor)
  -> OrderService.changeStatus
       BEGIN TRANSACTION
         read order + items
         same-status guard / canTransition (order.status.ts)
         debitStock | replenishStock (products table)
         update orders.status
         insert order_status_history
         re-read order with relations
       COMMIT (or ROLLBACK on any thrown error)
  -> 200 JSON (order with items, history, customer)
  -> on error: next(err) -> errorMiddleware -> { error: { code, message, details? } }
```

### 4.3 Observations

- There are no circular dependencies between source files.
- The only cross-module code dependency is `auth -> users`.
- `OrderService` depends directly on `PrismaClient` (constructor, `order.service.ts:27-30`) in addition to `OrderRepository`; its write paths (`create`, `changeStatus`) use the transaction client directly rather than the repository. The repository is used only for read and delete operations (`list`, `findByIdWithRelations`, `findById`, `deleteById`).
- `@prisma/client` generated types (`Order`, `OrderStatus`, `Prisma`, etc.) are imported by 13 files in `src/`, including the domain state machine and Zod schemas, so the Prisma schema is the de facto source of domain types.

---

## 5. Integration Points

| Integration | Type | Location | Purpose | Risk Level |
|-------------|------|----------|---------|------------|
| MySQL 8.0 | Relational database | prisma/schema.prisma:5-9, src/config/database.ts, docker-compose.yml | Single primary data store for all modules | High (single store, single instance) |
| Prisma ORM / Prisma Client 5.22.0 | Data access library + migration tool | src/config/database.ts:4-10, prisma/migrations/ | Query building, transactions, migrations, generated types | Medium |
| Shadow database | Migration tooling | prisma/schema.prisma:8, .env.example:6 | Required by `prisma migrate dev` | Low |
| JWT (jsonwebtoken) | Authentication token | src/modules/auth/auth.service.ts:47-50, src/middlewares/auth.middleware.ts:41 | Stateless bearer authentication with HS secret `JWT_SECRET` | High |
| bcrypt | Password hashing | src/modules/users/user.service.ts:16,26, src/modules/auth/auth.service.ts:36 | Hash and verify user passwords (10 rounds) | Low |
| Pino / pino-pretty | Logging (stdout) | src/shared/logger/index.ts | Structured logs; pretty output in development | Low |
| HTTP clients (API consumers) | Inbound REST API | src/routes/index.ts, `/health` in src/app.ts:62-64 | Exposes `/api/v1/*` and `/health` | Medium |
| Environment variables | Configuration | src/config/env.ts, .env.example | `NODE_ENV`, `PORT`, `LOG_LEVEL`, `DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRES_IN` | Medium |

No outbound integrations exist: there are no HTTP clients, SDKs for third-party APIs, message brokers, caches, object storage, email/SMS providers, schedulers or background workers. **There is no existing eventing, queue, outbox or webhook mechanism in the code base.**

---

## 6. Architectural Risks & Single Points of Failure

| Risk Level | Component | Issue | Impact | Details |
|------------|-----------|--------|--------|---------|
| Critical | AuthSchemas / AuthRoutes | Public self-registration with `ADMIN` role | Security, system-wide | `registerSchema.role` accepts `'ADMIN'` (`src/modules/auth/auth.schemas.ts:7`) and `POST /auth/register` is unauthenticated (`src/modules/auth/auth.routes.ts:10`) |
| High | Authorization model | `requireRole` applied to a single route | Security | Only `GET /users/:id` is role-restricted (`src/modules/users/user.routes.ts:15`); any authenticated `OPERATOR` can create/update/delete products and customers, change order status and delete orders |
| High | MySQL | Single point of failure | Availability, system-wide | One database for all modules; `docker-compose.yml` defines one MySQL container; no replica or failover configuration in the repository |
| High | OrderService.changeStatus | No explicit row locking | Data consistency | The order is read with a plain `findUnique` (`order.service.ts:132-135`) and stock is checked by reading products (`order.service.ts:208-221`) before decrementing (`:225-230`). Under concurrent requests on the same order or product, the default isolation level may allow two transitions or overselling to interleave. Whether this occurs depends on MySQL isolation semantics and was not verified at runtime |
| High | OrderService.changeStatus | All side effects synchronous inside the transaction | Latency / extensibility | Stock updates, status update, audit insert and re-read all occur inside one transaction holding locks on `orders` and `products` rows; there is no post-commit hook or event emission point |
| Medium | order_number_sequence | Global serialization point | Throughput | Every order creation upserts the single row `id = 1` inside the creation transaction (`order.service.ts:245-254`), serializing concurrent order creation on that row |
| Medium | OrderStatusHistory | Audit loss on delete | Auditability | `onDelete: Cascade` from orders to history (`prisma/schema.prisma:125`); `OrderService.delete` (`order.service.ts:181-192`) hard-deletes orders and thus their history |
| Medium | OrderService.delete | Check-then-act outside a transaction | Consistency | Status check (`:182-190`) and delete (`:191`) are separate statements; a concurrent status change between them is not prevented |
| Medium | Error middleware | Unmapped Prisma errors | API correctness | Foreign key violations (for example deleting a customer with orders, or a product referenced by order items, both `ON DELETE RESTRICT` in `migration.sql:110,119`) are not mapped and surface as 500 `INTERNAL_SERVER_ERROR` |
| Medium | Error middleware | Handled errors not logged | Observability | `AppError` responses (4xx, including 401/403) are returned without any log entry (`error.middleware.ts:15-24`); only the access log records the status code |
| Medium | Module boundaries | OrderService writes across module tables | Coupling | Reads `customer` and `product`, updates `product.stockQuantity`, and writes `orderNumberSequence` directly via `tx` instead of through the customers/products modules |
| Medium | Test suite | Destructive tests against the configured database | Data safety | `tests/setup.ts:8-16` deletes all rows from all tables before each test using the same `DATABASE_URL` as the application; no dedicated test database configuration exists |
| Low | Server bootstrap | Shutdown does not await in-flight requests | Availability | `shutdown` calls `server.close()` without awaiting it, then disconnects Prisma and calls `process.exit(0)` (`src/server.ts:13-18`) |
| Low | Seed script | Bypasses domain rules | Data consistency (dev) | `prisma/seed.ts:287-320` writes order statuses and history directly; stock is not debited for seeded `PAID`/later orders |
| Low | Dead code | Unused exports | Maintainability | `allowedTransitions`, `isTerminal` (`order.status.ts:16-22`), `BadRequestError` (`http-errors.ts:3-7`), `ProductRepository.findManyByIds` (`product.repository.ts:47-49`), `userIdParamSchema` (`user.schemas.ts:3-5`), `pino-http` dependency, `@/*` path alias in `tsconfig.json:24-26` |
| Low | Configuration | `SHADOW_DATABASE_URL` not validated | Tooling | Used by `prisma/schema.prisma:8` but absent from the Zod schema in `src/config/env.ts` (it is only needed by Prisma CLI) |

### Architectural debt summary

- Authorization is coarse (authenticated vs. not) for most of the API.
- Orders module mixes repository-based reads with direct Prisma transaction writes.
- No extension point exists after a successful order status change (no domain events, hooks or outbox), so any reaction to status changes currently requires modifying `OrderService.changeStatus` itself.
- Test coverage is limited to auth and orders integration tests; customers, products, users, `requireRole`/403 behaviour and the state machine functions as a unit are not tested directly.

---

## 7. Technology Stack Assessment

| Category | Technology | Version (package.json) | Usage |
|----------|------------|------------------------|-------|
| Runtime | Node.js | >= 20 (`engines`) | ES modules (`"type": "module"`), `--env-file` flag used in `dev` and `start` scripts |
| Language | TypeScript | 5.6.3 | `strict`, `noUncheckedIndexedAccess`, target ES2022, `moduleResolution: Bundler` (`tsconfig.json`) |
| Web framework | Express | 4.21.1 | Routing, middleware chain, JSON body parser (1 MB limit, `src/app.ts:59`), `x-powered-by` disabled |
| ORM | Prisma / @prisma/client | 5.22.0 | MySQL provider, interactive and batch transactions, migrations |
| Database | MySQL | 8.0 (docker image) | utf8mb4 / utf8mb4_unicode_ci |
| Validation | Zod | 3.23.8 | Env config, request schemas, DTO type inference |
| Auth | jsonwebtoken | 9.0.2 | HS-signed access tokens, default expiry `8h` |
| Password hashing | bcrypt | 5.1.1 | 10 salt rounds |
| Logging | pino / pino-pretty | 9.5.0 / 11.3.0 | Structured logs; `pino-http` 10.3.0 declared but unused |
| IDs | uuid | 11.0.3 | Request ids; entity ids generated by Prisma `uuid()` |
| Testing | Vitest / Supertest | 2.1.4 / 7.0.0 | Integration tests through HTTP |
| Dev runner | tsx | 4.19.2 | `tsx watch` for development, seed execution |
| Lint/format | ESLint 8 + @typescript-eslint 8, Prettier 3 | 8.57.1 / 8.13.0 / 3.3.3 | `consistent-type-imports`, `eqeqeq`, `no-console` (warn) |

Monetary values are stored as integer cents (`priceCents`, `subtotalCents`, `discountCents`, `totalCents`). Entity ids are UUID strings stored as `CHAR(36)`. Order numbers follow `ORD-000001` format (`order.service.ts:253`).

### 7.1 Prisma schema summary (`prisma/schema.prisma`)

| Model (table) | Key fields | Relations / constraints | Lines |
|---------------|------------|-------------------------|-------|
| User (`users`) | id, email (unique), passwordHash, name, role (`UserRole`) | creates Orders; authors OrderStatusHistory | 25-38 |
| Customer (`customers`) | id, name, email (unique), phone, document, address (JSON) | has Orders; index on document | 40-54 |
| Product (`products`) | id, sku (unique), name, description, priceCents, stockQuantity, active | referenced by OrderItem; indexes on active, name | 56-72 |
| Order (`orders`) | id, orderNumber (unique), customerId, status (`OrderStatus`, default PENDING), subtotal/discount/total cents, notes, createdById | FK customer (RESTRICT), FK createdBy (RESTRICT); indexes on customerId, status, createdAt, createdById | 74-97 |
| OrderItem (`order_items`) | id, orderId, productId, quantity, unitPriceCents, totalCents | FK order (CASCADE), FK product (RESTRICT) | 99-114 |
| OrderStatusHistory (`order_status_history`) | id, orderId, fromStatus?, toStatus, changedAt, changedById, reason? | FK order (CASCADE), FK changedBy (RESTRICT) | 116-131 |
| OrderNumberSequence (`order_number_sequence`) | id (default 1), nextValue | single-row counter | 133-138 |

Enums: `UserRole { ADMIN, OPERATOR }` (lines 11-14), `OrderStatus { PENDING, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED }` (lines 16-23). A single migration exists: `prisma/migrations/20260519182739_init/migration.sql`. No webhook-, event- or outbox-related tables exist.

### 7.2 Test setup

- `vitest.config.ts`: Node environment, `include: ['tests/**/*.test.ts']`, 30 s test/hook timeouts, `setupFiles: ['tests/setup.ts']`, `fileParallelism: false`, `pool: 'forks'` with `singleFork: true` (fully serial execution).
- `tests/setup.ts`: `prisma.$connect()` before all (lines 4-6); before each test deletes rows from `orderStatusHistory`, `orderItem`, `order`, `orderNumberSequence`, `product`, `customer`, `user` in FK-safe order (lines 8-16); disconnects after all (lines 18-20). It imports the application's shared `prisma` singleton (`src/config/database.ts`), so it requires a running MySQL and a valid `.env`-equivalent environment (the `test` npm script does not pass `--env-file`; environment variables must be present in the shell).
- `tests/helpers/factories.ts`: cached `buildApp({ prisma })` (lines 8-15), `createTestUser` (17-31), `loginAndGetToken` via `POST /api/v1/auth/login` (33-40), `createTestCustomer` (42-60), `createTestProduct` (62-74), `bootstrapAuthenticatedUser(role)` (76-83).
- `tests/auth.test.ts` (7 tests): register 201 with public data (line 6), duplicate email (19), invalid payload (30), login success (41), wrong password (54), `GET /auth/me` (65), `/auth/me` without token (79).
- `tests/orders.test.ts` (8 tests): create in PENDING with server-side totals and `ORD-\d{6}` number (line 12), non-existent product 404 (42), `PENDING -> PAID` decrements stock (59), invalid transition `PENDING -> SHIPPED` 409 (89), insufficient stock 422 (109), `PAID -> CANCELLED` replenishes stock (134), list filtered by status (163), refuses delete when not PENDING/CANCELLED (197).
- There are no unit tests, no mocks, and no coverage configuration.

---

## 8. Security Architecture and Risks

### 8.1 Security boundaries and controls present

- Authentication: stateless JWT bearer tokens signed with `env.JWT_SECRET` (minimum 16 characters enforced at startup, `src/config/env.ts:8`), expiry from `JWT_EXPIRES_IN` (default `8h`).
- Authorization: two roles (`ADMIN`, `OPERATOR`); RBAC guard `requireRole` available but used once.
- Input validation: Zod schemas on all routes with params/body/query (UUID ids, string length limits, positive integers).
- Password storage: bcrypt with 10 rounds; `passwordHash` excluded from API responses through `UserService.toPublic` (`src/modules/users/user.service.ts:42-51`).
- Log redaction of authorization headers, cookies, passwords and tokens (`src/shared/logger/index.ts:4-11`).
- Generic 500 responses do not leak stack traces (`error.middleware.ts:62-64`).
- Login returns the same `Invalid credentials` message for unknown email and wrong password (`auth.service.ts:33-39`).
- Request body size limited to 1 MB (`src/app.ts:59`).

### 8.2 Risks

| Severity | Area | Finding | Location |
|----------|------|---------|----------|
| Critical | Privilege escalation | Anyone can register an `ADMIN` account through the public register endpoint | src/modules/auth/auth.schemas.ts:7, src/modules/auth/auth.routes.ts:10 |
| High | Broken access control | No role restrictions on destructive or business-critical operations (order delete, order status change, product price/stock changes, customer delete) | src/modules/orders/order.routes.ts:14-24, src/modules/products/product.routes.ts:14-24, src/modules/customers/customer.routes.ts:14-24 |
| High | Brute force | No rate limiting or account lockout on `POST /auth/login` | src/modules/auth/auth.routes.ts:11 |
| Medium | Token lifecycle | No refresh/revocation; role and identity trusted from token claims for up to 8 h even if the user changes or is removed | src/middlewares/auth.middleware.ts:41-42, src/config/env.ts:9 |
| Medium | JWT verification options | `jwt.verify` is called without an explicit `algorithms` allow-list; library defaults apply | src/middlewares/auth.middleware.ts:41 |
| Medium | Missing HTTP hardening | No security headers (for example helmet), CORS policy or rate limiting middleware present | src/app.ts:55-76 |
| Medium | Default credentials | Seed creates `admin@oms.local` / `admin123` and `operador@oms.local` / `operator123`; `.env.example` contains placeholder JWT secret and database passwords; `docker-compose.yml` has default passwords and exposes 3306 on the host | prisma/seed.ts:6-7,194-210; .env.example:5-14; docker-compose.yml:7-12 |
| Medium | PII handling | Customer name, email, phone, document (CPF/CNPJ format) and address stored in plain text and returned by list/get endpoints to any authenticated user | prisma/schema.prisma:40-54 |
| Low | Log integrity | Client-supplied `X-Request-Id` is accepted without validation and written to logs and response headers | src/middlewares/request-logger.middleware.ts:6-8 |
| Low | Database principal | Same database credentials used for application and (per `.env.example`) root used for the shadow database | .env.example:5-6 |

There are no outbound network calls, so there are currently no SSRF, outbound secret-management or callback-signing concerns in the existing code.

---

## 9. Infrastructure Analysis

- **Containerization**: `docker-compose.yml` defines a single service `mysql` (image `mysql:8.0`, container `oms-mysql`, `restart: unless-stopped`), host port `3306:3306`, named volume `oms_mysql_data`, healthcheck via `mysqladmin ping` (5 s interval, 20 retries, 30 s start period), and server flags `--default-authentication-plugin=mysql_native_password`, `--character-set-server=utf8mb4`, `--collation-server=utf8mb4_unicode_ci`. Credentials come from environment variables with defaults.
- **Application runtime**: not containerized (no Dockerfile). The API runs as a single Node.js process: `npm run dev` (`tsx watch --env-file=.env src/server.ts`) or `npm run build` + `npm start` (`node --env-file=.env dist/server.js`). Build uses `tsconfig.build.json` (rootDir `src`, outDir `dist`).
- **Process model**: one HTTP server process; no worker processes, cron jobs or clustering. Graceful shutdown on SIGINT/SIGTERM (`src/server.ts:13-21`).
- **Health check**: `GET /health` returns `{ status: 'ok' }` without checking database connectivity (`src/app.ts:62-64`).
- **Database lifecycle**: `npm run db:migrate` (`prisma migrate dev`), `db:reset`, `db:seed`.
- **Configuration management**: fail-fast Zod validation of environment variables at import time (`src/config/env.ts:14-27`); `.env` is git-ignored (`.gitignore:4`).
- **CI/CD, Kubernetes, IaC**: none present in the repository.
- **Scalability**: the API is stateless (JWT) and could in principle run multiple instances, but the repository contains no load balancer or orchestration configuration; the database and the single-row order number sequence are shared serialization points.
