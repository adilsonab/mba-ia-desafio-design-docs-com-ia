# Component Deep Analysis Report

**Component:** CompositionAndConfig
**Project:** order-management-api (Order Management System REST API)
**Analysis date:** 2026-11-02
**Scope (files analyzed):** `src/server.ts`, `src/app.ts`, `src/routes/index.ts`, `src/config/env.ts`, `src/middlewares/validate.middleware.ts`, `src/shared/http/response.ts`, `package.json` (scripts), `tests/setup.ts`, `tests/helpers/factories.ts`, `vitest.config.ts`, `docker-compose.yml`
**Supporting context read (not in scope, referenced for wiring):** `src/config/database.ts`, `src/shared/logger/index.ts`, `src/middlewares/error.middleware.ts`, `src/middlewares/request-logger.middleware.ts`, `src/middlewares/auth.middleware.ts`, `src/shared/errors/*`, `src/modules/*/*.routes.ts`, `src/modules/*/*.schemas.ts` (pagination fields), `src/modules/*/*.controller.ts`, `.env.example`, `tsconfig.json`, `tsconfig.build.json`, `.eslintrc.json`, `prisma/schema.prisma` (datasource block), `tests/auth.test.ts`, `tests/orders.test.ts`
**Ignored:** `node_modules`, `dist`, `.git`, `docs`

---

## 1. Executive Summary

CompositionAndConfig is the cross-cutting "glue" of the application. It does not implement domain behavior (orders, stock, customers); instead it decides **how the process starts, how configuration is validated, how every module is instantiated and wired, under which URL prefixes routes are mounted, how input is validated, what shape list responses take, and how the test environment is assembled**.

Key characteristics:

- **Two-stage bootstrap with a pure application factory.** `src/server.ts` is the only process entry point; it calls `buildApp({ prisma })` from `src/app.ts`, which is side-effect free apart from module-level singletons (env, logger, Prisma client) that are created on import. The same factory is reused by the test suite (`tests/helpers/factories.ts:10-15`), so tests exercise the real middleware pipeline end-to-end via Supertest.
- **Manual dependency injection (Composition Root).** `buildControllers()` (`src/app.ts:26-54`) constructs Repository -> Service -> Controller chains for five modules (users, auth, customers, products, orders) by hand, with no DI container. The only injected infrastructure dependency is `PrismaClient`.
- **Single versioned API prefix.** All business routes live under `/api/v1` (`src/app.ts:67`) and are subdivided in `src/routes/index.ts:24-28` into `/auth`, `/users`, `/customers`, `/products`, `/orders`. `/health` is the only unversioned route.
- **Fail-fast configuration.** `src/config/env.ts` validates `process.env` with Zod at import time; any violation prints the issues and terminates the process with exit code 1 (`src/config/env.ts:15-23`). Six variables are validated; `SHADOW_DATABASE_URL` and `MYSQL_*` are consumed only by Prisma CLI and Docker Compose.
- **Uniform validation pattern.** `validate({ body, query, params })` (`src/middlewares/validate.middleware.ts:11-37`) parses each request part with Zod, replaces/merges the coerced values into the request and converts `ZodError` into the domain `ValidationError` (HTTP 400, `VALIDATION_ERROR`).
- **Uniform pagination envelope.** `paginated()` (`src/shared/http/response.ts:22-24`) produces `{ data, pagination: { page, pageSize, total, totalPages } }`, used by customers, products and orders list endpoints.
- **Integration-test-only strategy against a real MySQL.** Vitest runs serially in a single forked process (`vitest.config.ts:11-17`) and `tests/setup.ts:8-16` deletes all rows from all seven tables before **every** test.

Key findings (detailed in section 10):

- Malformed JSON bodies and bodies larger than 1 MB are not mapped by the error middleware and therefore return HTTP 500 instead of 400/413 (`src/app.ts:61` combined with `src/middlewares/error.middleware.ts:14-65`). Those requests also bypass the request logger (registered after the JSON parser).
- The test setup wipes the database pointed to by `DATABASE_URL`; there is no separate test database configuration, so running `npm test` with the development `.env` values would erase development and seed data.
- `npm test` does not load `.env` (unlike `dev`, `start`, `db:seed`), so the env schema will call `process.exit(1)` unless variables are exported in the shell. Confidence: medium (Vitest only exposes `VITE_`-prefixed variables via `import.meta.env`; no `dotenv` import exists in the project).
- Graceful shutdown does not wait for `server.close()` to finish before `process.exit(0)`, so in-flight requests can be cut.
- No automated tests target the composition component directly (`/health`, 404 fallback, env validation, pagination math, validate middleware edge cases); it is covered only indirectly.

---

## 2. Data Flow Analysis

### 2.1 Process startup flow (`npm run dev` / `npm start`)

```
1. Node starts with --env-file=.env (package.json:12,14), which loads .env into process.env
   (tsx watch for dev, compiled dist/server.js for start).
2. src/server.ts imports ./app.js, ./config/env.js, ./config/database.js, ./shared/logger/index.js.
   ESM import evaluation triggers, in dependency order:
   a. src/config/env.ts:28  -> loadEnv() -> Zod safeParse(process.env)
      - failure: console.error list of issues, process.exit(1)   (env.ts:16-22)
      - success: frozen-by-convention `env` object exported
   b. src/shared/logger/index.ts:32 -> pino logger built from env.LOG_LEVEL / env.NODE_ENV
   c. src/config/database.ts:10 -> PrismaClient singleton (log level depends on NODE_ENV)
3. bootstrap() (server.ts:6) calls buildApp({ prisma }) (app.ts:56).
4. buildApp:
   a. express() instance, x-powered-by disabled                    (app.ts:59-60)
   b. express.json({ limit: '1mb' })                                (app.ts:61)
   c. requestLogger (X-Request-Id + access log on finish)           (app.ts:62)
   d. GET /health -> 200 { status: 'ok' }                           (app.ts:64-66)
   e. buildControllers(prisma) -> Controllers record                (app.ts:68, 26-54)
   f. app.use('/api/v1', buildApiRouter(controllers))               (app.ts:69)
   g. catch-all -> NotFoundError("Route <METHOD> <url>")            (app.ts:71-73)
   h. errorMiddleware (terminal)                                    (app.ts:75)
5. app.listen(env.PORT) -> log 'server_started' { port, env }       (server.ts:9-11)
6. SIGINT / SIGTERM handlers registered                             (server.ts:20-21)
7. Any rejection in bootstrap -> logger.fatal 'bootstrap_failed', exit(1) (server.ts:24-27)
```

### 2.2 Request flow through the composed pipeline

```
1. HTTP request arrives at Express (app.ts:59)
2. express.json parses body (max 1mb)                     -> parse errors jump to errorMiddleware
3. requestLogger assigns req.id (X-Request-Id header or uuid v4), sets response header,
   schedules access log on 'finish'
4. Path matching:
   - /health                    -> inline handler, 200 {"status":"ok"}
   - /api/v1/*                  -> buildApiRouter (routes/index.ts:21-31)
        /auth      -> buildAuthRouter
        /users     -> buildUserRouter
        /customers -> buildCustomerRouter (router-level authenticate)
        /products  -> buildProductRouter  (router-level authenticate)
        /orders    -> buildOrderRouter    (router-level authenticate)
   - anything else              -> 404 NotFoundError
5. Inside module routers: [authenticate] -> [requireRole] -> validate({...}) -> controller method
6. validate (validate.middleware.ts:12-36):
   - body   : parsed and REPLACED on req.body
   - query  : parsed and MERGED into req.query via Object.assign
   - params : parsed and REPLACED on req.params
   - ZodError -> ValidationError(400, VALIDATION_ERROR, details[{path,message}])
7. Controller casts req.query/req.body to the inferred schema type and calls the service
8. Services for list endpoints return paginated(items, page, pageSize, total)
   (response.ts:22-24) -> { data, pagination }
9. Controller responds res.status(200|201|204).json(...)
10. Errors -> next(err) -> errorMiddleware maps AppError / ZodError / Prisma P2002 / P2025,
    otherwise logs and returns 500 INTERNAL_SERVER_ERROR
11. On 'finish', requestLogger logs { requestId, method, path, statusCode, durationMs, userId }
```

### 2.3 Shutdown flow

```
1. SIGINT or SIGTERM received (server.ts:20-21)
2. log 'shutdown_initiated' { signal }
3. server.close(cb)  -> stops accepting new connections; cb logs 'http_server_closed' later
4. await prisma.$disconnect()
5. process.exit(0)   -> executed without waiting for server.close callback
```

### 2.4 Test flow

```
1. `npm test` -> vitest run (package.json:19)
2. vitest.config.ts: include tests/**/*.test.ts, node env, single fork, no file parallelism,
   30s test/hook timeouts, setupFiles: tests/setup.ts
3. tests/setup.ts imports src/config/database.ts (which imports env.ts -> env validation)
4. beforeAll: prisma.$connect()
5. beforeEach: deleteMany on orderStatusHistory, orderItem, order, orderNumberSequence,
   product, customer, user (child-to-parent order)
6. Test files obtain the cached Express app via getTestApp() -> buildApp({ prisma })
7. Factories insert rows directly with Prisma (users with bcrypt hash, customers, products)
8. loginAndGetToken drives the real POST /api/v1/auth/login endpoint and extracts
   body.tokens.accessToken
9. afterAll: prisma.$disconnect()
```

---

## 3. Business Rules & Logic

### Overview of the business rules

| # | Rule Type | Rule Description | Location |
|---|-----------|------------------|----------|
| BR-01 | Configuration / Validation | `NODE_ENV` must be `development`, `test` or `production`; default `development` | src/config/env.ts:4 |
| BR-02 | Configuration / Validation | `PORT` coerced to positive integer; default 3000 | src/config/env.ts:5 |
| BR-03 | Configuration / Validation | `LOG_LEVEL` must be one of fatal/error/warn/info/debug/trace; default `info` | src/config/env.ts:6 |
| BR-04 | Configuration / Validation | `DATABASE_URL` required, non-empty | src/config/env.ts:7 |
| BR-05 | Security / Configuration | `JWT_SECRET` required with minimum 16 characters | src/config/env.ts:8 |
| BR-06 | Configuration | `JWT_EXPIRES_IN` free-form string; default `8h` | src/config/env.ts:9 |
| BR-07 | Fail-fast | Invalid env aborts process with exit code 1 and prints each issue | src/config/env.ts:14-26 |
| BR-08 | Configuration (external) | `SHADOW_DATABASE_URL` and `MYSQL_*` are not validated by the app; consumed by Prisma CLI and Docker Compose | .env.example:6,11-14; prisma/schema.prisma:8; docker-compose.yml:7-10 |
| BR-09 | Environment-dependent behavior | NODE_ENV drives Prisma log level and pretty logging transport | src/config/database.ts:6; src/shared/logger/index.ts:20-28 |
| BR-10 | Process entry point | Only `src/server.ts` starts the HTTP server; `buildApp` never listens | src/server.ts:6-22; src/app.ts:56-78 |
| BR-11 | Process lifecycle | Graceful shutdown on SIGINT/SIGTERM: close server, disconnect Prisma, exit 0 | src/server.ts:13-21 |
| BR-12 | Process lifecycle | Bootstrap failure logged as fatal and exits 1 | src/server.ts:24-27 |
| BR-13 | Wiring / Composition | Manual DI: Repository -> Service -> Controller per module; shared UserRepository/UserService for auth | src/app.ts:26-54 |
| BR-14 | Wiring / Composition | OrderService receives PrismaClient directly in addition to its repository (transaction capability) | src/app.ts:45 |
| BR-15 | Routing | All business APIs are versioned under `/api/v1` | src/app.ts:69 |
| BR-16 | Routing | Module prefixes `/auth`, `/users`, `/customers`, `/products`, `/orders` | src/routes/index.ts:24-28 |
| BR-17 | Routing / Ops | `GET /health` is public, unversioned and returns `{status:'ok'}` without DB check | src/app.ts:64-66 |
| BR-18 | Routing / Error | Unmatched routes produce 404 `NOT_FOUND` with message `Route <METHOD> <url> not found` | src/app.ts:71-73; src/shared/errors/http-errors.ts:27-31 |
| BR-19 | Middleware order | json parser -> requestLogger -> health -> api router -> 404 -> error handler | src/app.ts:60-75 |
| BR-20 | Security / Hardening | `X-Powered-By` header disabled | src/app.ts:60 |
| BR-21 | Input limit | JSON body size limited to 1 MB | src/app.ts:61 |
| BR-22 | Authentication placement | customers/products/orders apply `authenticate` at router level; auth applies it only on `/me`; users applies `authenticate` + `requireRole('ADMIN')` per route | src/modules/*/\*.routes.ts |
| BR-23 | Validation pattern | `validate()` validates body, query, params independently with Zod in that order | src/middlewares/validate.middleware.ts:14-23 |
| BR-24 | Validation pattern | body and params are replaced with parsed output; query is merged (`Object.assign`) | src/middlewares/validate.middleware.ts:15,19,22 |
| BR-25 | Validation error contract | ZodError -> `ValidationError` 400 `VALIDATION_ERROR` with `details: [{path, message}]`, root path rendered as `(root)` | src/middlewares/validate.middleware.ts:26-32 |
| BR-26 | Validation | Non-Zod errors thrown during validation are forwarded unchanged | src/middlewares/validate.middleware.ts:34 |
| BR-27 | Response convention | Paginated envelope `{ data: T[], pagination: { page, pageSize, total, totalPages } }` | src/shared/http/response.ts:1-24 |
| BR-28 | Response convention | `totalPages = ceil(total / pageSize)`, or 0 if pageSize is 0 | src/shared/http/response.ts:18 |
| BR-29 | Pagination input | List endpoints accept `page` (int >= 1, default 1) and `pageSize` (int 1..100, default 20); offset = (page-1)*pageSize | src/modules/{customers,orders,products}/*.schemas.ts; *.service.ts |
| BR-30 | Response convention | Status codes: 200 read/update, 201 create, 204 delete with empty body | src/modules/*/\*.controller.ts |
| BR-31 | Build | Production build compiles only `src/` into `dist/` without source maps | tsconfig.build.json:1-11; package.json:13 |
| BR-32 | npm scripts | dev/start/db:seed load `.env` via `--env-file`; test, db:migrate, db:reset do not | package.json:10-21 |
| BR-33 | Runtime requirement | Node.js >= 20 (required by `--env-file`) and ESM (`"type": "module"`) with `.js` import specifiers | package.json:6-9 |
| BR-34 | Test infrastructure | Tests run serially in a single forked worker, 30s timeouts | vitest.config.ts:4-17 |
| BR-35 | Test isolation | Full table wipe before every test in FK-safe order | tests/setup.ts:8-16 |
| BR-36 | Test infrastructure | App instance is a lazily created singleton per worker | tests/helpers/factories.ts:8-15 |
| BR-37 | Test data | Factory defaults: OPERATOR role, `password123`, unique emails/SKUs via timestamp + random, price 10000 cents, stock 10, active | tests/helpers/factories.ts:17-74 |
| BR-38 | Test auth | Tokens are obtained through the real login endpoint, not by signing JWTs directly | tests/helpers/factories.ts:33-40, 76-83 |
| BR-39 | Local infrastructure | MySQL 8.0 via Docker Compose, port 3306, utf8mb4, mysql_native_password, healthcheck, named volume | docker-compose.yml:1-28 |

## Detailed breakdown of the business rules

---

### Business Rule: BR-01 to BR-06 - Environment variable schema

**Overview**:
The application accepts exactly six validated environment variables, declared in a single Zod object schema (`src/config/env.ts:3-10`). The inferred type `Env` (`src/config/env.ts:12`) is the only typed configuration contract inside the codebase.

**Detailed description**:
`NODE_ENV` is a closed enumeration (`development`, `test`, `production`) defaulting to `development`. Because the default applies whenever the variable is absent, a production deployment that forgets to set `NODE_ENV` would run in development mode, which activates `pino-pretty` transport (a devDependency) and verbose Prisma logging (`warn` + `error`). `PORT` uses `z.coerce.number().int().positive()`, so string values from the environment are converted to numbers; non-numeric strings fail, and there is no upper bound (values above 65535 pass validation and would fail only at `listen`). `LOG_LEVEL` is restricted to Pino's six levels and defaults to `info`.

`DATABASE_URL` only requires a non-empty string (`min(1)`), with the explicit message "DATABASE_URL is required". The URL format and the MySQL scheme are not validated by the app; Prisma validates it at connection time. `JWT_SECRET` requires at least 16 characters, with the message "JWT_SECRET must be at least 16 characters". This is the only security-strength rule enforced at configuration level; entropy and the use of the placeholder value from `.env.example:8` are not checked.

`JWT_EXPIRES_IN` accepts any string and defaults to `8h`. It is passed to `jsonwebtoken` through a type cast (`src/modules/auth/auth.service.ts:48`) and returned to clients in the login response (`auth.service.ts:43`). An invalid duration string is not detected at startup; it would surface as an error at token-signing time (login request), which the error middleware would map to HTTP 500. This is inferred from the code path; confidence: medium.

**Rule workflow**:
```
process.env --> envSchema.safeParse
   NODE_ENV      enum, default 'development'
   PORT          coerce number, int, > 0, default 3000
   LOG_LEVEL     enum (6 pino levels), default 'info'
   DATABASE_URL  string, min 1 (required)
   JWT_SECRET    string, min 16 (required)
   JWT_EXPIRES_IN string, default '8h'
--> typed `env` object exported and imported by database.ts, logger, auth.middleware, auth.service
```

---

### Business Rule: BR-07 - Fail-fast environment loading

**Overview**:
Configuration is validated exactly once, at module import time, and an invalid configuration terminates the process before any server, logger or database client exists.

**Detailed description**:
`loadEnv()` (`src/config/env.ts:14-26`) uses `safeParse` rather than `parse`, collects all issues and formats them as `  - <path>: <message>` lines, then writes them with `console.error` (explicitly allowed by an eslint-disable comment because the Pino logger depends on `env` and cannot be used yet). It then calls `process.exit(1)`.

Because `env` is evaluated as a top-level constant (`src/config/env.ts:28`), every module that imports it (directly or transitively: `database.ts`, `logger`, `auth.middleware.ts`, `auth.service.ts`, therefore `app.ts`, `server.ts`, `tests/setup.ts`, `tests/helpers/factories.ts`, `prisma/seed.ts` if it imports these) triggers validation. A consequence is that importing `buildApp` in any context, including tests, terminates the process if the environment is incomplete. There is no way to inject an alternative configuration object; configuration is a module-level singleton.

All issues are reported in one pass, which is an operational convenience: an operator missing both `DATABASE_URL` and `JWT_SECRET` sees both messages at once.

**Rule workflow**:
```
import env.ts
  -> safeParse(process.env)
     success -> export env
     failure -> format issues -> console.error("Invalid environment configuration:\n...") -> exit(1)
```

---

### Business Rule: BR-08 - Variables outside the application schema

**Overview**:
`.env.example` declares more variables than the application validates. These belong to other tools.

**Detailed description**:
`SHADOW_DATABASE_URL` (`.env.example:6`) is referenced only by `prisma/schema.prisma:8` (`shadowDatabaseUrl = env("SHADOW_DATABASE_URL")`) and is required by `prisma migrate dev` (script `db:migrate`). The example value uses the MySQL `root` user and a database named `oms_shadow`, which Docker Compose does not create explicitly; the root user is privileged enough for Prisma to manage it. Confidence on automatic creation: medium (Prisma behavior, not visible in code).

`MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` (`.env.example:11-14`) are consumed by Docker Compose variable interpolation (`docker-compose.yml:7-10,16`), each with a default identical to the example value. The application never reads them; their only coupling with the app is that `DATABASE_URL` in `.env.example:5` must match `MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DATABASE` manually.

Because the Zod object schema is non-strict, unknown variables in `process.env` are silently ignored.

**Rule workflow**:
```
.env --> app (Zod):        NODE_ENV, PORT, LOG_LEVEL, DATABASE_URL, JWT_SECRET, JWT_EXPIRES_IN
.env --> Prisma CLI:       DATABASE_URL, SHADOW_DATABASE_URL
.env --> docker compose:   MYSQL_ROOT_PASSWORD, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD
```

---

### Business Rule: BR-09 - NODE_ENV-dependent behavior

**Overview**:
`NODE_ENV` changes infrastructure behavior in two places only.

**Detailed description**:
In `src/config/database.ts:6`, Prisma logs `['warn','error']` in development and only `['error']` otherwise. In `src/shared/logger/index.ts:22-28`, development uses the `pino-pretty` transport with colors and `HH:MM:ss.l` timestamps; test and production emit structured JSON. The logger also stamps every line with `base: { service: 'order-management-api', env: env.NODE_ENV }`.

No other code path branches on `NODE_ENV`: error responses are identical across environments (no stack traces leak in any mode, per `error.middleware.ts:62-64`), and there is no test-specific database selection. The `test` value exists in the enum but nothing sets it automatically; Vitest sets `process.env.NODE_ENV` to `test` when not already defined (Vitest default behavior, not visible in project code; confidence: medium).

**Rule workflow**:
```
NODE_ENV=development -> Prisma log [warn,error], pino-pretty transport
NODE_ENV=test|production -> Prisma log [error], JSON logs to stdout
```

---

### Business Rule: BR-10 - Single process entry point and app factory separation

**Overview**:
Starting the HTTP listener is isolated in `src/server.ts`; `src/app.ts` exports pure factories that build but never start the server.

**Detailed description**:
`buildApp(deps: AppDependencies)` (`src/app.ts:56`) receives its only external dependency (`prisma`) explicitly via the `AppDependencies` type (`src/app.ts:22-24`). This enables the test helper to construct the same application without binding a port (`tests/helpers/factories.ts:12`), with Supertest managing an ephemeral server per request.

`buildControllers(prisma)` is exported separately (`src/app.ts:26`), so callers could construct controllers independently of Express; in the current codebase it is called only from `buildApp`.

Although `buildApp` accepts Prisma via injection, other singletons are not injectable: `env`, `logger` and (inside `auth.middleware.ts`) the JWT secret are imported as module-level constants. The DI boundary is therefore partial: database is injected, configuration and logging are global.

The npm scripts map to this entry point: `dev` runs `tsx watch --env-file=.env src/server.ts` and `start` runs `node --env-file=.env dist/server.js` (`package.json:11,13`).

**Rule workflow**:
```
server.ts (process) -> buildApp({ prisma }) -> app.listen(env.PORT)
tests                -> getTestApp() -> buildApp({ prisma }) -> supertest(app)
```

---

### Business Rule: BR-11 and BR-12 - Graceful shutdown and bootstrap failure

**Overview**:
The process handles SIGINT and SIGTERM by closing the HTTP server and the Prisma connection; unhandled bootstrap errors cause a fatal log and exit code 1.

**Detailed description**:
The `shutdown` closure (`src/server.ts:13-18`) logs `shutdown_initiated` with the signal name, calls `server.close()` with a callback that logs `http_server_closed`, awaits `prisma.$disconnect()` and then calls `process.exit(0)`. Since `server.close` is not awaited (it is callback-based and its completion depends on open connections finishing), `process.exit(0)` usually runs as soon as Prisma disconnects. In-flight requests may therefore be terminated, and the `http_server_closed` log line may never be printed. Keep-alive connections are not explicitly closed.

There is no guard against repeated signals (a second SIGINT launches a second shutdown concurrently) and no timeout. There are no `unhandledRejection` or `uncaughtException` handlers; those fall back to Node.js defaults.

`bootstrap()` is async; any rejected promise inside it is caught at `src/server.ts:24-27`, logged via `logger.fatal({ err }, 'bootstrap_failed')` and the process exits with 1. In practice `buildApp` and `listen` are synchronous, so the most likely failure modes (port in use) are emitted as `'error'` events on the server object, which are not handled by this catch. Confidence: high (no `server.on('error')` listener exists).

Note that `prisma.$connect()` is never called explicitly at startup; Prisma connects lazily on the first query. A wrong `DATABASE_URL` or an unavailable database is therefore discovered on the first request, not at boot.

**Rule workflow**:
```
SIGINT/SIGTERM -> log shutdown_initiated -> server.close(cb) -> await prisma.$disconnect() -> exit(0)
bootstrap() rejects -> logger.fatal bootstrap_failed -> exit(1)
```

---

### Business Rule: BR-13 and BR-14 - Manual dependency wiring (Composition Root)

**Overview**:
`buildControllers` is the composition root that instantiates every layer of every module once per application instance.

**Detailed description**:
The wiring (`src/app.ts:27-45`) is:

| Module | Repository | Service | Controller |
|--------|------------|---------|------------|
| users | `new UserRepository(prisma)` | `new UserService(userRepository)` | `new UserController(userService)` |
| auth | (reuses userRepository) | `new AuthService(userRepository, userService)` | `new AuthController(authService, userService)` |
| customers | `new CustomerRepository(prisma)` | `new CustomerService(customerRepository)` | `new CustomerController(customerService)` |
| products | `new ProductRepository(prisma)` | `new ProductService(productRepository)` | `new ProductController(productService)` |
| orders | `new OrderRepository(prisma)` | `new OrderService(orderRepository, prisma)` | `new OrderController(orderService)` |

Two wiring decisions are notable. First, the auth module has no repository of its own: it shares the user repository and user service instances, so auth is a consumer of the users module rather than an independent bounded unit. Second, `OrderService` receives the raw `PrismaClient` in addition to its repository; this is the only service with direct database access and is consistent with the order lifecycle requiring transactions across orders, products (stock) and status history (as described in the README and confirmed by the order tests on stock decrement/replenishment).

All instances are effectively singletons per `buildApp` call. Controllers expose handlers as arrow-function class properties (e.g. `src/modules/orders/order.controller.ts:9`), which is why they can be passed to Express routers unbound. The return value is typed as `Controllers` (`src/routes/index.ts:13-19`), which is the contract between composition and routing. Adding a new module (for example a webhook module, which the README describes as the upcoming feature) requires touching three places: a new chain in `buildControllers`, a new key in the `Controllers` type, and a new `router.use` line in `buildApiRouter`.

**Rule workflow**:
```
prisma
 |-> UserRepository -> UserService -> UserController
 |         \______________\__> AuthService -> AuthController (also gets UserService)
 |-> CustomerRepository -> CustomerService -> CustomerController
 |-> ProductRepository  -> ProductService  -> ProductController
 |-> OrderRepository ----> OrderService <---- prisma (direct)
                               \-> OrderController
=> Controllers { auth, users, customers, products, orders } -> buildApiRouter
```

---

### Business Rule: BR-15 to BR-18 - URL prefixes, health and 404

**Overview**:
The public URL space is split into an unversioned operational endpoint (`/health`), a versioned API (`/api/v1/...`), and a catch-all 404.

**Detailed description**:
`buildApiRouter` (`src/routes/index.ts:21-31`) creates one Express `Router` and mounts each module router under a fixed plural-noun prefix: `/auth`, `/users`, `/customers`, `/products`, `/orders`. The versioned prefix `/api/v1` is applied once at `src/app.ts:69`, so module routers are prefix-agnostic. A future `/api/v2` would require a second router mount; there is no versioning abstraction beyond the literal string.

`/health` (`src/app.ts:64-66`) is registered before the API router and before any authentication. It returns `200 {"status":"ok"}` unconditionally; it does not ping the database, so it is a liveness signal rather than a readiness signal. It still passes through `requestLogger`, so health probes produce access log lines.

The catch-all (`src/app.ts:71-73`) runs for any request not answered by previous handlers, including unknown subpaths under `/api/v1` and unsupported methods on existing paths (Express routers do not return 405). It creates `new NotFoundError('Route GET /x')`; since `NotFoundError` appends " not found" (`src/shared/errors/http-errors.ts:29`), the message becomes `Route GET /x not found`, with code `NOT_FOUND` and status 404, serialized by the error middleware as `{ error: { code, message } }`.

**Rule workflow**:
```
/health                     -> 200 {status:'ok'}
/api/v1/auth/...            -> auth router
/api/v1/users/...           -> users router
/api/v1/customers/...       -> customers router
/api/v1/products/...        -> products router
/api/v1/orders/...          -> orders router
anything else               -> 404 {error:{code:'NOT_FOUND', message:'Route <M> <url> not found'}}
```

---

### Business Rule: BR-19 to BR-21 - Global middleware order, hardening and body limit

**Overview**:
The order of global middleware is fixed and determines which requests are logged and how errors are formatted.

**Detailed description**:
The order is: `app.disable('x-powered-by')` -> `express.json({ limit: '1mb' })` -> `requestLogger` -> `/health` -> `/api/v1` -> 404 -> `errorMiddleware` (`src/app.ts:60-75`). The error middleware is registered last, as Express requires, so it receives errors from every previous stage.

Because the JSON parser runs before `requestLogger`, a request with malformed JSON or a body exceeding 1 MB fails inside `express.json`, which calls `next(err)` directly. Express then skips all non-error middleware, including `requestLogger`, so: no `X-Request-Id` header is set on the response, `req.id` is undefined (the error middleware logs `requestId: 'unknown'`, `error.middleware.ts:56`), and no `http_request` access log is written. The body-parser errors (`SyntaxError` with `status 400`, or `PayloadTooLargeError` with `status 413`) are neither `AppError`, `ZodError` nor Prisma errors, so they fall through to the generic branch and return `500 INTERNAL_SERVER_ERROR` while being logged as unhandled errors. Confidence: high (based on the explicit branches in `error.middleware.ts:15-64` and documented body-parser behavior).

Disabling `x-powered-by` is the only HTTP hardening measure; there is no CORS configuration, no security-header middleware, no rate limiting and no request timeout in the composition layer. The `requestLogger` trusts a client-provided `x-request-id` header verbatim (`request-logger.middleware.ts:6`), which allows log correlation with upstream systems but also lets clients inject arbitrary identifiers into logs.

**Rule workflow**:
```
request -> [json parser 1mb] --error--> errorMiddleware (500, no request id, no access log)
        -> [requestLogger] -> [/health | /api/v1 | 404] --error--> errorMiddleware
```

---

### Business Rule: BR-22 - Authentication placement per module router

**Overview**:
The composition layer mounts routers without authentication; each module router decides its own protection, resulting in three distinct patterns.

**Detailed description**:
`customers`, `products` and `orders` call `router.use(authenticate)` at the top of their router (`customer.routes.ts:14`, `product.routes.ts:14`, `order.routes.ts:14`), so every route under those prefixes requires a valid Bearer token; any authenticated role (ADMIN or OPERATOR) is accepted. `auth` leaves `/register` and `/login` public and protects only `GET /me` (`auth.routes.ts:10-12`). `users` exposes only `GET /:id`, protected by `authenticate` and `requireRole('ADMIN')` per route (`user.routes.ts:12-18`).

Because `authenticate` runs before `validate` in all cases, unauthenticated requests are rejected with 401 before payload validation; invalid payloads from authenticated users yield 400. For users, an OPERATOR with a malformed id receives 403 before validation.

A consequence of router-level `router.use(authenticate)` in Express 4 is that it runs for any request whose path enters that router, including paths that will not match any route; an unauthenticated request to `/api/v1/orders/unknown/path` returns 401 rather than 404. Confidence: high.

**Rule workflow**:
```
/api/v1/auth/register, /login   public -> validate -> controller
/api/v1/auth/me                 authenticate -> controller
/api/v1/users/:id               authenticate -> requireRole(ADMIN) -> validate -> controller
/api/v1/{customers,products,orders}/*  authenticate (router-level) -> validate -> controller
```

---

### Business Rule: BR-23 to BR-26 - The `validate` middleware pattern

**Overview**:
`validate(schemas)` is a higher-order middleware that accepts optional Zod schemas for `body`, `query` and `params`, enforces them, and normalizes request data before the controller runs.

**Detailed description**:
The middleware validates the parts in a fixed order: body, then query, then params (`validate.middleware.ts:14-23`). Validation stops at the first failing part because each `parse` throws; consequently, when both body and params are invalid (e.g. `PATCH /customers/:id` with a bad id and a bad body), only the body errors are reported. This is a direct consequence of sequential `parse` calls; the client sees the issues of one source only.

The parsed output is written back differently per source. `req.body` and `req.params` are replaced (`:15`, `:22`), so Zod defaults, coercions and stripping of unknown keys (default Zod object behavior) take effect: unknown body properties disappear before reaching the controller. `req.query` is merged with `Object.assign(req.query, parsedQuery)` (`:19`), so coerced and defaulted values (for instance `page` and `pageSize` as numbers with defaults 1 and 20) overwrite the raw strings, but unknown query parameters remain present on `req.query` because merging does not remove keys. The merge strategy is commonly used because in some Express versions `req.query` is a getter that cannot be reassigned; in Express 4.21.1 (the installed version) it is a writable property, so the choice is defensive. Confidence on intent: low (not documented).

On failure, a `ZodError` is converted to `new ValidationError('Validation failed', details)` where `details` is an array of `{ path, message }`; nested paths are dot-joined and an empty path becomes `(root)` (`:27-31`). `ValidationError` maps to HTTP 400 and code `VALIDATION_ERROR` (`http-errors.ts:9-13`). The error middleware independently formats raw `ZodError`s with the identical shape (`error.middleware.ts:7-12,26-35`), so `parse` calls done inside services also yield the same 400 contract. Any non-Zod error (for example a `refine` callback throwing) is passed through via `next(err)` (`:34`). Type safety is limited: the generic `S` gives typed schemas, but Express handler types are not narrowed, so controllers cast (`req.query as unknown as ListOrdersQuery`, `order.controller.ts:11`).

**Rule workflow**:
```
validate({ body?, query?, params? })
  body   ? req.body   = body.parse(req.body)
  query  ? Object.assign(req.query, query.parse(req.query))
  params ? req.params = params.parse(req.params)
  ok -> next()
  ZodError -> next(ValidationError 400 { details: [{ path | '(root)', message }] })
  other    -> next(err)
```

Example error response:
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Validation failed",
             "details": [ { "path": "email", "message": "Invalid email" } ] } }
```

---

### Business Rule: BR-27 to BR-29 - Pagination and list response convention

**Overview**:
All paginated list endpoints share the same request parameters and response envelope.

**Detailed description**:
`src/shared/http/response.ts` defines `Pagination { page, pageSize, total, totalPages }` and `PaginatedResponse<T> { data: T[]; pagination: Pagination }`. `buildPagination` computes `totalPages` as `Math.ceil(total / pageSize)`, with a guard returning 0 when `pageSize` is 0 to avoid division by zero (`:18`). This guard is unreachable through the HTTP API because every list schema enforces `pageSize >= 1`. When `total` is 0, `totalPages` is 0; when a client requests a page beyond the last, `data` is an empty array while `pagination.page` echoes the requested page (no clamping, no error).

The request side of the convention is defined in each module's list query schema, identically for customers (`customer.schemas.ts:26-27`), products (`product.schemas.ts:17-18`) and orders (`order.schemas.ts:24-25`): `page` is coerced to an integer >= 1 defaulting to 1; `pageSize` is coerced to an integer between 1 and 100 defaulting to 20. Services compute `skip = (page - 1) * pageSize` and `take = pageSize`, then call `paginated(items, page, pageSize, total)` (`customer.service.ts:17-20`, `product.service.ts:18-21`, `order.service.ts:38-41`). The pagination schema fragment is duplicated in the three modules rather than shared.

Non-list responses do not use an envelope: single resources are returned as plain JSON objects, creations return 201 with the created resource, deletions return 204 with no body (`*.controller.ts`). Errors always use `{ error: { code, message, details? } }`. The integration test `tests/orders.test.ts:194` asserts `pagination.total` for a status-filtered list, which is the only test assertion on this envelope.

**Rule workflow**:
```
GET /api/v1/{customers|products|orders}?page=2&pageSize=10
 -> validate(query) : page=2, pageSize=10 (numbers)
 -> service: skip=10, take=10, count total
 -> paginated(items, 2, 10, total)
 -> 200 { data: [...], pagination: { page: 2, pageSize: 10, total, totalPages: ceil(total/10) } }
```

---

### Business Rule: BR-30 - HTTP status code convention

**Overview**:
Controllers follow a consistent mapping between operation and status code, and the error middleware owns all error codes.

**Detailed description**:
Reads and updates return 200, creations (`POST /auth/register`, `POST /customers`, `POST /products`, `POST /orders`) return 201, and deletions return 204 with `res.send()` (`customer.controller.ts:48`, `order.controller.ts:51`, `product.controller.ts:48`). Login returns 200 (`auth.controller.ts:24`).

Every controller method wraps its body in `try/catch` and forwards to `next(err)`, which is required in Express 4 because rejected promises from async handlers are not automatically routed to the error middleware.

Error statuses come from the error hierarchy: 400 (`BAD_REQUEST`, `VALIDATION_ERROR`), 401 (`UNAUTHORIZED`), 403 (`FORBIDDEN`), 404 (`NOT_FOUND`, also Prisma P2025), 409 (`CONFLICT`, `INVALID_STATUS_TRANSITION`, also Prisma P2002), 422 (`UNPROCESSABLE_ENTITY`, `INSUFFICIENT_STOCK`), 500 (`INTERNAL_SERVER_ERROR`).

**Rule workflow**:
```
GET -> 200 | POST create -> 201 | PATCH -> 200 | DELETE -> 204 (empty)
error -> { error: { code, message, details? } } with status from AppError / mapping
```

---

### Business Rule: BR-31 to BR-33 - Build, npm scripts and runtime requirements

**Overview**:
`package.json` scripts define the operational lifecycle of the project.

**Detailed description**:

| Script | Command | Loads .env | Purpose |
|--------|---------|-----------|---------|
| dev | `tsx watch --env-file=.env src/server.ts` | yes (Node flag) | Hot-reload development server |
| build | `tsc -p tsconfig.build.json` | n/a | Compile `src/` to `dist/` (no source maps, no tests/prisma) |
| start | `node --env-file=.env dist/server.js` | yes (Node flag) | Run compiled server |
| db:migrate | `prisma migrate dev` | Prisma CLI loads `.env` itself | Create/apply migrations (needs shadow DB) |
| db:reset | `prisma migrate reset --force` | Prisma CLI | Drop, re-migrate, run seed without confirmation |
| db:seed | `tsx --env-file=.env prisma/seed.ts` | yes | Populate data |
| test | `vitest run` | no | Run tests once |
| test:watch | `vitest` | no | Watch mode |
| lint | `eslint . --ext .ts` | n/a | Lint (config files ignored) |
| format | `prettier --write .` | n/a | Format |

The `prisma.seed` key (`package.json:23-25`) defines `tsx prisma/seed.ts` (without `--env-file`) as the seed command used by `prisma migrate reset` and `prisma db seed`; in that path the Prisma CLI has already loaded `.env` into the environment. `start` requires `.env` to exist because `--env-file` fails when the file is missing (Node 20 behavior), so production deployments that inject variables through the platform still need a `.env` file or a different command. Confidence: medium (depends on Node minor version).

`"type": "module"` plus `moduleResolution: "Bundler"` (`tsconfig.json:5`) requires the `.js` extension in relative imports, observed in every import of the component. `tsconfig.json` declares a `@/*` path alias (`:24-26`) that is not used anywhere in `src/` and would not resolve at runtime under `node dist/server.js` because `tsc` does not rewrite aliases. The base `tsconfig.json` includes `tests` and `prisma` for type-checking in the editor, while the build config restricts to `src/`.

**Rule workflow**:
```
local dev:   docker compose up -d -> npm run db:migrate -> npm run db:seed -> npm run dev
production:  npm run build -> npm start (requires .env file)
tests:       export env vars / ensure DB up -> npm test
```

---

### Business Rule: BR-34 - Serial test execution

**Overview**:
Vitest is configured to run all test files sequentially in a single child process.

**Detailed description**:
`vitest.config.ts` sets `pool: 'forks'` with `singleFork: true` and `fileParallelism: false` (`:11-17`), so test files cannot run concurrently. This is required because all tests share one physical database and `tests/setup.ts` truncates every table before each test; parallel files would delete each other's data.

`globals: false` (`:5`) means test files must import `describe`, `it`, `expect` from `vitest` explicitly (as both test files do). `environment: 'node'` avoids a DOM. `include: ['tests/**/*.test.ts']` restricts discovery to the `tests` folder; co-located tests under `src/` would not be picked up. `testTimeout` and `hookTimeout` are raised to 30 seconds (`:8-9`) to accommodate bcrypt hashing and database round trips.

Because a single fork is reused, module singletons (`env`, `prisma`, `logger`, cached app) are shared across all test files.

**Rule workflow**:
```
vitest run -> 1 forked worker -> setup.ts -> auth.test.ts -> orders.test.ts (sequential)
```

---

### Business Rule: BR-35 - Database reset before every test

**Overview**:
Isolation is achieved by deleting all data from every table before each test case.

**Detailed description**:
`tests/setup.ts:8-16` runs `deleteMany()` on seven models in an order that respects foreign keys: `orderStatusHistory`, `orderItem`, `order`, `orderNumberSequence`, `product`, `customer`, `user`. Each test therefore starts with an empty database and must create all needed data through factories or API calls.

The setup uses the same `prisma` singleton as the application (`src/config/database.ts`), which connects to whatever `DATABASE_URL` holds. There is no separate test database variable, no guard that checks `NODE_ENV === 'test'` or the database name before deleting, and no transaction rollback strategy. Running the suite against a development database removes all seeded data. When the Prisma schema gains new tables (for example webhook-related tables), this list must be extended manually or those tables will retain data across tests, and FK constraints could make existing deletes fail.

`beforeAll` explicitly connects and `afterAll` disconnects (`:4-6`, `:18-20`); with `singleFork`, these hooks run per test file because setup files execute in each file's context.

**Rule workflow**:
```
beforeAll  -> prisma.$connect()
beforeEach -> delete orderStatusHistory -> orderItem -> order -> orderNumberSequence
              -> product -> customer -> user
afterAll   -> prisma.$disconnect()
```

---

### Business Rule: BR-36 to BR-38 - Test factories and authenticated test users

**Overview**:
`tests/helpers/factories.ts` provides the shared app instance, entity factories with defaults and overrides, and helpers to obtain JWTs through the real login flow.

**Detailed description**:
`getTestApp()` (`:10-15`) lazily builds one Express app per worker using the global `prisma` and caches it in a module variable. `createTestUser` (`:17-31`) hashes the password with bcrypt cost 10 (default password `password123`), generates a unique email `user-<timestamp>-<random6>@test.local`, defaults the name to `Test User` and the role to `OPERATOR`, inserts directly via Prisma (bypassing the register endpoint and its validation), and returns both the user and the plaintext password.

`loginAndGetToken` (`:33-40`) calls `POST /api/v1/auth/login` via Supertest and returns `res.body.tokens.accessToken`, throwing a descriptive error if the status is not 200. This couples test infrastructure to the login response contract (`tokens.accessToken`) and to the `/api/v1/auth` prefix. `bootstrapAuthenticatedUser(role)` (`:76-83`) combines both to return `{ user, token }`.

`createTestCustomer` (`:42-60`) creates a customer with a unique email, phone `+5511999999999`, document `000.000.000-00` and a fixed Sao Paulo address JSON. `createTestProduct` (`:62-74`) creates a product with a unique uppercase SKU `SKU-<timestamp>-<RANDOM4>`, price 10000 cents, stock 10 and active `true`. Customers and products are inserted directly with Prisma, so they bypass service-level rules; any business invariant enforced only in services is not applied to factory data.

**Rule workflow**:
```
bootstrapAuthenticatedUser('ADMIN')
  -> createTestUser({ role: 'ADMIN' }) -> prisma.user.create (bcrypt hash)
  -> loginAndGetToken(email, 'password123') -> POST /api/v1/auth/login -> tokens.accessToken
  -> { user, token }
```

---

### Business Rule: BR-39 - Local infrastructure via Docker Compose

**Overview**:
Docker Compose provides only the MySQL database; the application itself runs on the host.

**Detailed description**:
The single service `mysql` (`docker-compose.yml:2-24`) uses image `mysql:8.0`, container name `oms-mysql`, restart policy `unless-stopped`, and publishes port `3306:3306` on the host (conflicts with any local MySQL). Credentials and database name come from `MYSQL_*` variables with defaults `root_password`, `oms`, `oms_user`, `oms_password`, matching `.env.example`. Data persists in the named volume `oms_mysql_data`.

The server is started with `--default-authentication-plugin=mysql_native_password` (compatibility with older clients), `--character-set-server=utf8mb4` and `--collation-server=utf8mb4_unicode_ci`, which aligns with storing names and addresses with accents (e.g. the factory address "Sao Paulo" with diacritic). A healthcheck runs `mysqladmin ping` every 5s with 20 retries and a 30s start period; no application service depends on it because the app is not containerized.

There is no compose definition for a test database or for the shadow database; both rely on the single MySQL instance (shadow DB created by Prisma with root credentials).

**Rule workflow**:
```
docker compose up -d -> mysql:8.0 on localhost:3306 (db oms, user oms_user)
                     -> healthcheck mysqladmin ping
app (.env DATABASE_URL=mysql://oms_user:oms_password@localhost:3306/oms) -> connects
```

---

## 4. Component Structure

```
(project root)
├── package.json                    # Scripts (dev/build/start/db:*/test/lint/format), deps, engines >=20, ESM
├── docker-compose.yml              # Local MySQL 8.0 (only infra service)
├── .env.example                    # App vars + SHADOW_DATABASE_URL + MYSQL_* for compose
├── tsconfig.json                   # Strict TS, ES2022, Bundler resolution, includes tests/prisma
├── tsconfig.build.json             # Build-only config: src -> dist
├── vitest.config.ts                # Serial single-fork test runner config
├── src/
│   ├── server.ts                   # Process entry: bootstrap, listen, signal handling
│   ├── app.ts                      # buildControllers (composition root) + buildApp (Express pipeline)
│   ├── routes/
│   │   └── index.ts                # Controllers type + buildApiRouter (module prefixes)
│   ├── config/
│   │   ├── env.ts                  # Zod env schema, fail-fast loader, `env` singleton
│   │   └── database.ts             # (context) PrismaClient singleton
│   ├── middlewares/
│   │   └── validate.middleware.ts  # Zod-based body/query/params validation
│   └── shared/
│       └── http/
│           └── response.ts         # Pagination types, buildPagination, paginated
└── tests/
    ├── setup.ts                    # Global hooks: connect, wipe tables, disconnect
    └── helpers/
        └── factories.ts            # getTestApp, user/customer/product factories, login helpers
```

Size indicators: `app.ts` 78 lines, `server.ts` 27, `routes/index.ts` 31, `env.ts` 28, `validate.middleware.ts` 37, `response.ts` 24, `setup.ts` 20, `factories.ts` 83, `vitest.config.ts` 19, `docker-compose.yml` 28. All files have low cyclomatic complexity; the highest is `validate` (3 conditional branches plus error discrimination).

---

## 5. Dependency Analysis

### Internal dependencies

```
server.ts -> app.ts (buildApp)
server.ts -> config/env.ts (env.PORT, env.NODE_ENV)
server.ts -> config/database.ts (prisma) -> config/env.ts
server.ts -> shared/logger -> config/env.ts

app.ts -> middlewares/request-logger.middleware.ts -> shared/logger, uuid
app.ts -> middlewares/error.middleware.ts -> shared/errors, shared/logger, @prisma/client, zod
app.ts -> modules/{users,auth,customers,products,orders}/{repository,service,controller}
app.ts -> routes/index.ts (buildApiRouter, Controllers)
app.ts -> shared/errors (NotFoundError)

routes/index.ts -> modules/*/*.routes.ts (buildXRouter)
routes/index.ts -> modules/*/*.controller.ts (type-only imports)

validate.middleware.ts -> zod, shared/errors (ValidationError)
  <- used by auth.routes, user.routes, customer.routes, product.routes, order.routes

shared/http/response.ts (no dependencies)
  <- used by customer.service, product.service, order.service

config/env.ts -> zod
  <- used by database.ts, shared/logger, auth.middleware, auth.service

tests/setup.ts -> config/database.ts
tests/helpers/factories.ts -> config/database.ts, app.ts, bcrypt, supertest, @prisma/client types
tests/*.test.ts -> helpers/factories.ts, config/database.ts
```

### External dependencies (as used by this component)

| Package | Version | Role in component |
|---------|---------|-------------------|
| express | 4.21.1 | HTTP framework, Router, json body parser |
| zod | 3.23.8 | Env schema, validate middleware |
| @prisma/client | 5.22.0 | PrismaClient type injected into composition root; tests use it directly |
| prisma (dev) | 5.22.0 | CLI for db:migrate / db:reset |
| pino / pino-pretty (dev) | 9.5.0 / 11.3.0 | Logger used by server bootstrap/shutdown |
| uuid | 11.0.3 | Request id generation (request logger) |
| tsx (dev) | 4.19.2 | dev and db:seed runner |
| typescript (dev) | 5.6.3 | build |
| vitest (dev) | 2.1.4 | Test runner |
| supertest (dev) | 7.0.0 | HTTP assertions against buildApp |
| bcrypt | 5.1.1 | Test factory password hashing |
| MySQL | 8.0 (Docker image) | Database for app and tests |
| Node.js | >= 20 | `--env-file` flag, ESM |

---

## 6. Afferent and Efferent Coupling

Afferent (Ca) = number of distinct project files that depend on the unit. Efferent (Ce) = number of distinct project modules/packages the unit depends on (internal files + external packages).

| Component (unit) | Afferent Coupling | Efferent Coupling | Critical |
|------------------|-------------------|-------------------|----------|
| `env` (src/config/env.ts) | 5 (database.ts, logger, auth.middleware, auth.service, server.ts) + transitively every module | 1 (zod) | High |
| `buildApp` (src/app.ts) | 2 (server.ts, tests/helpers/factories.ts) | 20 (15 module classes, routes/index, 2 middlewares, shared/errors, express) | High |
| `buildControllers` (src/app.ts) | 1 (buildApp) | 15 (5 repositories, 5 services, 5 controllers) | Medium |
| `buildApiRouter` / `Controllers` (src/routes/index.ts) | 1 (app.ts) | 11 (5 route builders, 5 controller types, express) | Medium |
| `validate` (validate.middleware.ts) | 5 (all module route files) | 2 (zod, shared/errors) | High |
| `paginated` / `buildPagination` / `PaginatedResponse` (response.ts) | 3 (customer, product, order services) | 0 | Medium |
| `server.ts` bootstrap | 0 | 4 (app, env, database, logger) | Medium |
| `tests/setup.ts` | Vitest config (1) | 2 (database, vitest) | Medium |
| `tests/helpers/factories.ts` | 2 (auth.test.ts, orders.test.ts) | 6 (database, app, bcrypt, supertest, @prisma/client types, express types) | Medium |
| `vitest.config.ts` | 0 (tool entry) | 1 (vitest) | Low |
| `docker-compose.yml` | 0 code; implicit coupling to .env.example DATABASE_URL | 1 (mysql:8.0 image) | Low |

Interpretation: `app.ts` is the most unstable unit (very high efferent coupling, low afferent), which is the expected profile for a composition root. `env.ts`, `validate` and `response.ts` are stable units (high afferent, low efferent); changes to their contracts propagate to every module.

---

## 7. Endpoints

Endpoints defined directly by this component plus the prefixes it assigns to module routers (module route details are listed for completeness of the mounted URL space).

| Endpoint | Method | Description |
|----------|--------|-------------|
| /health | GET | Liveness check, public, returns `{ "status": "ok" }` (src/app.ts:64) |
| /api/v1/auth/register | POST | Public registration (validate body) |
| /api/v1/auth/login | POST | Public login, returns `tokens.accessToken` |
| /api/v1/auth/me | GET | Authenticated current user |
| /api/v1/users/{id} | GET | ADMIN only, uuid param |
| /api/v1/customers | GET | Authenticated, paginated list |
| /api/v1/customers/{id} | GET | Authenticated |
| /api/v1/customers | POST | Authenticated, 201 |
| /api/v1/customers/{id} | PATCH | Authenticated |
| /api/v1/customers/{id} | DELETE | Authenticated, 204 |
| /api/v1/products | GET | Authenticated, paginated list |
| /api/v1/products/{id} | GET | Authenticated |
| /api/v1/products | POST | Authenticated, 201 |
| /api/v1/products/{id} | PATCH | Authenticated |
| /api/v1/products/{id} | DELETE | Authenticated, 204 |
| /api/v1/orders | GET | Authenticated, paginated list (status filter) |
| /api/v1/orders/{id} | GET | Authenticated |
| /api/v1/orders | POST | Authenticated, 201 |
| /api/v1/orders/{id}/status | PATCH | Authenticated, status transition |
| /api/v1/orders/{id} | DELETE | Authenticated, 204 |
| (any other path/method) | ANY | 404 `NOT_FOUND` "Route <METHOD> <url> not found" (src/app.ts:71) |

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| MySQL 8.0 (via PrismaClient) | Database | Persistence for all modules; injected into composition root | MySQL wire protocol via Prisma engine | Relational / Prisma models | Lazy connection; P2002 -> 409, P2025 -> 404, others -> 500; disconnect on shutdown |
| Process environment (.env / platform) | Configuration source | App configuration | Node `--env-file` / process.env | KEY=VALUE strings | Zod validation, fail-fast exit(1) |
| HTTP clients | Inbound | REST API | HTTP/1.1 (Express) | JSON (max 1 MB) | Central error middleware; JSON parse errors fall to 500 |
| Operating system signals | Process | Graceful shutdown | SIGINT / SIGTERM | n/a | Close server (not awaited), disconnect Prisma, exit 0 |
| stdout (Pino) | Observability | Structured logs (startup, shutdown, access, errors) | stdout | JSON (pretty in development) | Redaction of auth headers, passwords, tokens |
| Docker Compose | Local infra | Provision MySQL | Docker | YAML | Healthcheck mysqladmin ping, restart unless-stopped |
| Prisma CLI | Tooling | Migrations, reset, seed | CLI | schema.prisma, SQL migrations | Requires DATABASE_URL and SHADOW_DATABASE_URL |
| Vitest + Supertest | Test tooling | In-process HTTP testing of buildApp against real DB | In-memory HTTP | JSON | Factory throws on failed login |

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Composition Root / Manual DI | `buildControllers(prisma)` | src/app.ts:26-54 | Single place where object graph is built; constructor injection |
| Application Factory | `buildApp(deps)` | src/app.ts:56-78 | Build app without listening; reuse in tests |
| Router Factory | `buildApiRouter(controllers)`, `buildXRouter(controller)` | src/routes/index.ts:21-31; modules/*/*.routes.ts | Decouple routing from instantiation |
| Layered architecture (Controller -> Service -> Repository) | Per-module chains | src/app.ts:27-45 | Separation of HTTP, business logic and persistence |
| Module-level Singleton | `env`, `prisma`, `logger`, cached test app | env.ts:28; database.ts:10; logger/index.ts:32; factories.ts:8 | Single shared instance per process |
| Fail-fast configuration / Schema validation | Zod env schema | src/config/env.ts | Reject invalid config at startup |
| Middleware chain (Chain of Responsibility) | Express pipeline | src/app.ts:60-75 | Ordered cross-cutting concerns |
| Higher-order middleware | `validate(schemas)`, `requireRole(...roles)` | validate.middleware.ts:11; auth.middleware.ts:49 | Configurable reusable middleware |
| Centralized error handling / Exception translation | ZodError -> ValidationError; errorMiddleware | validate.middleware.ts:26-32; error.middleware.ts | Single error contract `{ error: { code, message, details? } }` |
| Envelope / DTO for collections | `PaginatedResponse<T>` | src/shared/http/response.ts | Uniform list response |
| URI versioning | `/api/v1` prefix | src/app.ts:69 | API evolution |
| Graceful shutdown | Signal handlers | src/server.ts:13-21 | Release resources on termination |
| Test Data Builder / Object Mother | `createTestUser`, `createTestCustomer`, `createTestProduct` with overrides | tests/helpers/factories.ts | Concise test arrangement with defaults |
| Database cleanup per test | `beforeEach` deleteMany | tests/setup.ts:8-16 | Test isolation on shared DB |

Architectural decisions observed:

- No DI container; wiring is explicit and type-checked by the `Controllers` type.
- Infrastructure (Prisma) is injected into `buildApp`, but configuration and logger are global imports, so the app is only partially configurable from the outside.
- Validation lives at the routing edge (route definitions), not in controllers or services.
- Integration tests over unit tests: the entire test strategy relies on a real database and the real Express pipeline.
- Application is not containerized; Docker is used only for MySQL.

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| High | tests/setup.ts | Deletes all rows of all tables before each test using the same `DATABASE_URL` as development; no test DB variable or safety guard | Running `npm test` against the dev database destroys development/seed data; accidental execution against a shared DB is destructive |
| High | app.ts + error.middleware.ts | Body-parser errors (malformed JSON, payload > 1 MB) are not mapped and return 500 `INTERNAL_SERVER_ERROR` | Client errors reported as server errors; noisy error logs; misleading monitoring |
| Medium | app.ts middleware order | `express.json` runs before `requestLogger`; parse failures get no `X-Request-Id` and no access log; error log shows `requestId: 'unknown'` | Reduced traceability for a class of failed requests |
| Medium | package.json `test` script | `vitest run` does not load `.env` and the project has no dotenv; env.ts calls `process.exit(1)` when variables are missing (confidence: medium) | Tests fail to start unless variables are exported in the shell; inconsistent with other scripts |
| Medium | server.ts shutdown | `server.close()` not awaited before `process.exit(0)`; no timeout; no double-signal guard; no `server.on('error')` handler | In-flight requests can be cut; listen errors (EADDRINUSE) bypass the fatal log path |
| Medium | tests/setup.ts | Hardcoded table list must be maintained manually when the schema grows | New tables keep data between tests or cause FK failures |
| Medium | env.ts | `NODE_ENV` defaults to `development`; production without explicit NODE_ENV uses pino-pretty (a devDependency) | Possible startup failure or verbose logs in production if devDependencies are not installed |
| Medium | env.ts | `JWT_EXPIRES_IN` not format-validated; `JWT_SECRET` only length-checked (placeholder from .env.example passes) | Misconfiguration detected only at login time (500); weak/placeholder secret accepted |
| Medium | Database connection | No explicit `$connect()` at boot and `/health` does not check DB | Process reports healthy while database is unreachable |
| Low | validate.middleware.ts | Validation stops at first failing source (body before params); query merged so unknown keys persist | Partial error details for clients; unvalidated keys remain on `req.query` |
| Low | validate.middleware.ts / controllers | Parsed types not propagated to handlers; controllers use `as unknown as` casts | Type drift between schema and controller is not caught by the compiler |
| Low | Module schemas | Pagination schema fragment (`page`, `pageSize`) duplicated in 3 modules | Inconsistent changes possible |
| Low | response.ts | `pageSize === 0` guard is dead code under current schemas; out-of-range pages are not clamped | Minor; empty data with requested page echoed |
| Low | routes (router-level authenticate) | Unauthenticated requests to unknown paths under protected prefixes get 401 instead of 404 | Minor API inconsistency |
| Low | request-logger | Client-supplied `x-request-id` trusted without validation | Log injection/spoofing of correlation ids |
| Low | app.ts | No CORS, security headers, rate limiting or request timeouts configured in the pipeline | Hardening relies on external infrastructure |
| Low | package.json `start` | `--env-file=.env` requires the file to exist | Deployments injecting env via platform need a `.env` file or a different command |
| Low | tsconfig.json | Unused `@/*` path alias that would not resolve in compiled output | Potential confusion if adopted without a runtime resolver |
| Low | docker-compose.yml | Fixed host port 3306; no test or shadow database provisioned explicitly | Port conflicts with local MySQL; shadow DB relies on Prisma root privileges |
| Low | Composition root scalability | Adding a module requires edits in three places (app.ts, Controllers type, routes/index.ts) | Growing manual wiring; omissions caught only partially by types |

---

## 11. Test Coverage Analysis

### Test files located

| File | Kind | Tests | Relation to this component |
|------|------|-------|----------------------------|
| tests/setup.ts | Global setup (part of component) | n/a | Connect/wipe/disconnect hooks |
| tests/helpers/factories.ts | Test helper (part of component) | n/a | App factory reuse, data factories, login helper |
| tests/auth.test.ts | Integration (Supertest + MySQL) | 7 | Exercises buildApp pipeline, `/api/v1/auth` prefix, `validate` (register invalid payload -> 400 VALIDATION_ERROR, auth.test.ts:30-38), error contract (409, 401) |
| tests/orders.test.ts | Integration (Supertest + MySQL) | 8 | Exercises `/api/v1/orders` prefix, router-level auth, pagination envelope (`pagination.total`, orders.test.ts:194), error contract (404, 409, 422) |
| vitest.config.ts | Runner config (part of component) | n/a | Serial execution |

No unit tests exist anywhere in the project. No coverage tool is configured (no `@vitest/coverage-*` dependency, no `coverage` section in `vitest.config.ts`; `coverage/` is only listed in `.gitignore`), so coverage percentages below are qualitative estimates based on which code paths are exercised by the 15 integration tests.

### Coverage by unit

| Component | Unit Tests | Integration Tests | Coverage (estimated) | Test Quality |
|-----------|------------|-------------------|----------------------|--------------|
| buildApp / buildControllers (src/app.ts) | 0 | 15 (indirect, every test) | High for wiring of auth and orders paths; users/customers/products controllers instantiated but their routes not exercised | Wiring validated implicitly; `/health` and 404 catch-all never requested |
| buildApiRouter (src/routes/index.ts) | 0 | 15 (indirect) | `/auth` and `/orders` prefixes exercised; `/users`, `/customers`, `/products` not exercised via HTTP | No test asserts prefix mapping explicitly |
| server.ts | 0 | 0 | 0% | Bootstrap, signal handling and fatal path untested |
| env.ts | 0 | indirect (loaded at import) | Success path only | No test for invalid env, defaults or error formatting |
| validate.middleware.ts | 0 | 15 (indirect) | Body success + body failure (register) + query (orders list status filter) + params success | No test for params failure, query failure, multi-source ordering, `(root)` path, non-Zod errors |
| response.ts (paginated) | 0 | 1 assertion (orders.test.ts:194) | `total` asserted only | `totalPages`, `page`, `pageSize` defaults and empty results not asserted |
| tests/setup.ts | n/a | used by all | n/a | Correct FK order; destructive on shared DB |
| tests/helpers/factories.ts | n/a | used by all | n/a | Unique identifiers via timestamp+random; direct Prisma inserts bypass service validation |
| docker-compose.yml / npm scripts | n/a | n/a | n/a | Not testable by the suite; assumed external prerequisite |

### Observations

- The suite requires a running MySQL with migrations applied and valid env variables; there is no test container, mock database or CI configuration in the repository.
- Strengths: true end-to-end coverage of the real middleware pipeline, real JWT issuance via login, assertions on the uniform error envelope (`body.error.code`).
- Gaps directly relevant to this component: `/health`, the 404 catch-all message, malformed JSON handling, pagination defaults and `totalPages` math, env validation failure, shutdown behavior, `validate` for params/query errors, and the ADMIN-only `/api/v1/users/:id` route.
