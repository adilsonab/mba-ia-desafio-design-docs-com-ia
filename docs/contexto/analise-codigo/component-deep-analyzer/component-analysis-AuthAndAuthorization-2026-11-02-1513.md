# Component Deep Analysis Report

**Component:** AuthAndAuthorization
**Scope:** `src/middlewares/auth.middleware.ts` (`authenticate`, `requireRole`), `src/modules/auth/*`, and how authentication/roles are applied in every `*.routes.ts` file
**Project:** order-management-api (Node.js 20 + TypeScript + Express 4 + Prisma/MySQL)
**Analysis date:** 2026-11-02
**Excluded folders:** node_modules, dist, .git, docs

---

## 1. Executive Summary

The AuthAndAuthorization component provides **stateless, JWT-based authentication** and a **minimal role-based access control (RBAC)** layer for the Order Management System REST API. It has two halves:

1. **Identity issuance** (`src/modules/auth/`): public `POST /api/v1/auth/register` (self-service user creation) and `POST /api/v1/auth/login` (credential verification with bcrypt and HS256 JWT issuance), plus the authenticated `GET /api/v1/auth/me` (returns the caller's public profile).
2. **Request guarding** (`src/middlewares/auth.middleware.ts`): the `authenticate` middleware verifies a `Bearer` token and attaches `req.user = { id, email, role }`; the `requireRole(...roles)` factory returns a middleware that allows a request only if `req.user.role` is in the allowed list.

The role model is a closed two-value enum, `ADMIN | OPERATOR`, defined in the Prisma schema (`prisma/schema.prisma:11-14`, default `OPERATOR`) and duplicated as TypeScript string literals in at least six places.

**Key findings:**

- **`requireRole` is used exactly once in the codebase**: `GET /api/v1/users/:id` requires `ADMIN` (`src/modules/users/user.routes.ts:15`). Every other protected route (customers, products, orders, `/auth/me`) only requires authentication, so `ADMIN` and `OPERATOR` have identical capabilities everywhere else, including all `DELETE` operations.
- **Privilege escalation via public registration (Critical):** `POST /auth/register` is unauthenticated and its schema accepts `role: 'ADMIN'` (`src/modules/auth/auth.schemas.ts:7`). Anyone can self-register as `ADMIN` and thereby satisfy the only `requireRole('ADMIN')` check in the system.
- **Token claims are trusted without re-validation:** `authenticate` casts the verified payload to `JwtPayload` without schema validation and does not check that the user still exists or that the role is still current. Role changes or user deletion do not take effect until the token expires (default `8h`).
- **Error contract:** all authN failures surface as HTTP 401 `UNAUTHORIZED`; authZ failures as HTTP 403 `FORBIDDEN`, serialized by the centralized error middleware as `{ error: { code, message } }`.
- **Tests:** 7 integration tests in `tests/auth.test.ts` cover register/login/me happy paths and a few negatives. There are **no tests** for `requireRole`, the 403 path, invalid/expired/malformed tokens, or the `/users/:id` endpoint.

---

## 2. Data Flow Analysis

### 2.1 Registration flow (`POST /api/v1/auth/register`)

```
1. Express app (src/app.ts:59) parses JSON body (limit 1mb); requestLogger assigns request id
2. buildApiRouter mounts /auth -> buildAuthRouter (src/routes/index.ts:24)
3. validate({ body: registerSchema }) (src/modules/auth/auth.routes.ts:10)
   - email: valid email, max 255; password: 8..72; name: 2..150; role: ADMIN|OPERATOR, default OPERATOR
   - On failure: ValidationError -> 400 VALIDATION_ERROR with details[]
4. AuthController.register (src/modules/auth/auth.controller.ts:12) -> AuthService.register
5. AuthService.register delegates to UserService.createUser (src/modules/auth/auth.service.ts:27-29)
6. UserService.createUser (src/modules/users/user.service.ts:21-34)
   - findByEmail -> if exists: ConflictError 409 EMAIL_ALREADY_USED
   - bcrypt.hash(password, 10)
   - UserRepository.create -> Prisma user.create (MySQL `users` table)
7. UserService.toPublic strips passwordHash
8. Controller responds 201 with PublicUser { id, email, name, role, createdAt, updatedAt }
   (no token is issued on registration)
```

### 2.2 Login flow (`POST /api/v1/auth/login`)

```
1. validate({ body: loginSchema }) (src/modules/auth/auth.routes.ts:11)
   - email: valid email, max 255; password: 1..72
2. AuthController.login (src/modules/auth/auth.controller.ts:21) -> AuthService.login
3. AuthService.login (src/modules/auth/auth.service.ts:31-45)
   a. UserRepository.findByEmail(email) -> null => UnauthorizedError('Invalid credentials')
   b. bcrypt.compare(password, user.passwordHash) -> false => UnauthorizedError('Invalid credentials')
   c. signToken(user.id, user.email, user.role)
      jwt.sign({ sub, email, role }, env.JWT_SECRET, { expiresIn: env.JWT_EXPIRES_IN })
4. Response 200:
   { user: PublicUser, tokens: { accessToken, expiresIn: env.JWT_EXPIRES_IN, tokenType: 'Bearer' } }
```

### 2.3 Authenticated request flow (any guarded route)

```
1. Client sends `Authorization: Bearer <jwt>`
2. authenticate (src/middlewares/auth.middleware.ts:28-49)
   a. Header missing or not starting with "bearer " (case-insensitive) -> 401 'Missing or invalid Authorization header'
   b. token = header.slice(7).trim(); empty -> 401 'Missing bearer token'
   c. jwt.verify(token, env.JWT_SECRET) -> throws -> 401 'Invalid or expired token'
   d. req.user = { id: payload.sub, email: payload.email, role: payload.role }; next()
3. (Only on /users/:id) requireRole('ADMIN') (src/middlewares/auth.middleware.ts:51-63)
   a. !req.user -> 401 'Unauthorized'
   b. role not in allowed list -> 403 'Insufficient permissions'
4. validate(...) for params/query/body
5. Controller uses req.user.id where needed (auth/me, orders create/changeStatus)
6. Errors propagate via next(err) -> errorMiddleware (src/middlewares/error.middleware.ts:15-24)
   -> res.status(statusCode).json({ error: { code, message } })
7. requestLogger 'finish' handler logs userId = req.user?.id (src/middlewares/request-logger.middleware.ts:21)
```

### 2.4 `GET /api/v1/auth/me`

```
1. authenticate -> req.user populated from JWT claims
2. AuthController.me (src/modules/auth/auth.controller.ts:30-38)
   - defensive check: !req.user -> UnauthorizedError
   - UserService.getById(req.user.id) -> NotFoundError('User') 404 if user deleted after token issue
3. 200 PublicUser
```

---

## 3. Business Rules & Logic

### Overview of the business rules

| # | Rule Type | Rule Description | Location |
|---|-----------|------------------|----------|
| BR-01 | Domain / Data model | Roles are a closed enum `ADMIN`, `OPERATOR`; DB default `OPERATOR` | prisma/schema.prisma:11-14, :30; src/middlewares/auth.middleware.ts:9 |
| BR-02 | Validation | Registration payload constraints (email, password 8..72, name 2..150, role enum default OPERATOR) | src/modules/auth/auth.schemas.ts:3-8 |
| BR-03 | Authorization (implicit) | Public self-registration may choose any role including ADMIN | src/modules/auth/auth.routes.ts:10; src/modules/auth/auth.schemas.ts:7 |
| BR-04 | Business Logic | Email must be unique at registration -> 409 `EMAIL_ALREADY_USED` | src/modules/users/user.service.ts:22-25; prisma/schema.prisma:27 |
| BR-05 | Security | Passwords hashed with bcrypt, cost factor 10; hash never returned | src/modules/users/user.service.ts:16, :26, :42-51 |
| BR-06 | Validation | Login payload constraints (email, password 1..72) | src/modules/auth/auth.schemas.ts:10-13 |
| BR-07 | Business Logic | Login failure returns identical 401 `Invalid credentials` for unknown email and wrong password | src/modules/auth/auth.service.ts:32-39 |
| BR-08 | Security | JWT issued with claims `sub`, `email`, `role`, signed with `JWT_SECRET` (HS256 default), expiry `JWT_EXPIRES_IN` | src/modules/auth/auth.service.ts:47-50 |
| BR-09 | Contract | Login response shape `{ user, tokens: { accessToken, expiresIn, tokenType: 'Bearer' } }` | src/modules/auth/auth.service.ts:10-19, :41-44 |
| BR-10 | Configuration | `JWT_SECRET` min 16 chars, `JWT_EXPIRES_IN` default `8h`; process exits on invalid config | src/config/env.ts:8-9, :14-24 |
| BR-11 | Authentication | Bearer header parsing: scheme case-insensitive, token trimmed, three distinct 401 messages | src/middlewares/auth.middleware.ts:28-49 |
| BR-12 | Authentication | Identity on request derived solely from verified JWT claims (no DB lookup) | src/middlewares/auth.middleware.ts:42-43 |
| BR-13 | Authorization | `requireRole(...roles)`: 401 if no user, 403 `Insufficient permissions` if role not in list (OR semantics) | src/middlewares/auth.middleware.ts:51-63 |
| BR-14 | Authorization | Route protection matrix: `/users/:id` ADMIN only; customers/products/orders and `/auth/me` any authenticated role; register/login and `/health` public | src/modules/*/*.routes.ts; src/app.ts:62 |
| BR-15 | Error handling | Error codes: `UNAUTHORIZED` (401), `FORBIDDEN` (403), `VALIDATION_ERROR` (400), `EMAIL_ALREADY_USED` (409), `NOT_FOUND` (404) | src/shared/errors/http-errors.ts:15-25; src/middlewares/error.middleware.ts:15-24 |
| BR-16 | Business Logic | `/auth/me` re-reads the user from the DB by token `sub`; 404 if the user no longer exists | src/modules/auth/auth.controller.ts:30-38 |
| BR-17 | Audit / Attribution | Authenticated user id is used as `createdById` / `changedById` for orders and status history | src/modules/orders/order.controller.ts:30-31, :40-41 |
| BR-18 | Observability | Authenticated user id is included in the per-request access log | src/middlewares/request-logger.middleware.ts:21 |
| BR-19 | Seed data | Seed creates `admin@oms.local` / `admin123` (ADMIN) and `operador@oms.local` / `operator123` (OPERATOR) | prisma/seed.ts:6-7, :194-210 |

---

### Detailed breakdown of the business rules

---

### Business Rule: BR-01 Closed role enumeration (ADMIN / OPERATOR)

**Overview**:
The system recognizes exactly two roles: `ADMIN` and `OPERATOR`. Every user has exactly one role; new users default to `OPERATOR`.

**Detailed description**:
The canonical definition is the Prisma enum `UserRole { ADMIN OPERATOR }` (`prisma/schema.prisma:11-14`), with the `User.role` column declared `UserRole @default(OPERATOR)` (`prisma/schema.prisma:30`). At the database level, MySQL stores it as an ENUM column created by the initial migration, so no other value can be persisted.

In application code the enum is not imported from `@prisma/client`; instead, the literal union `'ADMIN' | 'OPERATOR'` is restated independently in `AuthUser` (`src/middlewares/auth.middleware.ts:9`), `AuthService.signToken` (`src/modules/auth/auth.service.ts:47`), `registerSchema` (`src/modules/auth/auth.schemas.ts:7`), `createUserSchema` (`src/modules/users/user.schemas.ts:11`), `UserRepository.create` (`src/modules/users/user.repository.ts:14`), `PublicUser` (`src/modules/users/user.service.ts:11`) and the test factory (`tests/helpers/factories.ts:18`, `:76`). `JwtPayload.role` is typed as `AuthUser['role']` (`src/middlewares/auth.middleware.ts:22`), and `requireRole` parameters are typed `AuthUser['role'][]`, which makes calls such as `requireRole('SUPERVISOR')` a compile error.

There is no role hierarchy: `ADMIN` does not implicitly include `OPERATOR` permissions by code. Because `requireRole` uses membership semantics, a route meant for both roles would have to list both explicitly. In practice, since only one route uses `requireRole`, the effective hierarchy is "ADMIN = OPERATOR + access to `GET /users/:id`". The `role` value is also echoed back to clients in `PublicUser` and embedded in the JWT.

**Rule workflow**:
```
User created (register or seed) -> role from input or default OPERATOR -> persisted as MySQL ENUM
Login -> role read from DB -> embedded as `role` claim in JWT
Request -> authenticate copies claim to req.user.role -> requireRole compares against allowed list
```

---

### Business Rule: BR-02 Registration payload validation

**Overview**:
Inbound registration data is validated with Zod before reaching any business logic.

**Detailed description**:
`registerSchema` (`src/modules/auth/auth.schemas.ts:3-8`) requires: `email` a syntactically valid email with max length 255 (matches the `VarChar(255)` column); `password` length 8 to 72 (72 corresponds to bcrypt's effective input limit, preventing silent truncation); `name` length 2 to 150 (matches `VarChar(150)`); `role` optional enum `ADMIN | OPERATOR` defaulting to `OPERATOR`. Unknown extra properties are stripped by Zod's default object behavior, because `validate` replaces `req.body` with the parsed result (`src/middlewares/validate.middleware.ts:15`).

On failure, `validate` converts `ZodError` into `ValidationError` with `details: [{ path, message }]`, which the error middleware serializes as HTTP 400 `{ error: { code: 'VALIDATION_ERROR', message: 'Validation failed', details } }`. This is verified by the test "rejects register with invalid payload" (`tests/auth.test.ts:30-39`).

Email is not normalized (no lowercasing or trimming). Because MySQL's default collations are case-insensitive, `Foo@x.com` and `foo@x.com` are likely treated as equal by the unique index and by `findUnique`, but this depends on the database collation and is not enforced in code (confidence: medium). The schema is functionally identical to `createUserSchema` in `src/modules/users/user.schemas.ts:7-12`, which is declared but not wired to any route.

**Rule workflow**:
```
POST /auth/register body -> registerSchema.parse
  -> ok: req.body replaced by parsed (role defaulted) -> controller
  -> fail: ValidationError -> 400 VALIDATION_ERROR + details[]
```

---

### Business Rule: BR-03 Public self-registration with caller-selected role

**Overview**:
Any unauthenticated client can create a user account and choose its role, including `ADMIN`.

**Detailed description**:
The `/register` route is mounted without `authenticate` or `requireRole` (`src/modules/auth/auth.routes.ts:10`). The `role` field in `registerSchema` accepts `'ADMIN'` (`src/modules/auth/auth.schemas.ts:7`), and `AuthService.register` passes the input directly to `UserService.createUser` (`src/modules/auth/auth.service.ts:27-29`), which persists `input.role` unchanged (`src/modules/users/user.service.ts:31`).

The consequence is that the role boundary enforced by `requireRole('ADMIN')` on `GET /users/:id` can be bypassed by registering a new ADMIN account and logging in. No code, comment or README text documents this as intentional; it is therefore recorded as observed behavior, not as a confirmed business decision. The test suite exercises registration with `role: 'OPERATOR'` (`tests/auth.test.ts:11`) but never asserts that ADMIN self-registration is accepted or rejected.

The practical blast radius today is limited because the only ADMIN-only capability is reading any user's public profile by id. However, the meeting transcript (`TRANSCRICAO.md:208-212`) records a planned decision to reuse `requireRole` for an ADMIN-only DLQ replay endpoint, so any future ADMIN-only feature inherits this exposure.

**Rule workflow**:
```
Anonymous client -> POST /auth/register { role: 'ADMIN', ... }
  -> validate OK -> createUser(role=ADMIN) -> 201
  -> POST /auth/login -> JWT with role=ADMIN
  -> GET /users/:id passes requireRole('ADMIN')
```

---

### Business Rule: BR-04 Unique email at registration

**Overview**:
An email can be registered only once; duplicates are rejected with a specific error code.

**Detailed description**:
`UserService.createUser` first calls `users.findByEmail(input.email)`; if a user exists it throws `new ConflictError('Email already registered', 'EMAIL_ALREADY_USED')` (`src/modules/users/user.service.ts:22-25`), mapped to HTTP 409 with `error.code = 'EMAIL_ALREADY_USED'`. This is asserted by `tests/auth.test.ts:19-28`.

The check is a read-then-write (check-then-act) sequence without a transaction. Two concurrent registrations with the same email can both pass the check; the second `create` will then fail on the unique index `email @unique` (`prisma/schema.prisma:27`) with Prisma error `P2002`, which the error middleware maps to 409 with the generic code `CONFLICT` and message `Unique constraint violation on: <target>` (`src/middlewares/error.middleware.ts:37-46`). So the invariant holds, but the error code differs under race conditions.

This rule is owned by the Users module but is the effective uniqueness rule of the registration use case.

**Rule workflow**:
```
createUser -> findByEmail
  -> found: 409 EMAIL_ALREADY_USED
  -> not found: hash -> create
       -> race: Prisma P2002 -> 409 CONFLICT
       -> ok: 201
```

---

### Business Rule: BR-05 Password hashing and non-disclosure

**Overview**:
Passwords are stored only as bcrypt hashes and are never returned in any response.

**Detailed description**:
`UserService` hashes with `bcrypt.hash(input.password, BCRYPT_ROUNDS)` where `BCRYPT_ROUNDS = 10` is a module constant (`src/modules/users/user.service.ts:16`, `:26`). The cost factor is hardcoded, not configurable via environment. The same cost (10) is used by the seed (`prisma/seed.ts:191-192`) and the test factory (`tests/helpers/factories.ts:21`).

Login verifies with `bcrypt.compare(input.password, user.passwordHash)` (`src/modules/auth/auth.service.ts:36`). All outbound user representations go through `UserService.toPublic` (`src/modules/users/user.service.ts:42-51`), which whitelists `id, email, name, role, createdAt, updatedAt`; this is asserted by `tests/auth.test.ts:15-16` (`not.toHaveProperty('passwordHash')`).

The 72-character maximum on password inputs (BR-02, BR-06) aligns with bcrypt's 72-byte input limit. Note that the Zod limit is on characters, not bytes; multi-byte UTF-8 passwords shorter than 72 characters may still exceed 72 bytes and be truncated by bcrypt (confidence: high, based on bcrypt semantics; not tested).

**Rule workflow**:
```
register: plaintext -> bcrypt.hash(10) -> users.passwordHash
login: plaintext + stored hash -> bcrypt.compare -> boolean
any response: User -> toPublic (no passwordHash)
```

---

### Business Rule: BR-06 Login payload validation

**Overview**:
Login requires a valid email and a non-empty password up to 72 characters.

**Detailed description**:
`loginSchema` (`src/modules/auth/auth.schemas.ts:10-13`) enforces `email` as a valid email max 255 and `password` min 1 max 72. The minimum is intentionally looser than registration (1 vs 8), so policy changes in password length do not lock out existing users at the validation layer.

Validation failures produce 400 `VALIDATION_ERROR` before any database access, meaning malformed login attempts do not consume a bcrypt comparison.

No rate limiting, lockout, CAPTCHA or attempt counter exists anywhere in the component or the app pipeline (`src/app.ts:55-76`).

**Rule workflow**:
```
POST /auth/login body -> loginSchema.parse -> ok -> AuthService.login | fail -> 400
```

---

### Business Rule: BR-07 Uniform invalid-credentials response

**Overview**:
Login returns the same 401 error for an unknown email and for a wrong password.

**Detailed description**:
`AuthService.login` throws `new UnauthorizedError('Invalid credentials')` in both branches (`src/modules/auth/auth.service.ts:33-35` and `:37-39`). The serialized body is `{ error: { code: 'UNAUTHORIZED', message: 'Invalid credentials' } }`, so response content does not reveal whether the account exists. Covered by `tests/auth.test.ts:54-63` (wrong password only; unknown email is not tested).

However, the timing differs: for an unknown email the method returns immediately after the DB lookup, whereas for a known email it performs a bcrypt comparison (cost 10, typically tens of milliseconds). This timing difference can enable account enumeration. Separately, the registration endpoint returns `409 EMAIL_ALREADY_USED` for existing emails (BR-04), which is a direct enumeration oracle independent of login.

**Rule workflow**:
```
findByEmail -> null -> 401 Invalid credentials (fast path)
            -> user -> bcrypt.compare -> false -> 401 Invalid credentials (slow path)
                                      -> true  -> issue token
```

---

### Business Rule: BR-08 JWT issuance

**Overview**:
A successful login issues one signed JWT access token carrying the user's id, email and role.

**Detailed description**:
`AuthService.signToken` (`src/modules/auth/auth.service.ts:47-50`) calls `jwt.sign({ sub: userId, email, role }, env.JWT_SECRET, { expiresIn: env.JWT_EXPIRES_IN })`. No `algorithm` option is passed, so `jsonwebtoken@9.0.2` uses its default `HS256` (symmetric HMAC with the shared secret). `iat` is added automatically; `exp` derives from `expiresIn`. No `iss`, `aud`, `jti` or `nbf` claims are set.

`env.JWT_EXPIRES_IN` is a free-form string (default `'8h'`), cast to `SignOptions['expiresIn']` without format validation (`src/config/env.ts:9`; `src/modules/auth/auth.service.ts:48`). An invalid value (for example `'eight hours'`) would cause `jwt.sign` to throw at login time, which, not being an `AppError`, would surface as 500 `INTERNAL_SERVER_ERROR`.

There is no refresh token, no token revocation list, no logout endpoint and no persistence of issued tokens. The token is the sole credential for its entire lifetime. Because `role` is embedded, a role downgrade or user deletion is not reflected until expiry (see BR-12).

**Rule workflow**:
```
login success -> signToken(id, email, role)
  -> payload { sub, email, role, iat, exp } signed HS256 with JWT_SECRET
  -> returned as tokens.accessToken
```

---

### Business Rule: BR-09 Login response contract

**Overview**:
Login returns both the public user and a token descriptor.

**Detailed description**:
`LoginResult = { user: PublicUser; tokens: AuthTokens }`, where `AuthTokens = { accessToken: string; expiresIn: string; tokenType: 'Bearer' }` (`src/modules/auth/auth.service.ts:10-19`). `expiresIn` echoes the configured string (for example `"8h"`), not a numeric seconds value nor an absolute timestamp; clients must parse the duration string or decode the JWT `exp` claim to know the expiry instant.

`tokenType` is always the constant `'Bearer'`, matching the scheme required by `authenticate`. Tests assert `tokens.accessToken` is a string, `tokens.tokenType === 'Bearer'` and `user.email` matches (`tests/auth.test.ts:48-51`).

Registration (`201`) returns only `PublicUser` and no tokens; clients must call login separately.

**Rule workflow**:
```
200 { user: { id, email, name, role, createdAt, updatedAt },
      tokens: { accessToken, expiresIn: "<JWT_EXPIRES_IN>", tokenType: "Bearer" } }
```

---

### Business Rule: BR-10 Auth configuration constraints

**Overview**:
The JWT secret must be at least 16 characters; the token lifetime defaults to 8 hours; misconfiguration aborts startup.

**Detailed description**:
`envSchema` (`src/config/env.ts:3-10`) declares `JWT_SECRET: z.string().min(16, 'JWT_SECRET must be at least 16 characters')` and `JWT_EXPIRES_IN: z.string().default('8h')`. `loadEnv` runs at module import time; on failure it prints all issues and calls `process.exit(1)` (`src/config/env.ts:14-24`). Because `auth.middleware.ts` and `auth.service.ts` import `env`, any process loading the auth component validates the secret first.

`.env.example:8-9` ships `JWT_SECRET=change-me-in-production-please-use-a-long-random-secret` and `JWT_EXPIRES_IN=8h`. The placeholder secret satisfies the 16-character rule, so a deployment that copies `.env.example` will start successfully with a publicly known secret; nothing in code rejects the placeholder value or enforces higher entropy in `production`.

There are no environment-specific variations in code for auth (no different expiry or algorithm per `NODE_ENV`).

**Rule workflow**:
```
process start -> import env -> envSchema.safeParse(process.env)
  -> JWT_SECRET < 16 chars -> stderr + exit(1)
  -> ok -> env.JWT_SECRET / env.JWT_EXPIRES_IN used by sign/verify
```

---

### Business Rule: BR-11 Bearer header parsing and authentication errors

**Overview**:
`authenticate` accepts only `Authorization: Bearer <token>` and maps every failure to 401 `UNAUTHORIZED` with one of three messages.

**Detailed description**:
The middleware (`src/middlewares/auth.middleware.ts:28-49`) reads `req.headers.authorization`. If absent, or if `header.toLowerCase().startsWith('bearer ')` is false, it calls `next(new UnauthorizedError('Missing or invalid Authorization header'))`. The scheme comparison is case-insensitive (`Bearer`, `bearer`, `BEARER` accepted) but requires exactly one space after the scheme as part of the 7-character prefix.

The token is `header.slice(7).trim()`. If empty (for example `"Bearer    "`), it returns `UnauthorizedError('Missing bearer token')`. Otherwise it calls `jwt.verify(token, env.JWT_SECRET)`; any exception (bad signature, malformed token, `TokenExpiredError`, `NotBeforeError`) is caught by a bare `catch` and converted to `UnauthorizedError('Invalid or expired token')`. Expired and tampered tokens are therefore indistinguishable to the client, and the underlying cause is not logged.

`jwt.verify` is called without an `algorithms` option. With `jsonwebtoken@9`, a string secret restricts accepted algorithms to the HMAC family and rejects `none`, so the classic algorithm-confusion attack is mitigated by the library default rather than by explicit configuration (confidence: high, based on jsonwebtoken 9 behavior). No `issuer`/`audience` checks are performed. All three cases yield HTTP 401 with `error.code = 'UNAUTHORIZED'`; no `WWW-Authenticate` header is set.

**Rule workflow**:
```
header missing / not "bearer " -> 401 "Missing or invalid Authorization header"
token empty after trim          -> 401 "Missing bearer token"
jwt.verify throws               -> 401 "Invalid or expired token"
verify ok                       -> req.user = { id: sub, email, role } -> next()
```

---

### Business Rule: BR-12 Stateless identity from token claims

**Overview**:
The authenticated identity is taken entirely from the verified JWT; the database is not consulted.

**Detailed description**:
After verification the payload is cast with `as JwtPayload` (`src/middlewares/auth.middleware.ts:42`) and copied into `req.user` (`:43`). There is no runtime validation that `sub`, `email` and `role` exist or that `role` is one of the enum values. A token signed with the correct secret but lacking `role` would produce `req.user.role === undefined`, which would fail any `requireRole` check (403) but pass `authenticate`-only routes.

Because there is no DB lookup, the following are not enforced until token expiry (default 8h): a user whose role was changed keeps the old role; a deleted user keeps access to customers/products/orders; there is no account disable/lock concept in the schema (`prisma/schema.prisma:25-38`). The only place the user is re-read is `/auth/me` (BR-16). For order creation, a deleted user's id would be written to `createdById`, which would fail the foreign key and surface as a Prisma error (likely 500, since only P2002/P2025 are mapped) (confidence: medium).

The design gives O(1) per-request authentication with no DB round trip, at the cost of revocation latency.

**Rule workflow**:
```
verified payload -> cast (no schema check) -> req.user { id, email, role }
downstream code trusts req.user without re-fetching user
```

---

### Business Rule: BR-13 requireRole semantics

**Overview**:
`requireRole(...roles)` is a middleware factory that authorizes when the authenticated user's role is any of the listed roles.

**Detailed description**:
Implementation (`src/middlewares/auth.middleware.ts:51-63`): it closes over a variadic `roles: AuthUser['role'][]` array. At request time: if `req.user` is undefined, it calls `next(new UnauthorizedError())` (401, message `'Unauthorized'`); if `!roles.includes(req.user.role)`, it calls `next(new ForbiddenError('Insufficient permissions'))` (403, code `FORBIDDEN`); otherwise `next()`.

Semantics: OR/membership over a flat list; no hierarchy, no permissions/scopes, no resource ownership checks. Calling `requireRole()` with no arguments would deny everyone authenticated (403), since `[].includes(x)` is false. The factory depends on `authenticate` having run earlier in the chain; it does not verify tokens itself. Its 401 branch is a defensive guard for mis-ordered middleware.

Ordering matters for error precedence. In `src/modules/users/user.routes.ts:12-18` the chain is `authenticate -> requireRole('ADMIN') -> validate(params) -> controller`. Thus an OPERATOR requesting `/users/not-a-uuid` gets 403, not 400; an ADMIN gets 400 `VALIDATION_ERROR`; an ADMIN with a valid but unknown uuid gets 404 `NOT_FOUND` with message `User not found`.

**Rule workflow**:
```
requireRole('ADMIN') ->
  req.user missing          -> 401 UNAUTHORIZED "Unauthorized"
  req.user.role not in list -> 403 FORBIDDEN "Insufficient permissions"
  otherwise                 -> next()
```

---

### Business Rule: BR-14 Route protection matrix

**Overview**:
Protection is applied per router: auth routes are mixed, users route is ADMIN-only, all other resource routers require authentication for every route but no specific role.

**Detailed description**:
Application mounting: `/health` is public (`src/app.ts:62-64`); everything else is under `/api/v1` via `buildApiRouter` (`src/app.ts:67`, `src/routes/index.ts:21-31`). No global auth middleware is applied at app or API-router level; each module router decides.

- `auth.routes.ts`: `register` and `login` are public; `me` uses per-route `authenticate` (`src/modules/auth/auth.routes.ts:10-12`).
- `user.routes.ts`: single route `GET /:id` with `authenticate, requireRole('ADMIN')` per-route (`src/modules/users/user.routes.ts:12-18`). The router does not expose user creation; `createUserSchema` exists but is unused.
- `customer.routes.ts`, `product.routes.ts`, `order.routes.ts`: `router.use(authenticate)` at the top of the router (`:14` in each), so every route including `DELETE` requires a valid token, and neither ADMIN nor OPERATOR is distinguished.

Consequences: OPERATOR can create/update/delete customers and products, create orders, change any order's status (including CANCELLED) and delete orders. There is no ownership rule (an OPERATOR can modify orders created by others). Per `TRANSCRICAO.md:212-214`, the team intends future webhook CRUD to be "any authenticated role" and DLQ replay to be ADMIN-only using the existing `requireRole`, which is consistent with this pattern.

**Rule workflow**: see section 7 for the full endpoint/role table.

---

### Business Rule: BR-15 Auth-related error codes

**Overview**:
Auth failures use the shared `AppError` hierarchy and the standard JSON error envelope.

**Detailed description**:
`UnauthorizedError` -> status 401, `errorCode 'UNAUTHORIZED'`, default message `'Unauthorized'` (`src/shared/errors/http-errors.ts:15-19`). `ForbiddenError` -> 403, `'FORBIDDEN'`, default `'Forbidden'` (`:21-25`). Both extend `AppError` (`src/shared/errors/app-error.ts:3-16`) and are rendered by `errorMiddleware` as `{ error: { code, message } }` without `details` (`src/middlewares/error.middleware.ts:15-24`).

Messages emitted by this component:

| Source | HTTP | code | message |
|--------|------|------|---------|
| authenticate, header missing/wrong scheme | 401 | UNAUTHORIZED | Missing or invalid Authorization header |
| authenticate, empty token | 401 | UNAUTHORIZED | Missing bearer token |
| authenticate, verify failure/expired | 401 | UNAUTHORIZED | Invalid or expired token |
| requireRole, no req.user | 401 | UNAUTHORIZED | Unauthorized |
| requireRole, role not allowed | 403 | FORBIDDEN | Insufficient permissions |
| AuthService.login, unknown email or bad password | 401 | UNAUTHORIZED | Invalid credentials |
| AuthController.me, no req.user | 401 | UNAUTHORIZED | Unauthorized |
| validate (register/login/users param) | 400 | VALIDATION_ERROR | Validation failed (+ details) |
| UserService.createUser duplicate | 409 | EMAIL_ALREADY_USED | Email already registered |
| Prisma P2002 race on email | 409 | CONFLICT | Unique constraint violation on: ... |
| UserService.getById (me, users/:id) | 404 | NOT_FOUND | User not found |

Auth errors are not logged by the error middleware (only non-AppError 500s are logged), but every request, including 401/403 responses, is logged by `requestLogger` with status code and `userId` when available.

**Rule workflow**:
```
throw/next(AppError subclass) -> errorMiddleware -> res.status(statusCode).json({ error: { code, message } })
```

---

### Business Rule: BR-16 Current-user profile (`/auth/me`)

**Overview**:
Returns the fresh database profile of the user identified by the token's `sub`.

**Detailed description**:
`AuthController.me` (`src/modules/auth/auth.controller.ts:30-38`) checks `req.user` (defensive, as `authenticate` precedes it), then calls `UserService.getById(req.user.id)` and returns 200 with `PublicUser`. Because it re-reads the DB, the response reflects the current role and name, which may differ from the `role` claim in the token used for the call.

If the user was deleted after the token was issued, `getById` throws `NotFoundError('User')` -> 404 `NOT_FOUND` "User not found", not 401. Tests cover the 200 path (`tests/auth.test.ts:65-77`) and the missing-token 401 path (`:79-83`).

`AuthController` depends on `UserService` directly (injected in `src/app.ts:32`), not via `AuthService`.

**Rule workflow**:
```
GET /auth/me -> authenticate -> me -> userService.getById(sub) -> 200 PublicUser | 404
```

---

### Business Rule: BR-17 Actor attribution for orders

**Overview**:
The authenticated user's id is recorded as the creator of orders and as the actor of status changes.

**Detailed description**:
`OrderController.create` and `changeStatus` check `req.user` and pass `req.user.id` to the service (`src/modules/orders/order.controller.ts:30-31`, `:40-41`), which persist it in `Order.createdById` and `OrderStatusHistory.changedById` (`prisma/schema.prisma:83`, `:122`). This is the only cross-module consumption of `req.user` beyond logging and `/auth/me`.

The role is not used in order logic; both roles can perform any transition allowed by the order state machine. Attribution relies on the token's `sub`, which is trusted per BR-12.

**Rule workflow**:
```
authenticate -> req.user.id -> OrderService.create(..., userId) / changeStatus(..., userId) -> DB audit columns
```

---

### Business Rule: BR-18 Authenticated user in access logs

**Overview**:
Each completed request is logged with the authenticated user id when present.

**Detailed description**:
`requestLogger` is registered before routing (`src/app.ts:60`) but logs on the response `finish` event, by which time `authenticate` may have populated `req.user`. It logs `userId: req.user?.id` (`src/middlewares/request-logger.middleware.ts:21`). For public routes or failed authentication the field is undefined.

The `Request` interface augmentation for `user` and `id` lives in `auth.middleware.ts:12-17`, so the logger implicitly depends on the auth module for its typing.

Neither email nor role is logged, and failed login attempts are not logged with the attempted email.

**Rule workflow**:
```
request -> requestLogger (sets req.id) -> ... authenticate sets req.user -> response finish -> log { requestId, method, path, statusCode, durationMs, userId }
```

---

### Business Rule: BR-19 Seeded default accounts

**Overview**:
The seed script creates one ADMIN and one OPERATOR with hardcoded passwords.

**Detailed description**:
`prisma/seed.ts:6-7` defines `ADMIN_PASSWORD = 'admin123'` and `OPERATOR_PASSWORD = 'operator123'`; users `admin@oms.local` (ADMIN) and `operador@oms.local` (OPERATOR) are created at `:194-210`. Note `admin123` is 8 characters and `operator123` is 11, both satisfying the registration minimum, though the seed bypasses validation anyway.

The seed deletes all users first (`:186`). It is run via `npm run db:seed` with `.env`. Nothing prevents running it against a production database.

These accounts are the expected bootstrap path for obtaining an ADMIN; however, BR-03 makes ADMIN obtainable without them.

**Rule workflow**:
```
npm run db:seed -> wipe tables -> create admin@oms.local (ADMIN) + operador@oms.local (OPERATOR) with bcrypt(10) hashes
```

---

## 4. Component Structure

```
src/
├── middlewares/
│   ├── auth.middleware.ts          # authenticate (JWT verify), requireRole factory, AuthUser type, Express Request augmentation
│   ├── validate.middleware.ts      # (collaborator) Zod validation used by auth routes
│   ├── error.middleware.ts         # (collaborator) serializes UnauthorizedError/ForbiddenError
│   └── request-logger.middleware.ts# (consumer) logs req.user?.id
├── modules/
│   ├── auth/
│   │   ├── auth.routes.ts          # POST /register, POST /login, GET /me
│   │   ├── auth.controller.ts      # AuthController: register, login, me
│   │   ├── auth.service.ts         # AuthService: register (delegates), login, signToken; AuthTokens/LoginResult types
│   │   └── auth.schemas.ts         # registerSchema, loginSchema (Zod)
│   ├── users/                      # (collaborator) UserService.createUser/getById/toPublic, UserRepository, ADMIN-only route
│   │   └── user.routes.ts          # only consumer of requireRole('ADMIN')
│   ├── customers/customer.routes.ts# router.use(authenticate)
│   ├── products/product.routes.ts  # router.use(authenticate)
│   └── orders/order.routes.ts      # router.use(authenticate); controller reads req.user.id
├── config/env.ts                   # JWT_SECRET (min 16), JWT_EXPIRES_IN (default 8h)
├── shared/errors/                  # AppError, UnauthorizedError (401), ForbiddenError (403)
├── routes/index.ts                 # mounts /auth and other routers
└── app.ts                          # composition root (DI wiring of AuthService/AuthController)
prisma/
├── schema.prisma                   # enum UserRole, model User
└── seed.ts                         # default admin/operator accounts
tests/
├── auth.test.ts                    # auth integration tests
├── orders.test.ts                  # uses authenticated OPERATOR tokens
└── helpers/factories.ts            # createTestUser, loginAndGetToken, bootstrapAuthenticatedUser
```

---

## 5. Dependency Analysis

```
Internal Dependencies:
auth.routes      -> validate.middleware, auth.middleware(authenticate), auth.schemas, AuthController(type)
AuthController   -> AuthService, UserService, shared/errors(UnauthorizedError)
AuthService      -> UserRepository(findByEmail), UserService(createUser, toPublic), config/env, shared/errors
auth.middleware  -> config/env(JWT_SECRET), shared/errors(UnauthorizedError, ForbiddenError)
user.routes      -> auth.middleware(authenticate, requireRole), validate.middleware
customer/product/order.routes -> auth.middleware(authenticate), validate.middleware
OrderController  -> req.user (populated by authenticate), shared/errors(UnauthorizedError)
request-logger   -> req.user (type augmentation declared in auth.middleware)
app.ts           -> new AuthService(userRepository, userService); new AuthController(authService, userService)

External Dependencies:
- jsonwebtoken 9.0.2   - JWT sign (HS256 default) and verify
- bcrypt 5.1.1         - password hashing (cost 10) and comparison
- zod 3.23.8           - request schema validation and env validation
- express 4.21.1       - RequestHandler, Router, Request type augmentation via express-serve-static-core
- @prisma/client 5.22.0- User model / UserRole enum persistence (MySQL)
```

---

## 6. Afferent and Efferent Coupling

Counts are distinct modules/classes depending on (afferent, Ca) or depended upon by (efferent, Ce) each unit, within `src/` and `tests/` (excluding framework libs from Ca; Ce includes external libs).

| Component | Afferent Coupling (Ca) | Efferent Coupling (Ce) | Critical |
|-----------|------------------------|------------------------|----------|
| `authenticate` (auth.middleware.ts) | 5 (auth/user/customer/product/order routes) | 3 (jsonwebtoken, env, UnauthorizedError) | High |
| `requireRole` (auth.middleware.ts) | 1 (user.routes) | 2 (UnauthorizedError, ForbiddenError) | Medium |
| `AuthUser` type + Request augmentation | 4 (auth.middleware, request-logger, auth.controller, order.controller via `req.user`) | 1 (express-serve-static-core) | High |
| `AuthService` | 2 (AuthController, app.ts) | 6 (bcrypt, jsonwebtoken, env, UnauthorizedError, UserRepository, UserService) | Medium |
| `AuthController` | 3 (auth.routes, routes/index, app.ts) | 3 (AuthService, UserService, UnauthorizedError) | Low |
| `auth.schemas` (registerSchema, loginSchema) | 2 (auth.routes, auth.service types) | 1 (zod) | Low |
| `buildAuthRouter` | 1 (routes/index) | 4 (express Router, validate, authenticate, auth.schemas) | Low |
| `UnauthorizedError` / `ForbiddenError` | 5 / 1 (auth.middleware, auth.service, auth.controller, order.controller, errors index) | 1 (AppError) | High |
| `env.JWT_SECRET` / `JWT_EXPIRES_IN` | 2 (auth.middleware, auth.service) | 1 (zod) | High |
| `UserService` (as used by auth) | 3 (AuthService, AuthController, UserController) | 4 (bcrypt, UserRepository, ConflictError, NotFoundError) | High |

Observations: `authenticate` is the single most depended-on unit of the component (every protected route); a defect there affects the entire API surface. The auth module has no dedicated repository and is tightly coupled to the Users module (`UserRepository` and `UserService`), so the auth/users boundary is shared rather than encapsulated.

---

## 7. Endpoints

### 7.1 Endpoints owned by the auth module

| Endpoint | Method | Auth | Role | Description |
|----------|--------|------|------|-------------|
| /api/v1/auth/register | POST | Public | - | Create user (any role, default OPERATOR); returns 201 PublicUser |
| /api/v1/auth/login | POST | Public | - | Verify credentials; returns 200 { user, tokens } |
| /api/v1/auth/me | GET | Bearer JWT | Any | Return current user's public profile from DB |

### 7.2 Role application across all `*.routes.ts`

| Endpoint | Method | authenticate | requireRole | Location |
|----------|--------|--------------|-------------|----------|
| /health | GET | No | - | src/app.ts:62 |
| /api/v1/auth/register | POST | No | - | src/modules/auth/auth.routes.ts:10 |
| /api/v1/auth/login | POST | No | - | src/modules/auth/auth.routes.ts:11 |
| /api/v1/auth/me | GET | Yes (per-route) | - | src/modules/auth/auth.routes.ts:12 |
| /api/v1/users/:id | GET | Yes (per-route) | ADMIN | src/modules/users/user.routes.ts:12-18 |
| /api/v1/customers | GET | Yes (router.use) | - | src/modules/customers/customer.routes.ts:14,16 |
| /api/v1/customers/:id | GET | Yes | - | customer.routes.ts:17 |
| /api/v1/customers | POST | Yes | - | customer.routes.ts:18 |
| /api/v1/customers/:id | PATCH | Yes | - | customer.routes.ts:19-23 |
| /api/v1/customers/:id | DELETE | Yes | - | customer.routes.ts:24 |
| /api/v1/products | GET | Yes (router.use) | - | src/modules/products/product.routes.ts:14,16 |
| /api/v1/products/:id | GET | Yes | - | product.routes.ts:17 |
| /api/v1/products | POST | Yes | - | product.routes.ts:18 |
| /api/v1/products/:id | PATCH | Yes | - | product.routes.ts:19-23 |
| /api/v1/products/:id | DELETE | Yes | - | product.routes.ts:24 |
| /api/v1/orders | GET | Yes (router.use) | - | src/modules/orders/order.routes.ts:14,16 |
| /api/v1/orders/:id | GET | Yes | - | order.routes.ts:17 |
| /api/v1/orders | POST | Yes | - | order.routes.ts:18 |
| /api/v1/orders/:id/status | PATCH | Yes | - | order.routes.ts:19-23 |
| /api/v1/orders/:id | DELETE | Yes | - | order.routes.ts:24 |

Note: because `router.use(authenticate)` is registered on routers mounted at specific prefixes, unmatched paths under `/api/v1/customers|products|orders/...` return 401 before reaching the global 404 handler, whereas unmatched paths elsewhere return 404.

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| MySQL `users` table via Prisma (UserRepository) | Database | Lookup by email/id, create user | Prisma client / MySQL wire | Prisma `User` model | Errors bubble to errorMiddleware; P2002 -> 409 CONFLICT, P2025 -> 404, others -> 500 |
| jsonwebtoken | Library | Sign/verify HS256 tokens | In-process | JWT (JWS compact) | verify errors caught -> 401; sign errors uncaught -> 500 |
| bcrypt | Native library | Hash/compare passwords | In-process (libuv threadpool) | bcrypt hash string | Errors propagate -> 500 |
| Environment (`process.env`) | Configuration | JWT_SECRET, JWT_EXPIRES_IN | Env vars / `--env-file=.env` | Strings validated by Zod | Invalid -> process.exit(1) at startup |
| HTTP clients | Inbound API | Register, login, access protected resources | HTTPS/REST (TLS assumed at infra, not in code) | JSON; `Authorization: Bearer` header | Standard `{ error: { code, message, details? } }` envelope |
| Users module | Internal module | User persistence and public projection | In-process calls | PublicUser / User | ConflictError, NotFoundError |
| Orders module | Internal consumer | Actor attribution from `req.user.id` | In-process | string uuid | Defensive 401 if `req.user` missing |
| request-logger (Pino) | Internal consumer | Log `userId` | In-process | JSON logs | n/a |

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Middleware / Chain of Responsibility | `authenticate`, `requireRole`, `validate` chained before controllers | src/middlewares/auth.middleware.ts; *.routes.ts | Cross-cutting authN/authZ separated from handlers |
| Factory function (higher-order middleware) | `requireRole(...roles)` returns a RequestHandler | src/middlewares/auth.middleware.ts:51 | Parameterized role policy per route |
| Stateless token authentication | JWT with claims `sub/email/role`, HS256 | auth.service.ts:47-50; auth.middleware.ts:42 | No server-side session store |
| Role-Based Access Control (flat) | Two roles, membership check | auth.middleware.ts:57 | Coarse-grained authorization |
| Layered architecture (Router -> Controller -> Service -> Repository) | auth.routes -> AuthController -> AuthService -> UserRepository | src/modules/auth/* | Separation of HTTP, business, data concerns |
| Constructor Dependency Injection / Composition Root | `buildControllers` wires services and controllers | src/app.ts:26-53 | Testability, explicit wiring |
| Router builder functions | `buildAuthRouter(controller)` | auth.routes.ts:7 | Routers receive controllers instead of instantiating them |
| Facade / Delegation | `AuthService.register` delegates to `UserService.createUser` | auth.service.ts:27-29 | Reuse user creation logic |
| DTO / Projection | `UserService.toPublic` -> PublicUser | src/modules/users/user.service.ts:42-51 | Prevent leaking passwordHash |
| Schema validation at the edge | Zod `registerSchema`, `loginSchema` + `validate` middleware | auth.schemas.ts; validate.middleware.ts | Fail-fast input validation |
| Exception hierarchy + centralized handler | `UnauthorizedError`, `ForbiddenError` extends `AppError`; `errorMiddleware` | src/shared/errors/*; error.middleware.ts | Uniform error envelope and codes |
| Type augmentation (module declaration merging) | `declare module 'express-serve-static-core' { interface Request { user?, id? } }` | auth.middleware.ts:12-17 | Typed `req.user` across the app |
| Fail-fast configuration | Zod env schema with `process.exit(1)` | src/config/env.ts | Prevent running with weak/missing secret |
| Arrow-function class properties | Controller handlers as properties | auth.controller.ts:12,21,30 | Preserve `this` when passed as callbacks |

Architectural decisions observed: per-router (not global) authentication; authorization expressed at the route layer only (no service-level checks); auth module reuses Users persistence rather than owning credentials storage; access token only (no refresh/revocation).

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| Critical | auth.schemas / auth.routes (register) | Public registration accepts `role: 'ADMIN'` (auth.schemas.ts:7, auth.routes.ts:10) | Any anonymous client can obtain ADMIN; `requireRole('ADMIN')` is effectively bypassable |
| High | Route matrix (customers/products/orders) | Only one route uses `requireRole`; all destructive operations (DELETE, status changes) are open to OPERATOR | Role model provides almost no differentiation; least-privilege not applied |
| High | auth.middleware (authenticate) | No user existence/role re-check; role embedded in token for up to 8h; no revocation/logout | Deleted or downgraded users retain access until expiry |
| High | config/env + .env.example | Placeholder secret in `.env.example` passes the 16-char rule; no production guard | Risk of deploying with a known signing secret, enabling token forgery |
| Medium | auth.middleware | Payload cast `as JwtPayload` without runtime validation (auth.middleware.ts:42) | Malformed-but-signed tokens produce undefined `req.user` fields |
| Medium | auth.middleware / auth.service | No explicit `algorithms`, `issuer`, `audience` on sign/verify | Security relies on library defaults; tokens not scoped to this API |
| Medium | auth.service (login) | Timing difference between unknown-email and wrong-password paths; register returns `EMAIL_ALREADY_USED` | Account enumeration |
| Medium | Login endpoint | No rate limiting / lockout anywhere in pipeline (src/app.ts) | Brute-force and credential-stuffing exposure |
| Medium | auth.service (signToken) | `JWT_EXPIRES_IN` is unvalidated free-form string cast to SignOptions | Misconfiguration yields 500 at login instead of failing at startup |
| Medium | Tests | No tests for requireRole/403, invalid/expired/malformed tokens, `/users/:id` | Authorization regressions undetected |
| Low | Role literals | `'ADMIN' \| 'OPERATOR'` duplicated in 7+ places instead of Prisma `UserRole` | Drift risk when adding roles |
| Low | user.service (createUser) | Check-then-insert race returns `CONFLICT` instead of `EMAIL_ALREADY_USED` | Inconsistent error code under concurrency |
| Low | auth/users schemas | `registerSchema` duplicates unused `createUserSchema` | Dead code / dual maintenance |
| Low | auth.middleware | Bare `catch` discards error cause; expired vs invalid indistinguishable; not logged | Reduced diagnosability; clients cannot distinguish refresh-needed vs tampered |
| Low | user.routes ordering | `requireRole` before `validate` | 403 precedes 400 for non-admins (behavioral detail, not defect) |
| Low | Email handling | No normalization (case/whitespace); relies on DB collation | Possible duplicate-looking accounts depending on collation |
| Low | Password limits | 72-character limit is by characters, bcrypt limit is 72 bytes | Silent truncation for multibyte passwords |
| Low | user.service | bcrypt cost factor 10 hardcoded | Cannot tune per environment |
| Low | Request augmentation location | `Request.user`/`Request.id` declared in auth.middleware.ts but `id` is set by request-logger | Hidden coupling; logger typing depends on auth module import |
| Low | seed.ts | Hardcoded weak default passwords; seed wipes users | Risk if run against non-dev DB |

---

## 11. Test Coverage Analysis

Test infrastructure: Vitest 2.1.4 + Supertest, integration-style against a real MySQL database (`tests/setup.ts` connects Prisma and truncates tables before each test), single fork, no parallelism (`vitest.config.ts`). No unit tests with mocks exist; no coverage tool/threshold is configured, so percentages below are qualitative estimates by code path, not measured values.

Test files located:
- `tests/auth.test.ts` - 7 integration tests for the auth module
- `tests/orders.test.ts` - 8 tests that use `authenticate` indirectly (OPERATOR tokens)
- `tests/helpers/factories.ts` - `createTestUser`, `loginAndGetToken`, `bootstrapAuthenticatedUser(role = 'OPERATOR')`
- `tests/setup.ts` - DB lifecycle

| Component | Unit Tests | Integration Tests | Coverage (estimated by path) | Test Quality |
|-----------|------------|-------------------|------------------------------|--------------|
| AuthController.register / AuthService.register | 0 | 3 (201 success, 409 duplicate, 400 invalid) - auth.test.ts:6-39 | High | Good assertions on status, code, absence of passwordHash; ADMIN self-registration not asserted |
| AuthService.login | 0 | 2 (200 success, 401 wrong password) - auth.test.ts:41-63; plus indirect via loginAndGetToken | Medium | Unknown-email path, 400 validation, token claims/expiry not asserted |
| AuthController.me | 0 | 2 (200 success, 401 no token) - auth.test.ts:65-83 | Medium | 404 for deleted user not tested |
| authenticate | 0 | 1 explicit negative (no header) + many indirect positives (orders.test.ts all 8 tests) | Low-Medium | Wrong scheme, empty token, invalid signature, expired token, tampered token: not tested; 401 response body code not asserted on /me |
| requireRole | 0 | 0 | None | No test for ADMIN allowed / OPERATOR 403 / missing user |
| GET /users/:id (only ADMIN route) | 0 | 0 | None | Endpoint completely untested |
| auth.schemas | 0 | 1 (invalid register payload) | Low | No boundary tests (password 7/8/72/73 chars, name length, invalid role) |
| Role application on customers/products routes | 0 | 0 | None | No tests for customers/products modules at all, including 401 behavior |
| Role application on orders routes | 0 | 8 (authenticated as OPERATOR) | Partial | Only positive authenticated paths; no unauthenticated 401 check; ADMIN never exercised |
| env (JWT config) | 0 | 0 | None | Startup validation untested |

Summary: the happy paths of registration, login and `/me` are covered with meaningful assertions. The authorization half of the component (`requireRole`, 403 `FORBIDDEN`, ADMIN-only route) has zero coverage, and token-rejection branches of `authenticate` beyond "no header" are untested. `bootstrapAuthenticatedUser` supports an ADMIN role parameter but no test passes it.
