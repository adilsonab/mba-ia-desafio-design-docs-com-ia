# Component Deep Analysis Report

**Component:** ErrorHandling
**Files in scope:** `src/shared/errors/app-error.ts`, `src/shared/errors/http-errors.ts`, `src/shared/errors/index.ts`, `src/middlewares/error.middleware.ts`
**Project:** Order Management API (Express 4.21.1 + Prisma 5.22.0 + Zod 3.23.8 + Pino 9.5.0, TypeScript ESM)
**Analysis date:** 2026-11-02
**Excluded folders:** node_modules, dist, .git, docs

---

## 1. Executive Summary

The ErrorHandling component is the cross-cutting error model and the single HTTP error translation point of the API. It has two parts:

1. **A typed error hierarchy** (`src/shared/errors/`) built on one base class, `AppError`. It carries three things besides the message: an HTTP `statusCode`, a machine-readable `errorCode` (UPPER_SNAKE_CASE), and optional structured `details`. Nine concrete subclasses cover HTTP 400, 401, 403, 404, 409 and 422, plus two domain-specific errors (`InvalidStatusTransitionError`, `InsufficientStockError`).
2. **A terminal Express error middleware** (`src/middlewares/error.middleware.ts`). It turns any error passed to `next(err)` into a uniform JSON envelope `{ "error": { "code", "message", "details?" } }`. It handles four kinds of error in order: `AppError`, `ZodError`, Prisma known request errors (only `P2002` and `P2025`), and a catch-all 500 that is logged.

Service, controller and middleware code across every business module (auth, users, customers, products, orders) and the app bootstrap use the component. Fourteen distinct error codes reach clients. Nine are defined in the hierarchy or middleware as defaults. Five more are domain codes passed as constructor arguments by services (`EMAIL_ALREADY_USED`, `SKU_ALREADY_USED`, `INACTIVE_PRODUCT`, `INVALID_ORDER_STATE_FOR_DELETE`, plus `INVALID_STATUS_TRANSITION` raised a second way).

**Key findings**

- The design is simple, cohesive and has no dependencies inside the hierarchy (the errors module imports nothing outside itself). Coupling to it is high: 11 source files depend on it.
- Only the 500 path is logged by the error middleware. 4xx responses are visible only through the generic `http_request` access log line written by `request-logger.middleware.ts`.
- Several common error sources reach the 500 catch-all even though they should be client errors:
  - Body-parser `SyntaxError` for malformed JSON (should be 400).
  - `PayloadTooLargeError` for bodies over 1mb (should be 413).
  - Prisma `P2003` foreign-key violations, e.g. deleting a customer or product that is referenced by orders (should be 409).
  - Other Prisma codes.
- The middleware ignores `res.headersSent` and never calls `next(err)` (the `_next` parameter is unused), so an error raised after streaming has started cannot be handed to Express's default handler.
- `BadRequestError`, and the default codes `CONFLICT` (as a class default) and `UNPROCESSABLE_ENTITY`, are defined but never used in `src/`.
- The `ZodError` branch in the middleware cannot be reached through the current code paths, because `validate.middleware.ts` already converts `ZodError` into `ValidationError`.
- The project has no unit tests for the component. Integration tests in `tests/auth.test.ts` and `tests/orders.test.ts` check the envelope and the codes for 7 of the 14 error codes.

---

## 2. Data Flow Analysis

### 2.1 Error production and propagation

```
1. Request enters Express app (src/app.ts:56)
   -> express.json({ limit: '1mb' }) (src/app.ts:59)      [may raise SyntaxError / PayloadTooLargeError]
   -> requestLogger assigns req.id, sets X-Request-Id (src/middlewares/request-logger.middleware.ts:6-8)
2. Route-level middlewares
   -> authenticate / requireRole (src/middlewares/auth.middleware.ts:26-61)
        next(new UnauthorizedError(...)) | next(new ForbiddenError(...))
   -> validate({ body|query|params }) (src/middlewares/validate.middleware.ts:11-37)
        ZodError -> next(new ValidationError('Validation failed', details[]))
        other    -> next(err)
3. Controllers (src/modules/*/*.controller.ts)
   -> try { await service.x() } catch (err) { next(err) }   (manual async forwarding, Express 4)
   -> some controllers throw UnauthorizedError when req.user is missing (auth.controller.ts:32, order.controller.ts:30,40)
4. Services (src/modules/*/*.service.ts)
   -> throw NotFoundError / ConflictError / ValidationError / UnprocessableEntityError /
      InvalidStatusTransitionError / InsufficientStockError / UnauthorizedError
   -> Prisma calls may raise PrismaClientKnownRequestError (P2002, P2025, P2003, ...)
5. Unmatched routes
   -> fallback handler next(new NotFoundError(`Route ${method} ${url}`)) (src/app.ts:69-71)
6. errorMiddleware (registered last, src/app.ts:73) classifies err:
   a. AppError                         -> res.status(err.statusCode) + envelope (error.middleware.ts:15-24)
   b. ZodError                         -> 400 VALIDATION_ERROR + formatted issues (error.middleware.ts:26-35)
   c. Prisma P2002                     -> 409 CONFLICT, message names unique target (error.middleware.ts:37-47)
   d. Prisma P2025                     -> 404 NOT_FOUND "Resource not found" (error.middleware.ts:48-53)
   e. Anything else                    -> logger.error(...) + 500 INTERNAL_SERVER_ERROR (error.middleware.ts:56-64)
7. Response 'finish' event -> requestLogger writes info-level "http_request" with statusCode (request-logger.middleware.ts:12-25)
```

### 2.2 Response envelope

All error responses produced by this component share this shape:

```json
{
  "error": {
    "code": "UPPER_SNAKE_CASE_CODE",
    "message": "Human readable message",
    "details": "<optional: object or array>"
  }
}
```

- `details` is included only when `err.details !== undefined` (error.middleware.ts:20). It is never included for the Prisma-mapped or 500 responses.
- Success responses do not use an envelope. They return the resource directly or `{ data, pagination }` (`src/shared/http/response.ts`). Error and success shapes are therefore different by design.

---

## 3. Business Rules & Logic

### Overview of the business rules

| Rule Type | Rule Description | Location |
|-----------|------------------|----------|
| Error Model | Every application error carries `statusCode`, `errorCode`, optional `details`; `name` is fixed to `AppError` | src/shared/errors/app-error.ts:3-16 |
| Error Model | `details` type is restricted to `Record<string, unknown> \| unknown[] \| undefined` | src/shared/errors/app-error.ts:1 |
| HTTP Mapping | `BadRequestError` -> 400, default code `BAD_REQUEST` (overridable) | src/shared/errors/http-errors.ts:3-7 |
| HTTP Mapping | `ValidationError` -> 400, fixed code `VALIDATION_ERROR` | src/shared/errors/http-errors.ts:9-13 |
| HTTP Mapping | `UnauthorizedError` -> 401, fixed code `UNAUTHORIZED`, no details | src/shared/errors/http-errors.ts:15-19 |
| HTTP Mapping | `ForbiddenError` -> 403, fixed code `FORBIDDEN`, no details | src/shared/errors/http-errors.ts:21-25 |
| HTTP Mapping | `NotFoundError` -> 404, fixed code `NOT_FOUND`, message `"<resource> not found"` | src/shared/errors/http-errors.ts:27-31 |
| HTTP Mapping | `ConflictError` -> 409, default code `CONFLICT` (overridable), message mandatory | src/shared/errors/http-errors.ts:33-37 |
| HTTP Mapping | `UnprocessableEntityError` -> 422, default code `UNPROCESSABLE_ENTITY` (overridable), message mandatory | src/shared/errors/http-errors.ts:39-43 |
| Domain Error | Invalid order status transition -> 409 `INVALID_STATUS_TRANSITION` with `{from,to}` | src/shared/errors/http-errors.ts:45-53 |
| Domain Error | Insufficient stock -> 422 `INSUFFICIENT_STOCK` with `{unavailable:[{sku,requested,available}]}` | src/shared/errors/http-errors.ts:55-63 |
| Naming Convention | Error codes are UPPER_SNAKE_CASE; generic codes mirror HTTP reason phrase; domain codes are `<SUBJECT>_<CONDITION>` | http-errors.ts, services |
| Response Format | Uniform envelope `{error:{code,message,details?}}` | src/middlewares/error.middleware.ts:16-22 |
| Response Format | `details` omitted when undefined | src/middlewares/error.middleware.ts:20 |
| Zod Mapping | `ZodError` -> 400 `VALIDATION_ERROR`, details `[{path,message}]`, empty path rendered as `(root)` | src/middlewares/error.middleware.ts:7-12, 26-35 |
| Zod Mapping (upstream) | `validate()` converts ZodError to `ValidationError` with the same details format | src/middlewares/validate.middleware.ts:26-32 |
| Prisma Mapping | `P2002` unique violation -> 409 `CONFLICT`, message lists `meta.target` columns | src/middlewares/error.middleware.ts:38-47 |
| Prisma Mapping | `P2025` record not found -> 404 `NOT_FOUND`, `"Resource not found"` | src/middlewares/error.middleware.ts:48-53 |
| Fallback | Any other error -> 500 `INTERNAL_SERVER_ERROR`, generic message, no internals leaked | src/middlewares/error.middleware.ts:62-64 |
| Logging | Only fallback errors are logged at `error` level with `err`, `requestId`, `method`, `path` | src/middlewares/error.middleware.ts:56-60 |
| Logging | Missing `req.id` logged as `"unknown"` | src/middlewares/error.middleware.ts:56 |
| Logging | Logger redacts authorization/cookie headers, password, passwordHash, token, accessToken | src/shared/logger/index.ts:4-11 |
| Routing | Unmatched routes -> `NotFoundError("Route <METHOD> <URL>")` -> 404 `NOT_FOUND` | src/app.ts:69-71 |
| Propagation | Async controllers must catch and forward errors via `next(err)` (Express 4) | src/modules/*/*.controller.ts |
| Security | Login failures use identical `"Invalid credentials"` for unknown email and wrong password | src/modules/auth/auth.service.ts:34,38 |

### Complete inventory of error codes used across `src/`

| Code | HTTP | Raised by / defined at | Usage sites (file:line) |
|------|------|------------------------|-------------------------|
| `BAD_REQUEST` | 400 | `BadRequestError` default, http-errors.ts:4 | None (class unused) |
| `VALIDATION_ERROR` | 400 | `ValidationError` http-errors.ts:11; middleware literal error.middleware.ts:29 | validate.middleware.ts:31 (Zod issues); order.service.ts:52 (empty items, no details); order.service.ts:88 (discount > subtotal, details `[{path:'discountCents',...}]`) |
| `UNAUTHORIZED` | 401 | `UnauthorizedError` http-errors.ts:17 | auth.middleware.ts:30, 36, 45, 52; auth.controller.ts:32; auth.service.ts:34, 38; order.controller.ts:30, 40 |
| `FORBIDDEN` | 403 | `ForbiddenError` http-errors.ts:23 | auth.middleware.ts:56 |
| `NOT_FOUND` | 404 | `NotFoundError` http-errors.ts:29; middleware P2025 literal error.middleware.ts:50 | app.ts:70 (route); customer.service.ts:25; product.service.ts:26; user.service.ts:38; order.service.ts:46, 60 (Customer), 64 (Product), 136, 183 |
| `CONFLICT` | 409 | `ConflictError` default http-errors.ts:34; middleware P2002 literal error.middleware.ts:42 | Only via Prisma P2002 mapping (no service uses the class default) |
| `EMAIL_ALREADY_USED` | 409 | `ConflictError` code argument | customer.service.ts:32, 48; user.service.ts:24 |
| `SKU_ALREADY_USED` | 409 | `ConflictError` code argument | product.service.ts:33, 50 |
| `INVALID_STATUS_TRANSITION` | 409 | `InvalidStatusTransitionError` http-errors.ts:49; also direct `ConflictError` | order.service.ts:143 (same-status, message "Order is already in X status"); order.service.ts:148 (disallowed transition) |
| `INVALID_ORDER_STATE_FOR_DELETE` | 409 | `ConflictError` code argument | order.service.ts:187 (details `{status}`) |
| `UNPROCESSABLE_ENTITY` | 422 | `UnprocessableEntityError` default http-errors.ts:40 | None |
| `INACTIVE_PRODUCT` | 422 | `UnprocessableEntityError` code argument | order.service.ts:70 (details `{skus:[...]}`) |
| `INSUFFICIENT_STOCK` | 422 | `InsufficientStockError` http-errors.ts:59 | order.service.ts:223 (details `{unavailable:[...]}`) |
| `INTERNAL_SERVER_ERROR` | 500 | middleware literal error.middleware.ts:63 | Any unclassified error |

### Detailed breakdown of the business rules

---

### Business Rule: AppError base contract

**Overview**:
Every intentional, client-facing error in the application is an instance of `AppError` (src/shared/errors/app-error.ts:3-16). It extends the native `Error` and adds three readonly properties: `statusCode`, `errorCode` and `details`.

**Detailed description**:
The constructor takes `(message, statusCode, errorCode, details?)`. The message goes to `super(message)`, so it becomes the standard `Error.message`, and the middleware returns it to the client unchanged. Because of this, every message written in a service is public text. The `statusCode` is the HTTP status the middleware will use without further mapping, so the error class alone decides the HTTP semantics. `errorCode` is a free-form string, and the convention (see the naming rule) keeps it in UPPER_SNAKE_CASE.

`details` is typed as `ErrorDetails = Record<string, unknown> | unknown[] | undefined` (app-error.ts:1). Primitive values are not allowed, so `details` is always an object or an array that clients can parse. The project uses three shapes: an array of `{path, message}` for validation, an object such as `{from, to}`, `{status}` or `{skus}` for conflicts, and an object wrapping an array (`{unavailable: [...]}`) for stock errors.

`this.name` is always set to `'AppError'` (app-error.ts:10), including in subclasses. Stack traces and log output therefore show `AppError` and not the concrete subclass name. `Error.captureStackTrace?.(this, this.constructor)` (app-error.ts:14) uses optional chaining, so it runs only on V8. It removes the constructor frame from the stack. All properties are `readonly`, which keeps error instances immutable after construction.

**Rule workflow**:
```
service/middleware detects condition
  -> new <Subclass>(...) -> AppError(message, statusCode, errorCode, details)
  -> throw / next(err)
  -> errorMiddleware: err instanceof AppError -> res.status(statusCode).json({error:{code:errorCode, message, details?}})
```

---

### Business Rule: HTTP status mapping by error class

**Overview**:
Each subclass in src/shared/errors/http-errors.ts fixes one HTTP status. The class hierarchy is the single source of truth for which status a domain condition produces.

**Detailed description**:
There are seven generic classes:

- `BadRequestError` (400, line 3)
- `ValidationError` (400, line 9)
- `UnauthorizedError` (401, line 15)
- `ForbiddenError` (403, line 21)
- `NotFoundError` (404, line 27)
- `ConflictError` (409, line 33)
- `UnprocessableEntityError` (422, line 39)

There are two domain classes. `InvalidStatusTransitionError` extends `ConflictError` (409, line 45). `InsufficientStockError` extends `UnprocessableEntityError` (422, line 55). Because the domain classes inherit from the generic ones, `instanceof ConflictError` is also true for transition errors. No code in `src/` relies on that, but it keeps the model consistent.

The constructor signatures control how much a caller can customize:

- `UnauthorizedError` and `ForbiddenError` take only a message. Their code is fixed and they have no details.
- `NotFoundError` takes only a resource name and builds the message `"${resource} not found"`, for example `"Order not found"`. Its code is always `NOT_FOUND` and it has no details.
- `ValidationError` takes a message and details, with the code fixed to `VALIDATION_ERROR`.
- `BadRequestError`, `ConflictError` and `UnprocessableEntityError` accept a custom code as their second argument. These three are the extension points that services use to create domain codes without adding new classes. For `ConflictError` and `UnprocessableEntityError` the message is required.

The project uses the 409 and 422 statuses with distinct meanings. 409 Conflict covers state or uniqueness conflicts with existing data: duplicate email or SKU, invalid status transition, and deleting an order in a non-deletable state. 422 Unprocessable Entity covers a request that is well formed and refers to existing entities but breaks a business constraint about those entities: inactive products in the order, or not enough stock when paying. 400 is reserved for input shape and arithmetic validation: Zod failures, an empty item list, and a discount larger than the subtotal.

**Rule workflow**:
```
Condition type                         -> Class                         -> Status
Input schema / arithmetic invalid      -> ValidationError               -> 400
Missing/invalid credentials or token   -> UnauthorizedError             -> 401
Authenticated but wrong role           -> ForbiddenError                -> 403
Entity or route not found              -> NotFoundError                 -> 404
Uniqueness / state conflict            -> ConflictError (+subclass)     -> 409
Business constraint on valid entities  -> UnprocessableEntityError (+subclass) -> 422
Unknown                                -> (middleware fallback)         -> 500
```

---

### Business Rule: Error code naming pattern

**Overview**:
Error codes are machine-readable UPPER_SNAKE_CASE strings that clients can branch on. They come in two families: generic codes and domain codes.

**Detailed description**:
Generic codes repeat the HTTP reason phrase of their status: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `UNPROCESSABLE_ENTITY`, `INTERNAL_SERVER_ERROR`. The one exception is `VALIDATION_ERROR`, which names the cause rather than the status. Generic codes are defaults set in the class constructors, or literals in the middleware.

Domain codes follow a `<SUBJECT>_<CONDITION>` or `<CONDITION>_<SUBJECT>` pattern: `EMAIL_ALREADY_USED`, `SKU_ALREADY_USED`, `INVALID_STATUS_TRANSITION`, `INVALID_ORDER_STATE_FOR_DELETE`, `INACTIVE_PRODUCT`, `INSUFFICIENT_STOCK`. Services pass them as string literals to `ConflictError` or `UnprocessableEntityError`, or they are hardcoded in a dedicated subclass. No central enum or constant registry exists, so the full set of codes is known only by searching the codebase (see the inventory table above). The 404 path has no domain code: every missing entity returns `NOT_FOUND`, and the entity type is given only in the message text.

`INVALID_STATUS_TRANSITION` has two producers. The dedicated class covers transitions that are not allowed (order.service.ts:148). A direct `ConflictError` with the same code handles the same-status case (order.service.ts:141-145). Both use the same details shape `{from, to}` but different message texts. This is the only code with more than one construction path. Confidence: High (both sites read directly).

**Rule workflow**:
```
Need new client-distinguishable condition?
  -> generic status sufficient -> use class default code
  -> domain-specific         -> pass literal code to ConflictError/UnprocessableEntityError/BadRequestError
                                or create dedicated subclass with hardcoded code + structured details
```

---

### Business Rule: Uniform error response envelope

**Overview**:
The error middleware writes every error response as `{ "error": { "code", "message", "details"? } }` (error.middleware.ts:16-22, 28-32, 40-45, 50, 63).

**Detailed description**:
The envelope has a single top-level key, `error`, so clients can tell error bodies from success bodies, which have no envelope. `code` is always present and always matches the inventory above. `message` is always present. For `AppError` it is the message from the throw site. For the Zod, Prisma and 500 paths it is fixed text, except that the P2002 message includes the target columns.

`details` uses a conditional spread, `...(err.details !== undefined ? { details: err.details } : {})` (error.middleware.ts:20). The key is left out entirely, not set to `null`, when there are no details. The Zod branch always includes `details`. The Prisma and 500 branches never do. Clients therefore have to treat `details` as optional and its shape as depending on the code: an array of `{path,message}` for `VALIDATION_ERROR`, `{from,to}` for `INVALID_STATUS_TRANSITION`, `{status}` for `INVALID_ORDER_STATE_FOR_DELETE`, `{skus}` for `INACTIVE_PRODUCT`, and `{unavailable}` for `INSUFFICIENT_STOCK`.

The envelope carries no `requestId`, timestamp or path. Clients can still correlate a response with server logs through the `X-Request-Id` response header that `requestLogger` sets (request-logger.middleware.ts:8). That header is set before routing, so it is also present on error responses.

**Rule workflow**:
```
err classified -> build {code, message} -> attach details only if defined (AppError) or always (Zod)
  -> res.status(status).json({ error: {...} })
```

---

### Business Rule: Zod validation error mapping

**Overview**:
Zod schema failures become HTTP 400 `VALIDATION_ERROR` responses. Their details are a flattened list of `{path, message}` entries.

**Detailed description**:
There are two mapping points, and both use the same algorithm. The main one is `validate()` in src/middlewares/validate.middleware.ts:26-32. It catches the `ZodError` raised by `schema.parse()` for body, query or params, and calls `next(new ValidationError('Validation failed', details))`. The second is a defensive branch in the error middleware (error.middleware.ts:26-35) that maps any raw `ZodError` reaching it. The helper `formatZodIssues` (error.middleware.ts:7-12) and the inline code in `validate()` both join each issue's path array with `.`, for example `items.0.quantity`. An empty path becomes the literal `(root)`. Only `issue.message` is kept. Zod issue codes, expected and received types, and other metadata are dropped.

The sources are validated in a fixed order: body, then query, then params. Each one uses `parse` (it throws on the first failure) and not `safeParse`. A request with an invalid body and invalid params therefore reports only the body issues. Within one source, every issue for that source is reported.

In the current code no other `parse()` call runs in request scope (`env.ts` uses `safeParse` at startup), so the error middleware's Zod branch cannot be reached. It only protects against future direct `parse` calls in services. Confidence: High (searching `src/` finds only the three `parse` calls in validate.middleware.ts:15, 18, 22).

**Rule workflow**:
```
validate(schemas) -> schema.parse(source) throws ZodError
  -> map issues to {path: path.join('.') || '(root)', message}
  -> next(new ValidationError('Validation failed', details))
  -> errorMiddleware AppError branch -> 400 {error:{code:'VALIDATION_ERROR', message:'Validation failed', details:[...]}}
(fallback) raw ZodError -> errorMiddleware Zod branch -> same output
```

---

### Business Rule: Service-level validation errors (non-Zod)

**Overview**:
Services raise `ValidationError` directly for business checks that the Zod schemas cannot express.

**Detailed description**:
`OrderService.create` throws `ValidationError('Order must contain at least one item')` when `input.items.length === 0` (order.service.ts:51-53). This response has no `details`, so its body differs from the Zod-originated `VALIDATION_ERROR`, which always carries an array. Whether this branch can be reached depends on the order Zod schema. If that schema already requires a minimum of one item, the check is defensive. This was not verified for this component.

The service also throws `ValidationError('Discount cannot exceed subtotal', [{ path: 'discountCents', message: 'Discount exceeds subtotal' }])` when `input.discountCents > subtotalCents` (order.service.ts:87-91). The details here deliberately copy the Zod `{path, message}` format, so clients can display the error the same way as a schema error. The check runs inside the Prisma transaction after prices are loaded from the database, because the subtotal is computed on the server from current product prices.

Throwing inside `prisma.$transaction` rolls the transaction back. Customer, product and inactive-product checks that run earlier in the same transaction have no side effects, so a validation failure leaves no partial data behind.

**Rule workflow**:
```
OrderService.create
  items empty           -> 400 VALIDATION_ERROR "Order must contain at least one item" (no details)
  discount > subtotal   -> 400 VALIDATION_ERROR "Discount cannot exceed subtotal" details [{path:'discountCents',...}]
```

---

### Business Rule: Authentication and authorization errors

**Overview**:
Authentication failures produce 401 `UNAUTHORIZED`. Authorization (role) failures produce 403 `FORBIDDEN`.

**Detailed description**:
`authenticate` (auth.middleware.ts:26-46) raises a different `UnauthorizedError` message for each case:

- `"Missing or invalid Authorization header"` when the header is missing or does not start with `bearer ` (case-insensitive, line 30).
- `"Missing bearer token"` when the token after the prefix is empty (line 36).
- `"Invalid or expired token"` for any `jwt.verify` failure (line 45). Expired, malformed and badly signed tokens get the same message, so the reason is not disclosed.

`requireRole` (auth.middleware.ts:48-60) returns `UnauthorizedError()` with the default message `"Unauthorized"` if `req.user` is missing (line 52), and `ForbiddenError('Insufficient permissions')` if the user's role is not in the allowed list (line 56).

The login flow (auth.service.ts:31-40) uses the same `UnauthorizedError('Invalid credentials')` for an unknown email (line 34) and for a wrong password (line 38). This prevents account enumeration through the message. Response timing still differs between the two paths, because bcrypt only runs when the user exists; this is an observation and not an error-handling rule. Controllers that need `req.user` (auth.controller.ts:32, order.controller.ts:30, 40) also throw a bare `UnauthorizedError()` as a defensive guard in case `authenticate` was not mounted.

All of these become 401 or 403 with no `details`. None of them is logged by the error middleware.

**Rule workflow**:
```
No/invalid header -> 401 "Missing or invalid Authorization header"
Empty token       -> 401 "Missing bearer token"
jwt.verify fails  -> 401 "Invalid or expired token"
No req.user       -> 401 "Unauthorized"
Role not allowed  -> 403 "Insufficient permissions"
Bad login         -> 401 "Invalid credentials"
```

---

### Business Rule: Not-found semantics

**Overview**:
Missing entities and unknown routes both produce 404 `NOT_FOUND`, and the message names the resource.

**Detailed description**:
Services call `new NotFoundError('<Entity>')` after a lookup returns null:

- `Customer`: customer.service.ts:25, order.service.ts:60
- `Product`: product.service.ts:26, order.service.ts:64
- `User`: user.service.ts:38
- `Order`: order.service.ts:46, 136, 183

The resulting message is `"<Entity> not found"`.

During order creation, a missing product is detected by comparing counts (`products.length !== productIds.length`, order.service.ts:63). The error does not say which product id is missing, and it has no details. Order items are combined by productId before this check (order.service.ts:55, 194-202), so duplicate lines in the request do not cause false positives.

Unmatched routes reach the fallback in app.ts:69-71, which produces `NotFoundError('Route GET /path')` and therefore the message `"Route GET /path not found"`. Prisma `P2025` ("record to update or delete not found") is mapped to 404 `NOT_FOUND` with the generic `"Resource not found"` (error.middleware.ts:48-53). In practice this happens when a record is deleted between the service's existence check and the repository's `update` or `delete` call: customer/product update and delete call `getById` first and then `update` or `delete`.

**Rule workflow**:
```
lookup returns null -> NotFoundError(entity) -> 404 "<Entity> not found"
no route matched     -> NotFoundError("Route M URL") -> 404 "Route M URL not found"
Prisma P2025         -> 404 "Resource not found"
```

---

### Business Rule: Uniqueness conflicts (application-level and database-level)

**Overview**:
Duplicate unique values are checked first by services, which return domain codes. The database unique constraint (Prisma `P2002`) is the second line of defense and returns the generic `CONFLICT`.

**Detailed description**:
`CustomerService.create` and `update` look the email up and throw `ConflictError('Email already registered', 'EMAIL_ALREADY_USED')` (customer.service.ts:32, 48). On update the error is raised only if the existing record has a different id, so saving your own email again is allowed. `UserService.createUser` does the same (user.service.ts:24). That path also covers `/auth/register`, because `AuthService.register` delegates to it. `ProductService.create` and `update` apply the same rule to the SKU with `SKU_ALREADY_USED` (product.service.ts:33, 50).

These check-then-write sequences are not atomic. Two concurrent requests can both pass the check, and then the second insert fails on the database unique index (`schema.prisma:27, 43, 58, 76` for user email, customer email, product SKU and order number). The resulting `PrismaClientKnownRequestError` with code `P2002` is mapped by error.middleware.ts:38-47 to 409 `CONFLICT`. The message is `"Unique constraint violation on: <target>"` when `meta.target` is available. `meta.target` is cast to `string[]` and joined with `, ` (line 39). If the target is missing, the message is `"Unique constraint violation"`. The race therefore produces the same HTTP status but a different code (`CONFLICT` instead of `EMAIL_ALREADY_USED` or `SKU_ALREADY_USED`). Clients that branch on the domain code would see the two cases differently.

The P2002 message exposes database column names (for example `email` or `sku`) to the client. Confidence that `meta.target` is an array of field names: Medium. That is the Prisma 5 convention for PostgreSQL, but the cast is unchecked: if Prisma returned a string (as some connectors do), `.join` would not exist on it and would throw inside the middleware.

**Rule workflow**:
```
service pre-check finds duplicate -> 409 EMAIL_ALREADY_USED | SKU_ALREADY_USED
race: DB unique index fails       -> Prisma P2002 -> 409 CONFLICT "Unique constraint violation on: <cols>"
```

---

### Business Rule: Order status transition conflict

**Overview**:
Order status changes must follow the state machine in `order.status.ts`. Any other change returns 409 `INVALID_STATUS_TRANSITION` with `{from, to}` details.

**Detailed description**:
`InvalidStatusTransitionError(from, to)` (http-errors.ts:45-53) builds the message `"Invalid status transition from ${from} to ${to}"`, with code `INVALID_STATUS_TRANSITION` and details `{from, to}`. `OrderService.changeStatus` throws it when `canTransition(from, to)` is false (order.service.ts:147-149). The allowed transitions are PENDING to PAID or CANCELLED, PAID to PROCESSING or CANCELLED, PROCESSING to SHIPPED or CANCELLED, and SHIPPED to DELIVERED. DELIVERED and CANCELLED are terminal (order.status.ts:3-10).

A same-status request (from === to) is caught before the state machine check (order.service.ts:140-146). It raises a plain `ConflictError` with the message `"Order is already in ${to} status"` and the same code and details shape. Clients get one code for both cases and can tell them apart only by the message or by comparing `from` and `to` in the details.

Both checks run inside `prisma.$transaction`, before any stock debit or replenishment, so no stock changes happen when a transition is rejected. The integration test `tests/orders.test.ts:89-107` checks the PENDING to SHIPPED rejection (409 plus code).

**Rule workflow**:
```
changeStatus(id, toStatus)
  order missing     -> 404 NOT_FOUND
  from == to        -> 409 INVALID_STATUS_TRANSITION "Order is already in X status" {from,to}
  !canTransition    -> 409 INVALID_STATUS_TRANSITION "Invalid status transition from A to B" {from,to}
  else              -> stock side effects + update + history
```

---

### Business Rule: Order deletion state conflict

**Overview**:
Orders can be deleted only while they are PENDING or CANCELLED. Otherwise the API returns 409 `INVALID_ORDER_STATE_FOR_DELETE`.

**Detailed description**:
`OrderService.delete` (order.service.ts:181-192) first raises `NotFoundError('Order')` if the order does not exist. If its status is neither `PENDING` nor `CANCELLED`, it throws `ConflictError('Order can only be deleted while in PENDING or CANCELLED status', 'INVALID_ORDER_STATE_FOR_DELETE', { status })`. The details include the current status, so clients can explain why the delete was refused.

The check and the delete are not wrapped in a transaction. A concurrent status change between the two steps could let an order be deleted after it became PAID. If the order is deleted concurrently, `deleteById` raises Prisma `P2025`, which becomes a generic 404 `"Resource not found"`. Covered by `tests/orders.test.ts:197-218`.

**Rule workflow**:
```
delete(id): missing -> 404; status not in {PENDING, CANCELLED} -> 409 INVALID_ORDER_STATE_FOR_DELETE {status}; else delete (items/history cascade)
```

---

### Business Rule: Unprocessable order constraints (inactive product, insufficient stock)

**Overview**:
Business constraints on valid, existing products return 422, with structured details that list each offending item.

**Detailed description**:
During `OrderService.create`, the service filters out inactive products after loading them. If any are inactive, it throws `UnprocessableEntityError('One or more products are inactive', 'INACTIVE_PRODUCT', { skus })` (order.service.ts:66-73). Every inactive SKU is reported, not only the first. The check runs inside the creation transaction, so nothing is written.

On the PENDING to PAID transition (`shouldDebitStock`), `debitStock` (order.service.ts:204-231) collects every item whose product is missing or has `stockQuantity < quantity` into `unavailable: [{sku, requested, available}]`. If the list is not empty, it throws `InsufficientStockError(unavailable)` (line 223). The fixed message is `"One or more products do not have enough stock"`, and the details are `{unavailable}`. A product that was deleted after the order was created is reported with its productId in place of the SKU and with `available: 0` (lines 216-218). The error is raised before any decrement and inside the transaction, so stock stays unchanged. The test at tests/orders.test.ts:131 checks this.

Stock is checked at payment time, not at order creation. An order can therefore be created for more units than are in stock and fail later with 422 when it is paid.

**Rule workflow**:
```
create: any product inactive -> 422 INACTIVE_PRODUCT {skus:[...]}
PENDING->PAID: any item short -> 422 INSUFFICIENT_STOCK {unavailable:[{sku,requested,available}]}
```

---

### Business Rule: Unhandled error fallback and logging

**Overview**:
Every error that is not classified becomes a 500 with a generic body. It is the only error type the error middleware logs.

**Detailed description**:
If an error is not an `AppError`, not a `ZodError` and not a Prisma known error with code P2002 or P2025, the middleware (error.middleware.ts:56-64):

1. Reads `req.id`, which `requestLogger` sets from the `X-Request-Id` header or a new UUIDv4. It falls back to `'unknown'`.
2. Calls `logger.error({ err, requestId, method: req.method, path: req.originalUrl }, 'Unhandled error in request')`.
3. Responds with `500 { error: { code: 'INTERNAL_SERVER_ERROR', message: 'Internal server error' } }`.

The client never receives the stack, the error message or Prisma metadata.

Pino applies its default `err` serializer to the `err` key, so the log contains type, message and stack. The redaction paths (`req.headers.authorization`, `req.headers.cookie`, `*.password`, `*.passwordHash`, `*.token`, `*.accessToken`) apply. The request object is not logged here, though, so only `err` fields at one level of nesting would be redacted. In development the logger uses `pino-pretty`; in other environments it writes JSON lines with ISO timestamps and base fields `service: 'order-management-api'` and `env`.

The fallback also catches errors that are client errors in nature:

- Body-parser `SyntaxError` for malformed JSON. Its `status` is 400 and its `type` is `entity.parse.failed`.
- `PayloadTooLargeError` for bodies over 1mb (status 413).
- Prisma `P2003` foreign-key constraint failures. These are reachable through `DELETE /customers/:id` and `DELETE /products/:id` when orders or order items reference the record, because `schema.prisma:87, 109` define relations without `onDelete`, which defaults to Restrict.
- Any other Prisma known request code, plus `PrismaClientValidationError`, `PrismaClientInitializationError` and `PrismaClientUnknownRequestError`.

All of these produce a 500 and an error-level log entry. Confidence that P2003 is reachable: High. The customer and product services call `delete` with no reference check (customer.service.ts:60-63, product.service.ts:63-66).

4xx errors are not logged by this component. They show up only in the info-level `http_request` access log line, which records `statusCode` but not the error code or message (request-logger.middleware.ts:13-24).

**Rule workflow**:
```
unclassified err -> requestId = req.id ?? 'unknown'
  -> logger.error({err, requestId, method, path}, 'Unhandled error in request')
  -> 500 {error:{code:'INTERNAL_SERVER_ERROR', message:'Internal server error'}}
```

---

### Business Rule: Async error propagation contract (Express 4)

**Overview**:
Express 4.21.1 does not forward rejected promises from async handlers. Every controller has to catch errors itself and call `next(err)`.

**Detailed description**:
All controllers (auth, users, customers, products, orders) declare handlers as async arrow properties with `try { ... } catch (err) { next(err) }`. Examples: order.controller.ts:9-55, customer.controller.ts:14/23/32/41/50, product.controller.ts:14/23/32/41/50, user.controller.ts:12, auth.controller.ts:17/26/36. This convention is what connects thrown `AppError` instances to the middleware. A new handler that left out the try/catch would leave the request hanging, or cause an unhandled rejection, and would never reach the error middleware.

The middlewares are synchronous and call `next(err)` directly (auth.middleware.ts, validate.middleware.ts). The 404 fallback and the error middleware are registered after the API router (app.ts:69-73), which is the order Express requires.

**Rule workflow**:
```
async handler -> await service -> throws -> catch -> next(err) -> errorMiddleware
```

---

## 4. Component Structure

```
src/
├── shared/
│   └── errors/
│       ├── app-error.ts          # ErrorDetails type + AppError base class (statusCode, errorCode, details)
│       ├── http-errors.ts        # 7 HTTP-status error classes + 2 domain errors
│       └── index.ts              # Barrel: re-exports AppError, ErrorDetails type, all subclasses
└── middlewares/
    └── error.middleware.ts       # Terminal Express ErrorRequestHandler: AppError/Zod/Prisma/fallback mapping + logging

Closely related collaborators (outside component boundary):
src/app.ts                                   # Registers 404 fallback and errorMiddleware (lines 69-73)
src/middlewares/validate.middleware.ts       # ZodError -> ValidationError conversion
src/middlewares/auth.middleware.ts           # Raises Unauthorized/Forbidden
src/middlewares/request-logger.middleware.ts # Provides req.id and X-Request-Id used in error logs
src/shared/logger/index.ts                   # Pino logger with redaction used by errorMiddleware
```

Size: app-error.ts 16 lines, http-errors.ts 63 lines, index.ts 13 lines, error.middleware.ts 65 lines.

---

## 5. Dependency Analysis

```
Internal Dependencies (compile-time):
http-errors.ts      -> app-error.ts (AppError, ErrorDetails)
index.ts            -> app-error.ts, http-errors.ts
error.middleware.ts -> shared/errors/index.ts (AppError)
error.middleware.ts -> shared/logger/index.ts (logger) -> config/env.ts (LOG_LEVEL, NODE_ENV)

Runtime dependencies:
error.middleware.ts reads req.id populated by request-logger.middleware.ts
error.middleware.ts relies on registration order in app.ts:73 (last middleware)

External Dependencies:
- express 4.21.1        - ErrorRequestHandler type (type-only import)
- @prisma/client 5.22.0 - Prisma.PrismaClientKnownRequestError (runtime instanceof)
- zod 3.23.8            - ZodError (runtime instanceof)
- pino 9.5.0            - logging (via shared logger); pino-pretty 11.3.0 in development
```

The error classes (`src/shared/errors/*`) depend on no framework. They have no imports beyond each other, so other layers can use them freely. The coupling to frameworks sits entirely in the middleware.

---

## 6. Afferent and Efferent Coupling

Afferent coupling (Ca) counts the source files in `src/` that import or use the element. Efferent coupling (Ce) counts the distinct modules or types the element depends on.

| Component | Afferent Coupling | Efferent Coupling | Critical |
|-----------|-------------------|-------------------|----------|
| AppError (app-error.ts) | 2 direct (http-errors.ts, index.ts); 1 via barrel (error.middleware.ts); indirectly all 9 subclasses | 0 | High |
| ErrorDetails (type) | 2 (http-errors.ts, index.ts) | 0 | Low |
| BadRequestError | 0 | 1 (AppError) | Low |
| ValidationError | 2 (validate.middleware.ts, order.service.ts) | 1 | Medium |
| UnauthorizedError | 4 (auth.middleware.ts, auth.controller.ts, auth.service.ts, order.controller.ts) | 1 | Medium |
| ForbiddenError | 1 (auth.middleware.ts) | 1 | Low |
| NotFoundError | 6 (app.ts, customer.service.ts, product.service.ts, user.service.ts, order.service.ts; plus indirect via services) | 1 | High |
| ConflictError | 4 (customer.service.ts, product.service.ts, user.service.ts, order.service.ts) + subclass | 1 | High |
| UnprocessableEntityError | 1 (order.service.ts) + subclass | 1 | Medium |
| InvalidStatusTransitionError | 1 (order.service.ts) | 1 (ConflictError) | Medium |
| InsufficientStockError | 1 (order.service.ts) | 1 (UnprocessableEntityError) | Medium |
| errors/index.ts (barrel) | 11 (app.ts, auth.middleware.ts, error.middleware.ts, validate.middleware.ts, auth.controller.ts, auth.service.ts, customer.service.ts, order.controller.ts, order.service.ts, product.service.ts, user.service.ts) | 2 | High |
| errorMiddleware | 1 (app.ts) | 5 (express types, Prisma, ZodError, AppError, logger) | High |
| formatZodIssues (private fn) | 1 (errorMiddleware) | 1 (ZodError) | Low |

The errors barrel has high afferent and low efferent coupling, which makes it a stable abstraction. `errorMiddleware` has low afferent and higher efferent coupling. Because it is the only translator of errors into HTTP responses, it is critical despite having a single consumer.

---

## 7. Endpoints

The component exposes no endpoints of its own. It shapes the error responses of every endpoint under `/api/v1` and handles unmatched routes through the fallback in `src/app.ts:69-71` together with `errorMiddleware`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `*` (any unmatched path) | ANY | Returns 404 `NOT_FOUND` "Route <METHOD> <URL> not found" via `NotFoundError` and `errorMiddleware` |

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| Express pipeline | Framework | Receives errors forwarded via `next(err)`; sends HTTP responses | HTTP | JSON | Terminal handler; does not check `res.headersSent`; never calls `next` |
| Prisma Client (PostgreSQL) | Library / Database | Classify DB errors | In-process | `PrismaClientKnownRequestError.code/meta` | P2002 -> 409, P2025 -> 404, others -> 500 |
| Zod | Library | Classify schema errors | In-process | `ZodError.issues` | -> 400 with `{path,message}[]` |
| Pino logger | Library / Observability | Log unhandled errors | stdout | JSON lines (pino-pretty in development) | Logs `err`, `requestId`, `method`, `path` at `error` level |
| request-logger middleware | Internal | Supplies `req.id` and `X-Request-Id` header | In-process | string | Fallback `'unknown'` |
| Domain services and middlewares | Internal | Throw `AppError` subclasses | In-process | Error objects | Mapped 1:1 by `statusCode`/`errorCode` |
| API clients | External consumers | Consume error envelope | HTTPS/REST | `{error:{code,message,details?}}` | Branch on `code` |

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Exception hierarchy / Layer Supertype | `AppError` base with HTTP-aware subclasses | src/shared/errors/app-error.ts, http-errors.ts | One typed model for client-facing errors |
| Specialization by inheritance | `InvalidStatusTransitionError extends ConflictError`, `InsufficientStockError extends UnprocessableEntityError` | src/shared/errors/http-errors.ts:45, 55 | Domain errors with fixed code and typed details |
| Parameterized error code | `code` constructor argument in Bad Request / Conflict / Unprocessable | src/shared/errors/http-errors.ts:4, 34, 40 | Domain codes without new classes |
| Centralized error handler (Express error middleware) | `errorMiddleware` | src/middlewares/error.middleware.ts:14 | Single translation point from errors to HTTP |
| Chain of type checks (adapter/translator) | `instanceof` cascade AppError, ZodError, Prisma, fallback | src/middlewares/error.middleware.ts:15-64 | Maps foreign error types to the API contract |
| Barrel module | `index.ts` re-exports | src/shared/errors/index.ts | Stable import path |
| Error envelope (API contract) | `{error:{code,message,details?}}` | src/middlewares/error.middleware.ts | Consistent client contract |
| Fail-safe default / information hiding | Generic 500 body, details logged server-side | src/middlewares/error.middleware.ts:56-64 | Avoid leaking internals |
| Correlation ID | `req.id` included in error log, `X-Request-Id` header | request-logger.middleware.ts:6-8; error.middleware.ts:56 | Trace a request across logs |
| Catch-and-forward (Express 4 async) | try/catch -> `next(err)` in controllers | src/modules/*/*.controller.ts | Bridge async rejections to middleware |

Architectural decisions found in the code:

- HTTP status is coupled to the error class. Services choose a class that already implies an HTTP status, so the domain layer knows about HTTP semantics, though not about Express.
- Expected (4xx) and unexpected (5xx) errors are separated by type. Only unexpected errors are logged.
- Prisma error translation is partial: only P2002 and P2025.

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| High | errorMiddleware / Prisma mapping | `P2003` (FK violation) not mapped; `DELETE /customers/:id` and `DELETE /products/:id` on referenced records fall through to 500 (schema.prisma:87, 109 have no `onDelete`) | Client error reported as server error; noisy error logs |
| Medium | errorMiddleware | Body-parser errors (`SyntaxError` 400 for malformed JSON, `PayloadTooLargeError` 413) ignored; `err.status`/`err.statusCode` of non-AppError errors not honored | Malformed client input returns 500 and is logged as a server failure |
| Medium | errorMiddleware | No `res.headersSent` check and `_next` unused (error.middleware.ts:14) | Calling `res.status().json()` after headers were sent throws `ERR_HTTP_HEADERS_SENT` inside the handler |
| Medium | errorMiddleware P2002 | `err.meta?.target as string[]` unchecked cast then `.join` (error.middleware.ts:39) | If `target` is a string, `.join` is not a function and a TypeError is thrown inside the error handler |
| Medium | Uniqueness | Check-then-write in services; race falls back to generic `CONFLICT` instead of `EMAIL_ALREADY_USED` / `SKU_ALREADY_USED` | Inconsistent error codes for the same condition |
| Low | P2002 message | Column names exposed in message (`Unique constraint violation on: email`) | Minor schema information disclosure |
| Low | Error code governance | Codes are string literals scattered across services; no enum or registry | Typos and drift go undetected at compile time; documentation must be kept in sync by hand |
| Low | INVALID_STATUS_TRANSITION | Raised from two construction paths with different messages (order.service.ts:141, 148) | Duplicated logic; clients must inspect the message to tell the cases apart |
| Low | ValidationError | Service-level `ValidationError` without details (order.service.ts:52) while others have details | `details` shape not consistent for the same code |
| Low | Dead code | `BadRequestError` unused; `UNPROCESSABLE_ENTITY` and class-default `CONFLICT` unused; middleware `ZodError` branch unreachable today | Maintenance overhead; untested paths |
| Low | AppError.name | Always `'AppError'` for every subclass (app-error.ts:10) | Logs and stack traces lose the concrete class name |
| Low | Logging | 4xx errors not logged with code or message; only status in access log | Limited diagnostics for client-error trends (e.g. auth failures) |
| Low | Error envelope | No `requestId` in body (only the `X-Request-Id` header) | Clients that ignore headers cannot report a correlation ID |
| Low | Express 4 async | Correctness depends on every async handler having try/catch | A missed try/catch hangs the request and causes an unhandled rejection |
| Low | Order delete | Status check and delete are not in a transaction (order.service.ts:181-192) | A race may delete an order that has just been paid |

---

## 11. Test Coverage Analysis

Test infrastructure: Vitest 2.1.4 with supertest 7.0.0 (`vitest.config.ts`). Tests run against a real database in a single fork. `tests/setup.ts` empties all tables before each test. No coverage provider is configured (no `@vitest/coverage-*` dependency and no `coverage` block), so the project has no measured coverage figures. The percentages below are estimates of how many branches or codes are exercised, based on reading the tests.

Test files located:

- `tests/auth.test.ts` (84 lines): integration tests for auth.
- `tests/orders.test.ts` (219 lines): integration tests for orders.
- `tests/helpers/factories.ts` (83 lines): data and app factories.
- `tests/setup.ts` (20 lines): DB lifecycle.

No unit tests exist for `AppError`, the subclasses or `errorMiddleware`.

Error-related assertions found:

| Test | File:line | Asserted status / code |
|------|-----------|------------------------|
| rejects register with duplicated email | tests/auth.test.ts:19-28 | 409 / `EMAIL_ALREADY_USED` |
| rejects register with invalid payload | tests/auth.test.ts:30-39 | 400 / `VALIDATION_ERROR`, `details` is array |
| rejects login with wrong password | tests/auth.test.ts:54-63 | 401 / `UNAUTHORIZED` |
| rejects /auth/me without token | tests/auth.test.ts:79-83 | 401 (code not asserted) |
| rejects an order with non-existent product | tests/orders.test.ts:42-57 | 404 / `NOT_FOUND` |
| returns 409 on invalid status transition (PENDING -> SHIPPED) | tests/orders.test.ts:89-107 | 409 / `INVALID_STATUS_TRANSITION` |
| returns 422 when transitioning PENDING -> PAID without enough stock | tests/orders.test.ts:109-132 | 422 / `INSUFFICIENT_STOCK`, `details.unavailable[0].sku`, stock unchanged |
| refuses to delete an order that is not PENDING or CANCELLED | tests/orders.test.ts:197-218 | 409 / `INVALID_ORDER_STATE_FOR_DELETE` |

| Component | Unit Tests | Integration Tests | Coverage (estimated) | Test Quality |
|-----------|------------|-------------------|----------------------|--------------|
| AppError | 0 | Indirect (all error tests) | Constructor exercised; `captureStackTrace` and `name` not asserted | Indirect only |
| ValidationError | 0 | 1 (Zod path) | Zod path only; service-level validations (empty items, discount > subtotal) not tested | Checks `details` is an array but not its content |
| UnauthorizedError | 0 | 2 | 2 of 9 raise sites (wrong password; missing header asserts status only) | Expired/invalid token, empty bearer and unknown email not tested |
| ForbiddenError | 0 | 0 | 0% | No role-based negative test |
| NotFoundError | 0 | 1 | 1 of 10 raise sites; route 404 not tested | Message content not asserted |
| ConflictError (EMAIL_ALREADY_USED) | 0 | 1 | Register path only; customer email conflict not tested | Good |
| ConflictError (SKU_ALREADY_USED) | 0 | 0 | 0% | Missing |
| ConflictError (INVALID_ORDER_STATE_FOR_DELETE) | 0 | 1 | Covered | Code asserted; `details.status` not asserted |
| InvalidStatusTransitionError | 0 | 1 | Disallowed-transition path; same-status path not tested | `details` not asserted |
| UnprocessableEntityError (INACTIVE_PRODUCT) | 0 | 0 | 0% | Missing |
| InsufficientStockError | 0 | 1 | Covered | Strong: checks details and the rollback (stock unchanged) |
| BadRequestError | 0 | 0 | 0% (unused) | N/A |
| errorMiddleware AppError branch | 0 | 7 | Covered, including details present/absent | Envelope `error.code` asserted; `message` never asserted |
| errorMiddleware ZodError branch | 0 | 0 | 0% (unreachable) | N/A |
| errorMiddleware Prisma P2002 / P2025 | 0 | 0 | 0% | No race or concurrency tests |
| errorMiddleware 500 fallback and logging | 0 | 0 | 0% | No test for generic body, log call or requestId |
| Route 404 fallback (app.ts:69-71) | 0 | 0 | 0% | Missing |

Summary: 7 of the 14 error codes appear in test assertions (`VALIDATION_ERROR`, `UNAUTHORIZED`, `NOT_FOUND`, `EMAIL_ALREADY_USED`, `INVALID_STATUS_TRANSITION`, `INSUFFICIENT_STOCK`, `INVALID_ORDER_STATE_FOR_DELETE`). Nothing tests `FORBIDDEN`, `CONFLICT` (P2002), `SKU_ALREADY_USED`, `INACTIVE_PRODUCT`, `INTERNAL_SERVER_ERROR` or the fallback logging. `BAD_REQUEST` and `UNPROCESSABLE_ENTITY` are never raised. The lack of tests for the middleware's Prisma and fallback branches matters most, because those branches decide whether internal details leak and whether failures are logged.
