# Component Deep Analysis Report

**Component:** Observability (Pino logger, request logger middleware, request-id handling, all logger usages in `src/`)
**Project:** order-management-api (`package.json`)
**Analysis date:** 2026-11-02
**Scope excluded:** `node_modules`, `dist`, `.git`, `docs`

---

## 1. Executive Summary

The Observability component of the Order Management API is small and centralized. It consists of:

- A singleton Pino logger (`src/shared/logger/index.ts`) configured from the validated environment (`LOG_LEVEL`, `NODE_ENV`), with ISO timestamps, a static `base` context (`service`, `env`), a redaction list for credentials and tokens, and a `pino-pretty` transport only in `development`.
- An Express middleware (`src/middlewares/request-logger.middleware.ts`) that assigns or propagates a request identifier (`X-Request-Id`), echoes it in the response header, measures latency with `process.hrtime.bigint()`, and emits one structured `http_request` access-log line per completed response.
- A type augmentation (`src/middlewares/auth.middleware.ts:12-17`) that adds `id?: string` to Express `Request`, used as the carrier of the request id.
- Four logger consumers in the whole `src/` tree: the request logger (1 call), the centralized error middleware (1 call), and the server bootstrap/shutdown (4 calls). No business module (auth, users, customers, products, orders) logs anything.

Key findings:

1. **Logs only. No metrics and no tracing exist.** There is no Prometheus/OpenTelemetry/StatsD dependency, no `/metrics` endpoint, no spans, and no trace-context (`traceparent`) handling. `/health` (`src/app.ts:62-64`) is a static liveness check that does not touch the database.
2. **Request id is not propagated beyond the edge.** It lives in `req.id` and in two log lines (access log and unhandled-error log). There are no child loggers (`logger.child`), no `AsyncLocalStorage`, and the id is not passed to services, repositories, Prisma, or outgoing calls.
3. **`pino-http` (10.3.0) is declared as a runtime dependency but never imported.** The access log is hand-written.
4. **The incoming `X-Request-Id` header is trusted without validation** (length, format, or array form), which allows log-forging/log-pollution by clients.
5. **Some requests produce no access log and no request id:** body-parser failures (malformed JSON or payload over 1mb) occur in `express.json` registered *before* `requestLogger` (`src/app.ts:59-60`), and aborted connections never emit `finish`.
6. **Log level is not derived from the outcome.** All access-log lines, including 5xx, are `info`. Handled 4xx `AppError`/Zod/Prisma errors are not logged by the error middleware; only unexpected errors are logged at `error`.
7. **Several redaction paths are effectively inert** for the current call sites (`req.headers.*` is never logged as an object), and `*.password`-style wildcards only cover one nesting level.
8. **No business audit logging**, although the transcript (`TRANSCRICAO.md:210`) states that an admin replay endpoint "has to log who did the replay, for audit". Today, audit-like traceability exists only in the database (`changedById`, `createdById` in `src/modules/orders/order.service.ts:104,110,164`).

---

## 2. Data Flow Analysis

### 2.1 HTTP request (happy path and handled errors)

```
1. Request enters Express (src/app.ts:56)
2. express.json({ limit: '1mb' }) parses the body (src/app.ts:59)
3. requestLogger (src/app.ts:60 -> src/middlewares/request-logger.middleware.ts:5)
   3.1 Reads header 'x-request-id'; if absent, generates uuid v4 (line 6)
   3.2 Stores it in req.id (line 7)
   3.3 Sets response header 'X-Request-Id' (line 8)
   3.4 Captures start time with process.hrtime.bigint() (line 10)
   3.5 Registers res.on('finish') listener (line 12) and calls next() (line 27)
4. Route handling: /health or /api/v1/* routers (src/app.ts:62-67)
   4.1 authenticate (src/middlewares/auth.middleware.ts:27-47) may set req.user
5. Errors flow to errorMiddleware (src/middlewares/error.middleware.ts:14)
   5.1 AppError / ZodError / Prisma P2002 / Prisma P2025 -> JSON response, NOT logged
   5.2 Anything else -> logger.error({ err, requestId, method, path }, 'Unhandled error in request') (lines 56-60) -> 500
6. Response is flushed; 'finish' fires
7. logger.info({ requestId, method, path, statusCode, durationMs, userId }, 'http_request')
   (request-logger.middleware.ts:14-24)
8. Pino applies base fields {service, env}, ISO 'time', level, redaction, and writes:
   - development: to pino-pretty transport (worker thread, colorized) 
   - test/production: NDJSON to stdout
```

### 2.2 Request failing in body parsing (gap)

```
1. Request with malformed JSON or body > 1mb
2. express.json calls next(err) (src/app.ts:59)
3. requestLogger is skipped (non-error middleware), so:
   - req.id is never set
   - X-Request-Id header is never set on the response
   - no 'http_request' line is emitted
4. errorMiddleware: err is not AppError/ZodError/Prisma -> falls to generic branch
5. logger.error with requestId = 'unknown' (error.middleware.ts:56) and response 500
```

Confidence: High (derived from Express middleware ordering semantics and the code at the cited lines). The 500 status for body-parser errors is a consequence of the generic branch; body-parser sets `err.status = 400`, which the middleware ignores.

### 2.3 Process lifecycle

```
1. Module load: src/config/env.ts validates process.env; on failure console.error + exit(1) (lines 14-23)
   (logger does not exist yet at this point)
2. src/shared/logger/index.ts:32 creates the singleton at import time
3. src/server.ts:9-11 -> logger.info({ port, env }, 'server_started')
4. SIGINT/SIGTERM -> logger.info({ signal }, 'shutdown_initiated') (server.ts:14)
   -> server.close(cb -> logger.info('http_server_closed')) (line 15)
   -> await prisma.$disconnect() (line 16) -> process.exit(0) (line 17)
5. bootstrap() rejection -> logger.fatal({ err }, 'bootstrap_failed') -> process.exit(1) (server.ts:24-27)
```

### 2.4 Parallel (non-Pino) output channels

```
- Prisma client internal logging to stdout/stderr: ['warn','error'] in development, ['error'] otherwise (src/config/database.ts:6)
- console.error for invalid environment (src/config/env.ts:21)
- console.log / console.error in prisma/seed.ts (lines 180-330) - CLI script, outside the HTTP runtime
```

These channels do not carry `service`, `env`, `requestId`, or the Pino JSON format.

---

## 3. Business Rules & Logic

### Overview of the business rules

| Rule Type | Rule Description | Location |
|-----------|------------------|----------|
| Configuration | Log level is one of fatal/error/warn/info/debug/trace, default `info` | src/config/env.ts:6 |
| Configuration | Logger level comes from `env.LOG_LEVEL` | src/shared/logger/index.ts:15 |
| Configuration | Invalid env aborts the process before logger creation, using `console.error` | src/config/env.ts:14-23 |
| Security / Privacy | Six redaction paths censored with `[REDACTED]` | src/shared/logger/index.ts:4-11, 16-19 |
| Structured context | Every log line carries `service: 'order-management-api'` and `env: NODE_ENV` | src/shared/logger/index.ts:20 |
| Format | Timestamp is ISO-8601 (`time` field) | src/shared/logger/index.ts:21 |
| Environment | Pretty, colorized output only when `NODE_ENV === 'development'`; NDJSON otherwise | src/shared/logger/index.ts:22-28 |
| Lifecycle | Logger is a module-level singleton created at import time | src/shared/logger/index.ts:32 |
| Correlation | Request id = incoming `x-request-id` header, else new UUID v4 | src/middlewares/request-logger.middleware.ts:6 |
| Correlation | Request id stored on `req.id` (typed via module augmentation) | request-logger.middleware.ts:7; auth.middleware.ts:12-17 |
| Correlation | Request id echoed in response header `X-Request-Id` | request-logger.middleware.ts:8 |
| Access log | One `info` line `http_request` per finished response with requestId, method, path, statusCode, durationMs, userId | request-logger.middleware.ts:12-25 |
| Access log | Latency measured with monotonic high-resolution clock, rounded to 2 decimals in ms | request-logger.middleware.ts:10,13,20 |
| Access log | `userId` is taken from `req.user` at finish time (populated by `authenticate` when present) | request-logger.middleware.ts:21; auth.middleware.ts:42 |
| Middleware order | `express.json` runs before `requestLogger`; `requestLogger` runs before `/health` and all API routes | src/app.ts:59-60 |
| Error logging | Only unexpected errors (not AppError, ZodError, Prisma P2002/P2025) are logged, at `error` level | src/middlewares/error.middleware.ts:15-60 |
| Error logging | Error log includes `err`, `requestId` (fallback `'unknown'`), method, path; message `Unhandled error in request` | error.middleware.ts:56-60 |
| Error exposure | Internal error details are logged but never returned to the client (generic 500 body) | error.middleware.ts:62-64 |
| Lifecycle logging | `server_started` (info), `shutdown_initiated` (info), `http_server_closed` (info), `bootstrap_failed` (fatal) | src/server.ts:10,14,15,25 |
| Lifecycle | SIGINT and SIGTERM trigger graceful shutdown with log lines | src/server.ts:20-21 |
| Prisma logging | Prisma emits `warn`+`error` in development, `error` elsewhere, via its own output | src/config/database.ts:6 |
| Lint policy | `console.log` discouraged (`no-console` warn), `console.warn`/`console.error` allowed | .eslintrc.json (rules.no-console) |
| Absence | No metrics, no tracing, no child loggers, no async context propagation | Whole `src/` (grep evidence) |
| Absence | No `uncaughtException` / `unhandledRejection` handlers | src/server.ts (only signal handlers) |
| Decision (transcript) | Pino is the logging standard; reuse, add nothing new | TRANSCRICAO.md:174,180,282 |
| Requirement (transcript, not implemented) | Admin replay action must be logged for audit | TRANSCRICAO.md:210 |

### Detailed breakdown of the business rules

---

### Business Rule: Log level configuration

**Overview**:
The minimum log level emitted by the application is controlled by the `LOG_LEVEL` environment variable, validated by Zod and defaulting to `info`.

**Detailed description**:
`src/config/env.ts:6` declares `LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info')`. The enumeration matches the standard Pino levels except `silent`, which is therefore not allowed; there is no supported way to completely disable logs through configuration (for example, in tests). Any other value causes environment validation to fail, which prints the issues through `console.error` and terminates the process with exit code 1 (`env.ts:17-22`).

The validated value is passed directly to `pino({ level: env.LOG_LEVEL })` at `src/shared/logger/index.ts:15`. Because there is one global logger and no child loggers with distinct levels, the level is uniform across the whole process: access logs, error logs and lifecycle logs are all filtered by the same threshold. With the default `info`, all current log statements are emitted (the lowest level in use is `info`). Setting `LOG_LEVEL=warn` or higher would suppress every access log (`http_request`) and all lifecycle `info` events, leaving only `error` (unhandled request errors) and `fatal` (bootstrap failure).

There is no per-environment default: `.env.example:3` sets `LOG_LEVEL=info` and the schema default is also `info` regardless of `NODE_ENV`. The test command (`vitest run`, `package.json` scripts) does not load an env file nor override `LOG_LEVEL`, so tests run at `info` unless the shell defines otherwise, and every request issued by Supertest produces an access-log line on stdout. The level cannot be changed at runtime (no admin endpoint or signal handler adjusts `logger.level`).

**Rule workflow**:
```
process.env.LOG_LEVEL
  -> envSchema.safeParse (env.ts:15)
     -> invalid: console.error + process.exit(1)
     -> missing: 'info'
  -> pino({ level }) (logger/index.ts:15)
  -> any logger.<level>() below threshold is a no-op
```

---

### Business Rule: Sensitive data redaction

**Overview**:
The logger censors six object paths with the literal string `[REDACTED]` to prevent credentials and tokens from reaching logs.

**Detailed description**:
`src/shared/logger/index.ts:4-11` defines `redactPaths`: `req.headers.authorization`, `req.headers.cookie`, `*.password`, `*.passwordHash`, `*.token`, `*.accessToken`. They are applied with `censor: '[REDACTED]'` (lines 16-19). Pino's redaction (fast-redact) replaces values at the exact paths; `*` is a single-level wildcard, so `*.password` matches `{ anyKey: { password } }` but not a top-level `{ password }` nor deeper nesting such as `{ a: { b: { password } } }`. The censor is applied to the serialized output only; the original objects are not mutated in the application's view.

Mapping these paths against the actual call sites shows limited effective coverage. No call site logs a `req` object: the access log builds a flat object with `requestId`, `method`, `path`, `statusCode`, `durationMs`, `userId` (request-logger.middleware.ts:15-22), and the error log logs `{ err, requestId, method, path }` (error.middleware.ts:58). Consequently `req.headers.authorization` and `req.headers.cookie` never match anything today; they would become effective only if a `req` object (for instance via `pino-http`, which is installed but unused) were logged. The wildcard paths can match properties of the `err` object if an error carries `password`, `passwordHash`, `token` or `accessToken` as direct properties (e.g., `{ err: { token } }`), but not properties nested further (for example inside `err.meta` or `err.details`).

The names chosen align with the domain: `passwordHash` is the persisted user field, `password` is the login/register input, `accessToken` is the login response field, and `token` covers generic token payloads. The intent is coherent with the transcript concern about secrets leaking into logs (`TRANSCRICAO.md:132`). However, the JWT signing secret, `DATABASE_URL` (which embeds DB credentials, `.env.example:5`), and query strings inside `path` (`req.originalUrl`, which can include filter values such as e-mails) are not covered by any redaction path. Confidence on the effective-coverage analysis: High for current call sites; behaviour for future call sites depends on object shape.

**Rule workflow**:
```
logger.<level>(obj, msg)
  -> fast-redact checks each configured path against obj
     -> match: value replaced by '[REDACTED]' in output
     -> no match: value written as-is
Current effective matches: only first-level children of logged objects
(e.g. err.password, err.token) - none of the req.headers.* paths ever match.
```

---

### Business Rule: Base context and log format

**Overview**:
Every log line contains `service` and `env` fields, an ISO-8601 `time`, the numeric Pino `level`, `pid`/`hostname` are replaced by the custom base, and a `msg`.

**Detailed description**:
`base: { service: 'order-management-api', env: env.NODE_ENV }` (logger/index.ts:20) overrides Pino's default base (`pid`, `hostname`). As a result, log lines do not include the process id or host name; in multi-instance deployments, distinguishing instances depends on the log shipper adding host metadata. The service name is hard-coded and duplicates `package.json` `name`.

`timestamp: pino.stdTimeFunctions.isoTime` (line 21) writes `"time":"2026-11-02T15:13:00.000Z"`-style values instead of epoch milliseconds, which favors human readability and ingestion by systems that parse ISO dates. Levels remain numeric (no `formatters.level` is configured), so `level: 30` represents info, `50` error, `60` fatal. Messages follow a snake_case event-name convention for operational events (`http_request`, `server_started`, `shutdown_initiated`, `http_server_closed`, `bootstrap_failed`) with one exception: the error middleware uses the sentence `Unhandled error in request` (error.middleware.ts:59). This inconsistency means queries by event name must handle two styles.

Errors are passed under the `err` key in both error call sites (error.middleware.ts:58 and server.ts:25). Pino's default serializers serialize the `err` key with `pino-std-serializers` (type, message, stack, and enumerable own properties). Since `AppError` details and Prisma metadata are enumerable properties, they would be included when such errors reach the generic branch.

**Rule workflow**:
```
logger call -> merge { level, time(ISO), service, env } + user object + { msg }
  -> err key serialized by std err serializer
  -> redaction
  -> destination (pretty transport in development, stdout NDJSON otherwise)
```

---

### Business Rule: Environment-dependent output transport

**Overview**:
Human-readable, colorized output is used only in `development`; `test` and `production` emit raw JSON lines.

**Detailed description**:
`transport` (logger/index.ts:22-28) is set to `{ target: 'pino-pretty', options: { colorize: true, singleLine: false, translateTime: 'HH:MM:ss.l' } }` when `env.NODE_ENV === 'development'`, and `undefined` otherwise. `pino-pretty` is a devDependency (`package.json`, devDependencies `pino-pretty: 11.3.0`). Pino transports run in a worker thread, so writes in development are asynchronous relative to the main thread.

`NODE_ENV` defaults to `development` (env.ts:4) and `.env.example:1` also sets `development`. Therefore, a production deployment that forgets to set `NODE_ENV=production` will try to load `pino-pretty`; if devDependencies are pruned (typical for production images), the logger creation at import time would fail. Conversely, when `NODE_ENV` is correctly `production`, logs go synchronously to stdout as NDJSON, which is container-friendly.

The `translateTime: 'HH:MM:ss.l'` option only affects the pretty display; it shows time without date in development. In `test`, output is JSON on stdout interleaved with Vitest output. Whether Vitest sets `NODE_ENV=test` depends on the runner defaults when the variable is not already defined; the repository does not set it explicitly (vitest.config.ts, tests/setup.ts). Confidence: Medium on the effective `NODE_ENV` during tests.

**Rule workflow**:
```
NODE_ENV == 'development' ? pino-pretty worker transport (colorized, multi-line)
                          : default destination (stdout, NDJSON)
```

---

### Business Rule: Request id assignment and propagation

**Overview**:
Each HTTP request receives a correlation id, either taken from the caller's `X-Request-Id` header or generated as a UUID v4, stored on `req.id`, and returned in the `X-Request-Id` response header.

**Detailed description**:
`src/middlewares/request-logger.middleware.ts:6` reads `req.headers['x-request-id']` (Node lowercases header names) and casts it to `string | undefined`. If it is `undefined` (nullish), `uuidv4()` from `uuid@11.0.3` generates a new id. An empty string header (`X-Request-Id:`) is not nullish and is therefore accepted as an empty id. If the header is sent more than once, Node may expose a combined value; the TypeScript cast hides any non-string case. No validation of length, character set, or format is performed, so any client-provided value is trusted and written into logs and echoed back in the response header.

The id is stored in `req.id` (line 7). This property is declared through module augmentation of `express-serve-static-core` in `src/middlewares/auth.middleware.ts:12-17`, together with `req.user`. Placing the observability field in the auth middleware file couples the two concerns; `error.middleware.ts:56` does not rely on the augmentation and re-casts `req` as `{ id?: string }`, falling back to `'unknown'`. The header is set on the response before the route runs (line 8), so it is present on success and on errors handled by the error middleware, but it is absent when the request fails before `requestLogger` (body-parser errors, see section 2.2).

Propagation stops at the HTTP edge. The id appears in exactly two log events: `http_request` and `Unhandled error in request`. It is not added to a child logger, not stored in `AsyncLocalStorage`, not passed to services or repositories, not attached to Prisma queries, and not included in error response bodies (`error.middleware.ts:16-64` responses contain only `code`, `message`, `details`). Clients can still correlate through the response header. No W3C Trace Context (`traceparent`) or other tracing header is read or written.

**Rule workflow**:
```
incoming header x-request-id?
  -> present (any string, including empty): use as-is
  -> absent: uuid v4
req.id = requestId
response header X-Request-Id = requestId
used in: http_request log (finish), errorMiddleware error log (fallback 'unknown')
not used in: response body, services, repositories, Prisma, outgoing calls
```

---

### Business Rule: HTTP access log (`http_request`)

**Overview**:
Exactly one `info`-level structured log is written for every response that emits Node's `finish` event, with request id, method, path, status, latency and authenticated user id.

**Detailed description**:
At `request-logger.middleware.ts:10`, `process.hrtime.bigint()` captures a monotonic nanosecond start. On `res.on('finish')` (line 12), the elapsed nanoseconds are converted to milliseconds (`/ 1_000_000`, line 13) and rounded to two decimals via `Number(durationMs.toFixed(2))` (line 20). The latency includes time spent in all downstream middlewares, controllers, database access and response writing, but excludes JSON body parsing, which happens before the middleware.

The fields logged are: `requestId`, `method` (`req.method`), `path` (`req.originalUrl`, which includes the query string and the `/api/v1` prefix), `statusCode` (`res.statusCode`), `durationMs`, and `userId` (`req.user?.id`). Because the listener runs after the route chain, `req.user` is populated whenever `authenticate` succeeded for that request (auth.middleware.ts:42); for public routes (`/health`, register/login) and failed authentication, `userId` is `undefined` and Pino omits it from the JSON. User e-mail and role are not logged. No request/response body, size, user agent, remote IP or route template is logged; this limits cardinality-friendly aggregation by route (paths contain UUIDs).

The level is always `info`, regardless of status code: 4xx and 5xx responses produce the same level as 2xx, so level-based alerting cannot distinguish failures; filtering must use `statusCode`. Requests where the client aborts before the response finishes emit `close` but not `finish` and are not logged. `/health` requests are logged like any other, which can add volume under frequent probes. The message key `http_request` is a stable event name suitable for querying.

**Rule workflow**:
```
requestLogger -> t0 = hrtime
... route chain ...
res 'finish' -> durationMs = round2((hrtime - t0)/1e6)
  -> logger.info({ requestId, method, path: originalUrl, statusCode, durationMs, userId? }, 'http_request')
res 'close' without 'finish' -> nothing logged
```

---

### Business Rule: Error logging policy in the centralized error middleware

**Overview**:
Expected, classified errors are translated into HTTP responses without being logged; only unclassified errors are logged at `error` level and mapped to a generic 500.

**Detailed description**:
`src/middlewares/error.middleware.ts:14-54` handles four expected categories without logging: `AppError` subclasses (status from `err.statusCode`, body `code`/`message`/`details`), `ZodError` (400 `VALIDATION_ERROR` with formatted issues), Prisma `P2002` (409 `CONFLICT`, unique constraint, message includes target fields) and Prisma `P2025` (404 `NOT_FOUND`). These outcomes remain visible only through the `http_request` access log (status code and latency), without error code or cause. For example, a 409 invalid status transition or 422 insufficient stock in orders is not distinguishable in logs from other 409/422 responses except by path.

Every other error, including Prisma known errors with other codes, Prisma initialization/connection errors, programming errors, and body-parser errors, reaches lines 56-60: `logger.error({ err, requestId, method: req.method, path: req.originalUrl }, 'Unhandled error in request')`. The `err` key is serialized with stack and properties. The response is a generic `{ error: { code: 'INTERNAL_SERVER_ERROR', message: 'Internal server error' } }` with status 500 (lines 62-64), so internal details are kept in logs and not leaked to clients. The request id is not included in this response body, though it is available in the response header when `requestLogger` ran.

A consequence of the policy is that a single unexpected failure produces two lines: the `error` line from the middleware and the `info` `http_request` line with `statusCode: 500`, both sharing `requestId` (unless the failure happened before `requestLogger`, in which case only the error line exists with `requestId: 'unknown'`). Body-parser errors such as invalid JSON (which carry `status: 400`) are reported as 500 and logged as unhandled errors, inflating error-level log volume with client errors. Confidence: High.

**Rule workflow**:
```
err ->
  AppError       -> status err.statusCode, no log
  ZodError       -> 400, no log
  Prisma P2002   -> 409, no log
  Prisma P2025   -> 404, no log
  otherwise      -> logger.error({ err, requestId|'unknown', method, path }, 'Unhandled error in request')
                    -> 500 generic body
```

---

### Business Rule: Process lifecycle logging and graceful shutdown

**Overview**:
The server logs start, shutdown initiation, HTTP server closure and fatal bootstrap failure.

**Detailed description**:
`src/server.ts:9-11` logs `server_started` with `port` and `env` once `app.listen` is ready. `shutdown(signal)` (lines 13-18) is registered for `SIGINT` and `SIGTERM` (lines 20-21); it logs `shutdown_initiated` with the signal, calls `server.close()` with a callback that logs `http_server_closed`, awaits `prisma.$disconnect()`, and then calls `process.exit(0)`.

Because `process.exit(0)` is called right after the Prisma disconnect and does not wait for `server.close` to complete (in-flight connections drain asynchronously), the `http_server_closed` line may never be written, and in-flight requests may be cut without their `http_request` line. In development, where logs go through a worker-thread transport, `process.exit` can additionally drop buffered log lines. In non-development environments the default Pino stdout destination is synchronous, which mitigates loss for the lines already emitted.

`bootstrap().catch` (lines 24-27) logs `bootstrap_failed` at `fatal` with `err` and exits with code 1. Note that configuration errors in `env.ts` are reported before the logger exists, via `console.error` (env.ts:21), and therefore are plain text, not JSON with `service`/`env`. No handlers exist for `uncaughtException` or `unhandledRejection`, so crashes outside the request chain are reported by Node's default stderr output, not by Pino.

**Rule workflow**:
```
listen ok        -> info server_started {port, env}
SIGINT|SIGTERM   -> info shutdown_initiated {signal}
                 -> server.close(cb: info http_server_closed)  [may not run]
                 -> await prisma.$disconnect() -> exit(0)
bootstrap reject -> fatal bootstrap_failed {err} -> exit(1)
env invalid      -> console.error text -> exit(1) (before logger exists)
```

---

### Business Rule: Prisma and other non-Pino output

**Overview**:
Database client logging and some scripts bypass Pino.

**Detailed description**:
`src/config/database.ts:6` configures Prisma's own logging: `['warn', 'error']` in development and `['error']` in other environments. These messages are written by Prisma directly to stdout/stderr, without the Pino format, base fields, redaction, or request id. Query logging (`query` level) is never enabled, so slow-query visibility does not exist.

`prisma/seed.ts` (lines 180-330) uses `console.log` for progress and `console.error` for failures. It is a CLI script run with `npm run db:seed`, outside the HTTP runtime, so this is not a runtime observability concern but shows that the Pino standard is not used project-wide.

The ESLint rule `no-console` (warn, allowing `warn` and `error`) in `.eslintrc.json` nudges developers away from `console.log` but still permits `console.error`/`console.warn` outside Pino. `env.ts:20` explicitly disables the rule for its single `console.error`.

**Rule workflow**:
```
Prisma internal events -> Prisma logger -> stdout/stderr (unstructured)
Seed script            -> console.*     -> stdout/stderr
Runtime app events     -> Pino           -> structured JSON
```

---

### Business Rule: Absence of metrics, tracing and audit logging

**Overview**:
The component provides logs only. No metrics, distributed tracing, or business audit logging are implemented.

**Detailed description**:
A full search of `src/`, `tests/` and `prisma/` finds no imports of metrics or tracing libraries (no `prom-client`, `@opentelemetry/*`, `dd-trace`, StatsD clients), no `/metrics` endpoint, no `traceparent` handling, and no span creation. Dependencies in `package.json` confirm this: the only observability-related runtime packages are `pino`, `pino-http` (unused) and `uuid`. Latency exists only as a per-request log field (`durationMs`), so percentiles and rates must be derived by a log backend.

`GET /health` (src/app.ts:62-64) always returns `200 { status: 'ok' }`; it does not check database connectivity, so it is a liveness signal, not readiness. It is mounted after `requestLogger` and is therefore access-logged.

Business events (user registration, login success or failure, order creation, status transitions, stock changes, deletions) produce no log lines in any module under `src/modules/`. Traceability of who changed an order exists only as persisted data (`createdById` and `changedById` in `src/modules/orders/order.service.ts:104,110,164`). The meeting transcript requires audit logging for a future admin replay endpoint (`TRANSCRICAO.md:210`) and the challenge README asks for an observability section covering metrics, logs and tracing (`README.md:117,209`); these are requirements for upcoming design work, not current behaviour. Confidence: High for absence.

**Rule workflow**:
```
Metrics: none
Tracing: none
Audit:   none in logs; DB columns createdById / changedById only
Health:  static liveness at /health
```

---

### Business Rule: Architectural decision to reuse Pino

**Overview**:
The team decision recorded in the transcript is to reuse the existing Pino logger and add no new logging tooling.

**Detailed description**:
`TRANSCRICAO.md:174` states that the logger is Pino, already used across the project, and nothing new will be added. `TRANSCRICAO.md:180` and `:282` record the decision of maximum reuse, listing Pino among reused patterns (AppError, error middleware, module pattern, Zod schemas, error code pattern).

This decision constrains future features (such as a webhooks module) to use the singleton `logger` exported by `src/shared/logger/index.ts`, its redaction list and its base fields. Since the current logger has no child-logger or context mechanism, any per-request or per-job correlation in future modules (for example, a polling worker) would need to pass ids explicitly within the existing pattern.

The transcript statement "already in the whole project" is only partially reflected in code: Pino is imported in three files (`server.ts`, `error.middleware.ts`, `request-logger.middleware.ts`), and no module service uses it. Confidence: High.

**Rule workflow**:
```
New feature logging -> import { logger } from 'src/shared/logger/index.js'
                    -> inherits level, redaction, base, format
```

---

## 4. Component Structure

```
src/
├── shared/
│   └── logger/
│       └── index.ts                      # Pino factory (createLogger) and singleton (logger); level, redaction, base, timestamp, transport
├── middlewares/
│   ├── request-logger.middleware.ts      # Request id (X-Request-Id), latency, 'http_request' access log
│   ├── error.middleware.ts               # Logs unhandled errors at 'error' with requestId (consumer)
│   └── auth.middleware.ts                # Declares req.id and req.user via module augmentation (lines 12-17); sets req.user used in access log
├── config/
│   ├── env.ts                            # LOG_LEVEL and NODE_ENV validation; console.error on invalid env
│   └── database.ts                       # Prisma native log levels per environment
├── app.ts                                # Middleware order: express.json -> requestLogger -> /health -> /api/v1 -> 404 -> errorMiddleware
└── server.ts                             # Lifecycle logs: server_started, shutdown_initiated, http_server_closed, bootstrap_failed

Configuration / tooling:
├── .env.example                          # NODE_ENV=development, LOG_LEVEL=info
├── .eslintrc.json                        # no-console rule
└── package.json                          # pino 9.5.0, pino-http 10.3.0 (unused), uuid 11.0.3, pino-pretty 11.3.0 (dev)
```

---

## 5. Dependency Analysis

```
Internal Dependencies:
shared/logger/index.ts            -> config/env.ts (LOG_LEVEL, NODE_ENV)
middlewares/request-logger        -> shared/logger, uuid
                                  -> (type) auth.middleware augmentation for req.id / req.user
middlewares/error.middleware      -> shared/logger, shared/errors (AppError), zod, @prisma/client
server.ts                         -> shared/logger, config/env, config/database, app
app.ts                            -> middlewares/request-logger, middlewares/error.middleware
config/database.ts                -> config/env (NODE_ENV for Prisma log levels)

External Dependencies:
- pino 9.5.0          - structured logger (runtime)
- pino-pretty 11.3.0  - development transport (devDependency, loaded dynamically by target name)
- pino-http 10.3.0    - declared runtime dependency, not imported anywhere in src/
- uuid 11.0.3         - request id generation (v4)
- express 4.21.1      - middleware host, 'finish' event, headers
- zod 3.23.8          - validation of LOG_LEVEL / NODE_ENV
- @prisma/client 5.22.0 - separate native logging channel
- Node.js >= 20       - process.hrtime.bigint, process signals
```

---

## 6. Afferent and Efferent Coupling

| Component | Afferent Coupling | Efferent Coupling | Critical |
|-----------|-------------------|-------------------|----------|
| `logger` singleton (src/shared/logger/index.ts) | 3 (request-logger.middleware, error.middleware, server.ts) | 2 (pino, config/env) | High (every log line and redaction policy depend on it; created at import time) |
| `createLogger` function | 1 (same module, line 32) | 2 (pino, env) | Low |
| `requestLogger` middleware | 1 (app.ts) | 3 (logger, uuid, Express types incl. augmentation) | Medium (sole source of request id and access log) |
| `errorMiddleware` (logging branch) | 1 (app.ts) | 5 (logger, AppError, ZodError, Prisma, Express) | High (sole source of error-level request logs) |
| `Request` augmentation (`id`, `user`) in auth.middleware.ts | 3 (request-logger, auth.middleware, user-related controllers via req.user) | 1 (express-serve-static-core) | Medium (observability field defined in auth file) |
| `env` (LOG_LEVEL, NODE_ENV) | 4 relevant to observability (logger, database, server, auth) | 1 (zod) | High (invalid value stops the process) |
| `server.ts` bootstrap | 0 (entry point) | 4 (app, env, prisma, logger) | Medium |

Counts reflect import relationships for the observability concern found in `src/`.

---

## 7. Endpoints

The component itself does not define business endpoints. It instruments all routes and is the only owner of the following HTTP contract elements:

| Element | Type | Description |
|---------|------|-------------|
| `X-Request-Id` | Request header (optional) | Caller-provided correlation id; accepted without validation |
| `X-Request-Id` | Response header | Always set for requests that reach `requestLogger` |
| `/health` | GET | Static liveness endpoint (`src/app.ts:62-64`), access-logged, no dependency checks |

There is no `/metrics` or tracing endpoint.

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| stdout (non-development) | Output stream | Primary log sink for container/log shippers | Process stdout | NDJSON (Pino) | None; synchronous default destination |
| pino-pretty transport (development) | Worker-thread transport | Human-readable console output | In-process worker | Colorized text | None; module must be installed or logger creation fails |
| HTTP clients / gateways | External callers | Provide and receive `X-Request-Id` | HTTP header | String | No validation of incoming value |
| Prisma native logger | Library output | DB warnings/errors | stdout/stderr | Prisma text format | Independent of Pino |
| Environment variables | Configuration | `LOG_LEVEL`, `NODE_ENV` | Process env | Strings validated by Zod | `console.error` + exit(1) |

No integration with log aggregation, APM, metrics, or tracing backends exists in code.

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Module-level Singleton | `export const logger = createLogger()` | src/shared/logger/index.ts:32 | One shared logger configuration |
| Factory Function | `createLogger()` | src/shared/logger/index.ts:13-30 | Encapsulates Pino options (not used elsewhere, e.g., in tests) |
| Middleware / Chain of Responsibility | `requestLogger`, `errorMiddleware` | src/middlewares/*.ts; src/app.ts:60,73 | Cross-cutting instrumentation |
| Correlation Identifier | `X-Request-Id` read-or-generate and echo | request-logger.middleware.ts:6-8 | Request correlation across client and logs |
| Event-driven completion hook | `res.on('finish')` | request-logger.middleware.ts:12 | Log after status is known |
| Structured Logging | Object-first log calls with snake_case event messages | request-logger, server.ts | Machine-queryable logs |
| Centralized Error Handling | Single error middleware logging only unknown errors | error.middleware.ts | Single place for error logging and response masking |
| Declaration Merging (TS) | `declare module 'express-serve-static-core'` | auth.middleware.ts:12-17 | Typed `req.id` and `req.user` |
| Environment-based Configuration | Transport and Prisma log levels by `NODE_ENV` | logger/index.ts:22-28; database.ts:6 | Different output per environment |
| Fail-fast Configuration | Zod env schema with exit(1) | env.ts:14-23 | Prevent running with invalid log level |

Architectural decisions observed:
- Hand-written access logging instead of the installed `pino-http`.
- Correlation limited to HTTP edge (no context propagation).
- Expected errors not logged; unexpected errors logged with stack.
- Reuse of Pino as the project-wide standard (TRANSCRICAO.md:174,180).

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| High | Observability scope | No metrics and no tracing (no instrumentation, no `/metrics`, no trace context) | No rate/error/latency dashboards or alerting without a log backend deriving them; no cross-service tracing |
| High | request-logger.middleware.ts:6 | Incoming `X-Request-Id` trusted without length/format validation; cast hides non-string values | Log forging/pollution, oversized header values echoed and logged, correlation spoofing |
| Medium | app.ts:59-60 | `express.json` runs before `requestLogger` | Malformed/oversized bodies: no access log, no `X-Request-Id`, error logged with `requestId: 'unknown'` |
| Medium | error.middleware.ts:56-64 | Body-parser errors (status 400) fall into generic branch | Client errors reported as 500 and logged at `error`, distorting error rates |
| Medium | request-logger.middleware.ts:14 | Access log level always `info` regardless of status | Level-based alerting cannot detect 5xx/4xx |
| Medium | error.middleware.ts:15-54 | Handled errors (AppError, Zod, Prisma P2002/P2025) not logged with code | Business failures (e.g., invalid transitions, stock shortage) invisible beyond status code |
| Medium | Correlation | No child logger / AsyncLocalStorage; requestId not passed to services or DB | Future logs inside services cannot be correlated to requests |
| Medium | logger/index.ts:4-11 | `req.headers.*` redaction paths never match current call sites; wildcards only one level deep; query strings in `path` not redacted | False sense of protection; possible leakage of sensitive values in nested error properties or URLs |
| Medium | logger/index.ts:22-28 + env.ts:4 | `NODE_ENV` defaults to `development`, which requires devDependency `pino-pretty` | Process may fail at import in production if `NODE_ENV` is unset and devDependencies are pruned |
| Medium | server.ts:15-17 | `process.exit(0)` does not wait for `server.close` | Lost `http_server_closed` and in-flight access logs; possible log loss with async transport |
| Medium | server.ts | No `uncaughtException`/`unhandledRejection` handlers | Crashes outside request chain not logged in structured format |
| Medium | Business modules | No audit/business event logging (login failures, status changes, deletions) | Security investigations and auditing rely solely on DB columns; conflicts with stated audit requirement for admin actions (TRANSCRICAO.md:210) |
| Low | package.json | `pino-http` declared but unused | Unnecessary dependency surface |
| Low | logger/index.ts:20 | `base` overrides `pid`/`hostname`; service name hard-coded | Instance identification depends on infrastructure; duplication with package name |
| Low | Message naming | `Unhandled error in request` vs snake_case events elsewhere | Inconsistent event queries |
| Low | auth.middleware.ts:12-17 | `req.id` declared in auth file; error middleware re-casts instead of using augmentation | Cohesion issue between auth and observability |
| Low | request-logger.middleware.ts:12 | Aborted requests (no `finish`) are not logged | Missing visibility into client disconnects/timeouts |
| Low | app.ts:62-64 | `/health` static and access-logged | No readiness signal (DB); log noise from probes |
| Low | config/database.ts:6; env.ts:21; prisma/seed.ts | Output channels outside Pino | Non-uniform, non-structured log lines |
| Low | env.ts:6 | `silent` not an allowed level | Tests cannot silence logs via configuration |

---

## 11. Test Coverage Analysis

Test files located: `tests/auth.test.ts` (7 tests), `tests/orders.test.ts` (8 tests), `tests/setup.ts` (DB lifecycle hooks), `tests/helpers/factories.ts` (app builder and data factories). Configuration: `vitest.config.ts` (`include: tests/**/*.test.ts`, single fork, no coverage configuration). No coverage report exists in the repository (`coverage/` is gitignored).

| Component | Unit Tests | Integration Tests | Coverage | Test Quality |
|-----------|------------|-------------------|----------|--------------|
| shared/logger (createLogger, redaction, base, transport) | 0 | 0 direct (logger is loaded indirectly through `buildApp`) | Not measured; behaviour not asserted | No assertions on level, redaction, base fields or format |
| request-logger.middleware (request id, header, access log) | 0 | Executed indirectly by all 15 Supertest requests (tests/auth.test.ts, tests/orders.test.ts) | Lines executed, not asserted | No test checks `X-Request-Id` response header, propagation of a provided id, or log content |
| error.middleware logging branch (unhandled errors) | 0 | 0 (all tests exercise AppError/Zod paths: 400, 401, 409, 422) | Generic 500/log branch not exercised | Logging of unexpected errors untested |
| server.ts lifecycle logs | 0 | 0 (tests use `buildApp` via `getTestApp`, tests/helpers/factories.ts:10-15, not `server.ts`) | 0% | Startup, shutdown and fatal paths untested |
| env.ts LOG_LEVEL validation | 0 | 0 | Default path only | No tests for invalid or alternative levels |

Observations:
- No test uses `vi.mock`, spies, or a test destination for the logger; logs from tests go to stdout at the configured level.
- `npm test` (`vitest run`) does not load an env file; `LOG_LEVEL` and `NODE_ENV` used in tests depend on the shell environment. Confidence on effective test-time values: Medium.
- Overall, observability behaviour has no direct automated verification. This is a coverage risk for the redaction policy in particular.

---

**Component analyzed:** Observability
**Report file:** docs/contexto/analise-codigo/component-deep-analyzer/component-analysis-Observability-2026-11-02-1513.md
