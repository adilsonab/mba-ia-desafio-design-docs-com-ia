# Component Deep Analysis Report

**Component:** PersistenceLayer
**Scope:** `prisma/schema.prisma`, `prisma/migrations/*`, `prisma/seed.ts`, `src/config/database.ts`, and the way repositories, services and tests use Prisma
**Project:** Order Management System REST API (`order-management-api`)
**Analysis date:** 2026-11-02
**Excluded folders:** `node_modules`, `dist`, `.git`, `docs`

---

## 1. Executive Summary

The PersistenceLayer is the data-access foundation of the Order Management System. It is built on **Prisma ORM 5.22.0** (`prisma` CLI and `@prisma/client`, both pinned in `package.json`) over **MySQL 8.0** (`docker-compose.yml:3`). It is made of four parts:

1. **Declarative schema** (`prisma/schema.prisma`). It defines 7 models (`User`, `Customer`, `Product`, `Order`, `OrderItem`, `OrderStatusHistory`, `OrderNumberSequence`) and 2 enums (`UserRole`, `OrderStatus`).
2. **One versioned migration** (`prisma/migrations/20260519182739_init/migration.sql`). It creates every table with `utf8mb4` / `utf8mb4_unicode_ci`, 6 foreign keys and 15 secondary/unique indexes.
3. **A single shared `PrismaClient`** (`src/config/database.ts`). It is created once at module load and injected by hand through `buildApp({ prisma })` into four repositories and into `OrderService`.
4. **A destructive seed script** (`prisma/seed.ts`). It wipes all tables and loads 2 users, 10 customers, 20 products and 26 orders with a synthetic status history.

Main findings:

- **Identity and naming:** every entity uses a client-generated UUID v4 stored as `CHAR(36)`. The one exception is a singleton counter table (`order_number_sequence`, `INT id = 1`). Table names are snake_case through `@@map`, but **column names stay camelCase** because no `@map` is used anywhere (e.g. `passwordHash`, `createdAt`, `customerId`).
- **Money and quantities** are stored as signed 32-bit `INTEGER` in cents (`priceCents`, `subtotalCents`, `discountCents`, `totalCents`, `unitPriceCents`). The database has no CHECK constraints, so non-negativity is enforced only by Zod schemas and service code.
- **Referential integrity:** the order aggregate (`Order` -> `OrderItem`, `OrderStatusHistory`) uses `ON DELETE CASCADE`. All references to master data (`Customer`, `Product`, `User`) use `ON DELETE RESTRICT`. The FK violation error `P2003` is **not translated** by the error middleware, so deleting a customer or product that is still referenced returns HTTP 500.
- **Transactions are used in two styles:**
  - **Batch (array) `$transaction`**, for consistent paged lists (`findMany` + `count`) in 3 repositories.
  - **Interactive `$transaction(async tx => ...)`**, for order creation, status change (with stock debit/replenish) and order-number reservation.
  No isolation level, timeout or retry is configured, and there is no pessimistic locking. The stock check-then-decrement and the order status check are therefore exposed to concurrency anomalies.
- **Order numbering** (`ORD-000001`) comes from an atomic `upsert` + `increment` on a single-row table inside the order-creation transaction. This serializes order creation on one hot row.
- **The repository abstraction is partial.** Repositories only accept `PrismaClient`, not `Prisma.TransactionClient`, so `OrderService` bypasses them and calls `tx.*` delegates directly for all transactional work.
- **Tests are integration-only.** They run against the real database named by `DATABASE_URL` and truncate every table before each test. No dedicated test database or unit tests for the persistence layer exist.

---

## 2. Data Flow Analysis

### 2.1 Bootstrap and connection lifecycle

```
1. src/server.ts imports src/config/database.ts
2. database.ts imports src/config/env.ts -> env is parsed with Zod (DATABASE_URL required, min length 1)
3. createPrismaClient() builds a PrismaClient with log levels ['warn','error'] (development) or ['error'] (others)
4. The module-level singleton `prisma` is exported (database.ts:10)
5. server.ts calls buildApp({ prisma }) -> app.ts:buildControllers(prisma)
6. app.ts creates UserRepository, CustomerRepository, ProductRepository, OrderRepository (each gets prisma)
   and OrderService(orderRepository, prisma)
7. The connection is opened lazily on the first query (no explicit $connect in server.ts)
8. On SIGINT/SIGTERM: server.close() -> prisma.$disconnect() -> process.exit(0) (server.ts:13-18)
```

### 2.2 Simple CRUD read/write (Customer, Product, User)

```
1. HTTP request -> validate middleware (Zod) -> Controller
2. Service performs a pre-check through the repository (findById / findByEmail / findBySku)
3. Service throws an AppError (NotFound / Conflict) when the pre-check fails
4. Repository calls the prisma.<model>.create/update/delete delegate (no transaction)
5. Prisma generates SQL -> MySQL (table names from @@map)
6. If MySQL raises a unique violation not caught by the pre-check -> PrismaClientKnownRequestError P2002
   -> error.middleware.ts:38 -> HTTP 409 CONFLICT
7. If the record vanished between check and write -> P2025 -> error.middleware.ts:48 -> HTTP 404
8. If an FK RESTRICT blocks a delete -> P2003 -> not mapped -> HTTP 500 (error.middleware.ts:62)
```

### 2.3 Paginated list (Customer, Product, Order)

```
1. Service converts page/pageSize to skip/take ((page-1)*pageSize, pageSize)
2. Repository builds a Prisma WhereInput (buildWhere)
3. prisma.$transaction([findMany(where, orderBy createdAt desc, skip, take), count(where)])
   -> both queries run in one DB transaction (batch form)
4. Service wraps the result with paginated() -> { data, pagination: { page, pageSize, total, totalPages } }
```

### 2.4 Order creation (interactive transaction)

```
1. OrderService.create validates items.length > 0 and aggregates duplicate productIds (in memory)
2. prisma.$transaction(async tx => {...}) opens an interactive transaction
3. tx.customer.findUnique -> NotFoundError('Customer') if missing
4. tx.product.findMany({ id in [...] }) -> NotFoundError('Product') if count differs
5. Inactive products -> UnprocessableEntityError INACTIVE_PRODUCT
6. Prices are snapshotted: unitPriceCents = product.priceCents; totalCents = unit * qty
7. subtotal is computed; discount > subtotal -> ValidationError
8. reserveOrderNumber(tx): tx.orderNumberSequence.upsert(id=1, increment nextValue) -> "ORD-%06d"
9. tx.order.create with nested items.create[] and history.create (null -> PENDING, reason 'order created'),
   including items.product(id, sku, name), history (asc by changedAt) and customer(id, name, email)
10. Commit -> the response returns the OrderWithRelations shape
    Any thrown error -> rollback (including the sequence increment)
```

### 2.5 Order status change (interactive transaction)

```
1. prisma.$transaction(async tx => {...})
2. tx.order.findUnique({ id, include items }) -> NotFoundError if missing
3. from === to -> ConflictError INVALID_STATUS_TRANSITION
4. canTransition(from, to) false -> InvalidStatusTransitionError
5. shouldDebitStock (PENDING -> PAID): read products, verify stockQuantity >= quantity for every item,
   else InsufficientStockError; then tx.product.update(stockQuantity decrement) per item (sequential)
6. shouldReplenishStock (PAID|PROCESSING -> CANCELLED): tx.product.update(stockQuantity increment) per item
7. tx.order.update({ status: to })
8. tx.orderStatusHistory.create({ fromStatus, toStatus, changedById, reason })
9. tx.order.findUnique with the full include -> returned (non-null assertion)
10. Commit / rollback
```

### 2.6 Order deletion

```
1. OrderRepository.findById (outside any transaction)
2. Status must be PENDING or CANCELLED, else ConflictError INVALID_ORDER_STATE_FOR_DELETE
3. OrderRepository.deleteById -> DELETE orders -> ON DELETE CASCADE removes order_items and order_status_history
```

### 2.7 Seed flow (`prisma/seed.ts`)

```
1. New, separate PrismaClient (does not reuse src/config/database.ts)
2. deleteMany in FK-safe order: history -> items -> orders -> products -> customers -> users -> sequence
3. bcrypt hash of hard-coded passwords (cost 10) -> 2 users (ADMIN, OPERATOR)
4. Promise.all creates for 10 customers and 20 products (concurrent inserts)
5. For each of 26 planned orders: reserveOrderNumber() in its own $transaction -> order.create with nested items
   -> sequential orderStatusHistory.create rows that rebuild the path to the target status
6. $disconnect in finally; exit code 1 on failure
```

---

## 3. Business Rules & Logic

### Overview of the business rules

| # | Rule Type | Rule Description | Location |
|---|-----------|------------------|----------|
| 1 | Data Model / Identity | All entity PKs are UUID strings generated by Prisma (`@default(uuid())`), stored as `CHAR(36)` | prisma/schema.prisma:26,41,57,75,100,117 |
| 2 | Data Model / Identity | `OrderNumberSequence` is a singleton row with `INT id @default(1)` | prisma/schema.prisma:133-138 |
| 3 | Naming Convention | Tables are mapped to snake_case plural names through `@@map`; columns keep camelCase | prisma/schema.prisma:37,53,71,96,113,130,137; migration.sql |
| 4 | Naming Convention | Constraint/index names follow Prisma defaults `<table>_<col>_key/_idx/_fkey` | migration.sql:11-125 |
| 5 | Timestamps | `createdAt @default(now())` and `updatedAt @updatedAt` (client-managed) on User, Customer, Product, Order; OrderItem has only `createdAt`; history uses `changedAt` | prisma/schema.prisma:31-32,47-48,64-65,84-85,106,121 |
| 6 | Timestamp Precision | DateTime stored as `DATETIME(3)` (millisecond precision, no time zone) | migration.sql:8-9 et al. |
| 7 | Enum | `UserRole` = ADMIN, OPERATOR; default OPERATOR | prisma/schema.prisma:11-14,30 |
| 8 | Enum | `OrderStatus` = PENDING, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED; default PENDING | prisma/schema.prisma:16-23,78 |
| 9 | Uniqueness | `users.email` unique | prisma/schema.prisma:27; migration.sql:11 |
| 10 | Uniqueness | `customers.email` unique | prisma/schema.prisma:43; migration.sql:26 |
| 11 | Uniqueness | `products.sku` unique | prisma/schema.prisma:58; migration.sql:43 |
| 12 | Uniqueness | `orders.orderNumber` unique, `VARCHAR(20)` | prisma/schema.prisma:76; migration.sql:63 |
| 13 | Monetary Representation | All money values are integer cents (`Int` / `INTEGER`) | prisma/schema.prisma:61,79-81,104-105 |
| 14 | Default Values | `Product.stockQuantity` default 0; `Product.active` default true; `Order.discountCents` default 0 | prisma/schema.prisma:62,63,80 |
| 15 | Field Lengths | Max lengths: email 255, name 150 (users/customers) / 200 (products), phone 32, document 20, sku 64, reason 500; TEXT for description/notes | prisma/schema.prisma |
| 16 | Unstructured Data | `Customer.address` is a `JSON NOT NULL` column with no DB-level shape | prisma/schema.prisma:46; migration.sql:22 |
| 17 | Referential Integrity | Order -> Customer: ON DELETE RESTRICT, ON UPDATE CASCADE | migration.sql:110 |
| 18 | Referential Integrity | Order -> User (createdBy): ON DELETE RESTRICT | migration.sql:113 |
| 19 | Cascade Delete | OrderItem -> Order: ON DELETE CASCADE | prisma/schema.prisma:108; migration.sql:116 |
| 20 | Referential Integrity | OrderItem -> Product: ON DELETE RESTRICT | migration.sql:119 |
| 21 | Cascade Delete | OrderStatusHistory -> Order: ON DELETE CASCADE | prisma/schema.prisma:125; migration.sql:122 |
| 22 | Referential Integrity | OrderStatusHistory -> User (changedBy): ON DELETE RESTRICT | migration.sql:125 |
| 23 | Indexing | Secondary indexes on customers.document, products.active, products.name, orders.(customerId, status, createdAt, createdById), order_items.(orderId, productId), order_status_history.(orderId, changedAt) | prisma/schema.prisma:52,69-70,92-95,111-112,128-129 |
| 24 | Charset / Collation | All tables use `utf8mb4` / `utf8mb4_unicode_ci` (case-insensitive and accent-insensitive comparisons) | migration.sql:13...107; docker-compose.yml:23-24 |
| 25 | Audit Trail | Every order status change persists an `OrderStatusHistory` row; the first row has `fromStatus = null` | order.service.ts:106-113,159-167; schema.prisma:119 |
| 26 | Price Snapshot | `OrderItem.unitPriceCents` copies `Product.priceCents` at order creation | order.service.ts:77-83 |
| 27 | Derived Totals | item.totalCents = unit * qty; order.subtotal = sum of item totals; total = subtotal - discount; discount <= subtotal | order.service.ts:82-92 |
| 28 | Order Numbering | Sequential `ORD-` + 6-digit zero-padded number from `order_number_sequence`, reserved inside the order transaction | order.service.ts:245-254; seed.ts:165-176 |
| 29 | Transaction - Atomic Order Creation | Customer/product validation, numbering, order + items + first history row are created atomically | order.service.ts:58-123 |
| 30 | Transaction - Atomic Status Change | Status validation, stock movement, status update and history are atomic | order.service.ts:131-178 |
| 31 | Stock Debit | Stock is debited only on PENDING -> PAID, after an all-items availability check | order.status.ts:24-31; order.service.ts:151-153,204-231 |
| 32 | Stock Replenish | Stock is replenished on PAID -> CANCELLED or PROCESSING -> CANCELLED | order.status.ts:33-37; order.service.ts:154-156,233-243 |
| 33 | Consistent Pagination | List + count run in one batch `$transaction` | customer.repository.ts:26-34; product.repository.ts:27-35; order.repository.ts:35-43 |
| 34 | Default Sort | Lists are ordered by `createdAt desc`; order history is ordered by `changedAt asc` | repositories; order.repository.ts:56 |
| 35 | Search Semantics | Customer search = OR contains on name/email/document; Product search = OR contains on name/sku plus optional `active` filter; Order filter = status, customerId, createdAt range (gte/lte) | customer.repository.ts:12-22; product.repository.ts:13-23; order.repository.ts:21-31 |
| 36 | Deletion Guard | Orders can be deleted only in PENDING or CANCELLED; the delete cascades items and history | order.service.ts:181-192 |
| 37 | Uniqueness Pre-check | Services check email/SKU uniqueness before writing; DB unique constraints are the final guard (P2002 -> 409) | customer.service.ts:30-33,45-50; product.service.ts:31-34,47-52; user.service.ts:22-25; error.middleware.ts:37-47 |
| 38 | Not-found Translation | Prisma `P2025` is translated to HTTP 404 | error.middleware.ts:48-53 |
| 39 | Client Configuration | PrismaClient logs warn+error in development, only error otherwise | database.ts:5-7 |
| 40 | Data Exposure | `passwordHash` is persisted but stripped by `UserService.toPublic` | user.service.ts:42-51 |
| 41 | Seed Data | Destructive reset, 2 users with known passwords, 10 customers, 20 products, 26 orders over all statuses, 5% discount on every 7th order | seed.ts:178-325 |
| 42 | Test Isolation | All tables are truncated before each test in FK-safe order, against the configured `DATABASE_URL` | tests/setup.ts:8-16 |
| 43 | Migration Management | MySQL provider lock; shadow DB URL from `SHADOW_DATABASE_URL`; `db:migrate`, `db:reset`, `db:seed` scripts | migration_lock.toml:3; schema.prisma:8; package.json:14-16,22-24 |

### Detailed breakdown of the business rules

---

### Business Rule: UUID primary key strategy (Rule 1)

**Overview**:
Every business entity (`User`, `Customer`, `Product`, `Order`, `OrderItem`, `OrderStatusHistory`) has an `id String @id @default(uuid()) @db.Char(36)` primary key.

**Detailed description**:
The `@default(uuid())` attribute is applied by the Prisma Client engine, not by MySQL. The migration confirms this: the `id` columns are declared `CHAR(36) NOT NULL` with no SQL default (migration.sql:3,17,33,51,73,88). So any row inserted outside Prisma (raw SQL, an external ETL, manual DBA fixes) must supply its own UUID or the insert fails. The 36-character textual form (with hyphens) is stored as-is in a `utf8mb4` column, so each key takes more bytes than a `BINARY(16)` representation. Every FK column (`customerId`, `createdById`, `orderId`, `productId`, `changedById`) repeats the `CHAR(36)` type.

UUIDs make identifiers non-enumerable at the API level, which the Zod parameter schemas rely on (`z.string().uuid()` in every `*IdParamSchema`, e.g. order.schemas.ts:4). Validation therefore rejects malformed IDs before they reach the database. The UUIDs are random (v4), so new rows land at random positions in the InnoDB clustered primary key. On large tables this is a known source of page splits and fragmentation. The schema does not document the choice, so it is presumably a convention for API opacity and distributed generation. Confidence on the intent: medium.

Tests depend on this strategy. `tests/orders.test.ts:52` uses a syntactically valid but non-existent UUID (`11111111-1111-1111-1111-111111111111`) to exercise the "product not found" path. Factories never set IDs and rely fully on the client-side default.

**Rule workflow**:
```
Service/Repository calls prisma.<model>.create({ data }) without id
 -> Prisma engine generates a UUID v4 string
 -> INSERT ... (id = '<uuid>') into CHAR(36) column
 -> Row returned with id; API exposes id; Zod validates incoming ids as UUID
```

---

### Business Rule: Singleton order number sequence table (Rules 2 and 28)

**Overview**:
`OrderNumberSequence` (`order_number_sequence`) holds one row with `id = 1` and `nextValue`, which is the next order number to hand out. It is the source of the human-readable order number `ORD-NNNNNN`.

**Detailed description**:
The model has `id Int @id @default(1)` and `nextValue Int @default(1)` (schema.prisma:133-138). The table holds no other data and has no relation to `orders`. The reservation algorithm is identical in `OrderService.reserveOrderNumber` (order.service.ts:245-254) and in the seed (seed.ts:165-176). It runs `upsert where id=1`. If the row does not exist, it is created with `nextValue: 2` (so the reserved value is 1). If it exists, `nextValue` is incremented atomically with `{ increment: 1 }`, which becomes `UPDATE ... SET nextValue = nextValue + 1`. In both cases the reserved number is `nextValue - 1`, formatted as `ORD-` plus the number left-padded with zeros to 6 digits.

In `OrderService.create`, the reservation runs inside the same interactive transaction that creates the order (order.service.ts:93). If any later step fails, the increment rolls back with the order, so the sequence is **gap-free** for committed orders. The trade-off is that the InnoDB row lock on `order_number_sequence.id = 1` is held until the whole order transaction commits. All concurrent order creations are therefore serialized behind this single row. One edge case remains: when the table is empty and two transactions run the `upsert` concurrently, both may attempt the INSERT branch. One of them would fail with a duplicate-key error (P2002), which `error.middleware.ts` maps to HTTP 409. This only happens on a fresh or reset database (e.g. after `tests/setup.ts:12` deletes the sequence). Confidence: medium; it depends on how Prisma implements `upsert` for MySQL (it is not a native `INSERT ... ON DUPLICATE KEY UPDATE`).

The format has a few side effects. `orderNumber` is `VARCHAR(20)` (schema.prisma:76). With the `ORD-` prefix, padding to 6 digits gives `ORD-000001` up to `ORD-999999`. Beyond that, `padStart` does not truncate, so numbers keep growing (`ORD-1000000`), which still fits in 20 characters. Lexicographic sort on `orderNumber` stops matching numeric order after 999,999. The counter is a signed 32-bit `INT`, so its theoretical limit is 2,147,483,647. The unique index `orders_orderNumber_key` is the last guard against duplicates. Tests assert the format with `/^ORD-\d{6}$/` (orders.test.ts:39).

**Rule workflow**:
```
reserveOrderNumber(tx)
 -> tx.orderNumberSequence.upsert(where id=1, create {id:1,nextValue:2}, update {nextValue: increment 1})
 -> current = nextValue - 1
 -> return "ORD-" + pad6(current)
 -> used as orders.orderNumber in the same transaction
 -> commit: number consumed; rollback: increment undone
```

---

### Business Rule: Table and column naming conventions (Rules 3 and 4)

**Overview**:
Prisma model names are PascalCase singular. Physical table names are snake_case plural through `@@map`. Column names are **not** remapped and keep the camelCase Prisma field names.

**Detailed description**:
The mappings are `User -> users`, `Customer -> customers`, `Product -> products`, `Order -> orders`, `OrderItem -> order_items`, `OrderStatusHistory -> order_status_history` (singular "history"), and `OrderNumberSequence -> order_number_sequence` (singular). The schema has no `@map` on any field. The physical columns are therefore `passwordHash`, `createdAt`, `updatedAt`, `stockQuantity`, `priceCents`, `orderNumber`, `customerId`, `subtotalCents`, `discountCents`, `totalCents`, `createdById`, `unitPriceCents`, `fromStatus`, `toStatus`, `changedAt`, `changedById` and `nextValue` (migration.sql). The result is a hybrid convention: snake_case tables with camelCase columns. Anyone writing raw SQL, analytics queries or a future outbox/CDC integration needs to know this, because column names must be backtick-quoted and are case-sensitive in some contexts.

Constraint and index names are generated by Prisma from the physical table name and the field name. Examples are `users_email_key` (unique), `customers_document_idx` (index) and `orders_customerId_fkey` (foreign key). They show the same mix (`orders_createdById_idx`). Primary keys use MySQL's implicit `PRIMARY` name.

The relation names `"OrderCreatedBy"` and `"StatusChangedBy"` (schema.prisma:34-35,88,126) are required because `User` has two separate relations into the order aggregate. They exist only at the Prisma level and have no physical counterpart.

**Rule workflow**:
```
Prisma model (PascalCase) --@@map--> table (snake_case)
Prisma field (camelCase) --(no @map)--> column (camelCase)
Index/constraint name = <table>_<field>_<key|idx|fkey>
```

---

### Business Rule: Timestamp management (Rules 5 and 6)

**Overview**:
Mutable entities carry `createdAt` (DB default) and `updatedAt` (managed by the Prisma Client). Append-only entities carry only a creation timestamp.

**Detailed description**:
`User`, `Customer`, `Product` and `Order` declare `createdAt DateTime @default(now())` and `updatedAt DateTime @updatedAt`. In the migration, `createdAt` becomes `DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)`. `updatedAt` becomes `DATETIME(3) NOT NULL` with **no DB default and no `ON UPDATE` clause** (migration.sql:9,24,41,61). So `updatedAt` is filled only by the Prisma Client on create and update. Raw SQL inserts that omit `updatedAt` fail, and raw updates leave it stale.

`OrderItem` has only `createdAt` (schema.prisma:106), so order lines are treated as immutable after creation. Confirming this, no code path updates `order_items`. `OrderStatusHistory` uses `changedAt @default(now())` (schema.prisma:121) and has no update timestamp, matching its role as an append-only audit log. `OrderNumberSequence` has no timestamps.

`DATETIME(3)` stores millisecond precision with no time-zone offset. Prisma writes and reads `DateTime` values in UTC by convention, so the stored values are implicitly UTC. The `from`/`to` order filters (order.repository.ts:25-29) compare against `createdAt` using `z.coerce.date()` values (order.schemas.ts:28-29). A date-only string such as `2026-01-31` is interpreted as midnight UTC, so `to` excludes the rest of that day. History ordering relies on `changedAt asc` (order.repository.ts:56). Rows written in the same millisecond, such as the seed's back-to-back history inserts, have no secondary tiebreaker, so their relative order is not guaranteed. Confidence: medium.

**Rule workflow**:
```
create -> DB sets createdAt (CURRENT_TIMESTAMP(3)) unless Prisma sends it; Prisma sends updatedAt = now
update via Prisma -> Prisma sets updatedAt = now
update via raw SQL -> updatedAt unchanged
OrderItem / OrderStatusHistory -> insert-only timestamps
```

---

### Business Rule: UserRole enum (Rule 7)

**Overview**:
Users have exactly one of two roles, `ADMIN` or `OPERATOR`, with `OPERATOR` as the default.

**Detailed description**:
The enum becomes a native MySQL `ENUM('ADMIN','OPERATOR') NOT NULL DEFAULT 'OPERATOR'` (migration.sql:7). The database rejects any other value (under strict SQL mode, which is the MySQL 8 default). The role is persisted at user creation and embedded in the JWT (auth.service.ts:49). `requireRole('ADMIN')` checks it on `GET /api/v1/users/:id` (user.routes.ts:14-15).

In the persistence code the role is typed in places as the string literal union `'ADMIN' | 'OPERATOR'` instead of the generated `UserRole` type (user.repository.ts:14, user.service.ts:11, auth.middleware.ts:9). Adding a role to the Prisma enum would therefore need manual updates in several places. The seed uses the generated `UserRole` enum (seed.ts:199,208).

Adding a value to a native MySQL ENUM needs an `ALTER TABLE` migration. No such migration exists. `users.role` has no index.

**Rule workflow**:
```
register/createUser -> Zod enum default OPERATOR -> prisma.user.create(role) -> ENUM column
login -> role read from DB -> JWT claim -> requireRole() at route level
```

---

### Business Rule: OrderStatus enum and default (Rule 8)

**Overview**:
Orders have six possible statuses. New orders always start in `PENDING`.

**Detailed description**:
`OrderStatus` is a native MySQL ENUM reused in three columns: `orders.status` (NOT NULL DEFAULT 'PENDING'), `order_status_history.fromStatus` (NULL allowed) and `order_status_history.toStatus` (NOT NULL) (migration.sql:54,90,91). `OrderService.create` sets `status: OrderStatus.PENDING` explicitly even though the DB default covers it (order.service.ts:99).

The persistence layer stores the status but does not enforce which transitions are valid. Transition rules live in application code (`order.status.ts:3-10`): PENDING -> PAID|CANCELLED; PAID -> PROCESSING|CANCELLED; PROCESSING -> SHIPPED|CANCELLED; SHIPPED -> DELIVERED; DELIVERED and CANCELLED are terminal. The database would accept any direct `UPDATE orders SET status=...`. Because the generated enum is the single source of truth, Zod uses `z.nativeEnum(OrderStatus)` (order.schemas.ts:19,26) and the transitions map is typed `Record<OrderStatus, ...>`. Adding an enum value forces a compile-time update of the transitions table.

`orders.status` is indexed (`orders_status_idx`) to support the `?status=` list filter. The list query sorts by `createdAt desc` and there is no composite `(status, createdAt)` index, so MySQL either filters on status and then sorts, or scans the createdAt index and filters.

**Rule workflow**:
```
create -> status PENDING + history(null -> PENDING)
changeStatus -> app-level canTransition check -> UPDATE orders.status -> INSERT history(from -> to)
list ?status=X -> WHERE status = X (index orders_status_idx) ORDER BY createdAt DESC
```

---

### Business Rule: Unique user email (Rule 9)

**Overview**:
Two users cannot share an email address.

**Detailed description**:
`User.email` is `@unique @db.VarChar(255)` and becomes `UNIQUE INDEX users_email_key` (migration.sql:11). The collation is `utf8mb4_unicode_ci`, so uniqueness is case-insensitive at the DB level: `Admin@x.com` and `admin@x.com` collide. The application does not normalize case before storage. `UserService.createUser` pre-checks with `findByEmail` (user.service.ts:22-25), and that lookup is also case-insensitive under the collation. Confidence: high, based on MySQL collation semantics.

There is a race between the pre-check and the insert: two concurrent registrations with the same email can both pass the check. The unique index then rejects the second insert with Prisma `P2002`. The error middleware turns it into HTTP 409 with code `CONFLICT` and the message `Unique constraint violation on: users_email_key` or similar. The pre-check path returns code `EMAIL_ALREADY_USED` instead (tested in auth.test.ts:19-28), so clients see two different error codes for the same business condition depending on timing.

Login (`AuthService.login`) uses the same unique lookup (`findUnique where email`) (auth.service.ts:32).

**Rule workflow**:
```
createUser -> findByEmail -> exists ? 409 EMAIL_ALREADY_USED
 -> create -> unique index -> P2002 ? 409 CONFLICT : user row
```

---

### Business Rule: Unique customer email (Rule 10)

**Overview**:
Customer emails are unique across the `customers` table.

**Detailed description**:
`Customer.email` is unique (`customers_email_key`, migration.sql:26). `CustomerService.create` pre-checks with `findByEmail`. `CustomerService.update` checks only when `input.email` is provided, and it allows the same customer to keep its own email (`sameEmail.id !== id`) (customer.service.ts:30-33,45-50). Both checks raise `ConflictError('EMAIL_ALREADY_USED')`.

Customer and user emails live in separate tables, so the same address can belong to both a user and a customer. The collation makes uniqueness case-insensitive, as with users. Concurrency behaves as described in Rule 9: the DB index is the final guard and the error code differs (`CONFLICT`).

`customers.document` (CPF/CNPJ) is **not** unique. It only has a non-unique index (`customers_document_idx`, schema.prisma:52). Two customers can therefore share a document number. The seed uses distinct values, and the test factory uses the same default document `000.000.000-00` for every customer (factories.ts:50), which works only because the column is not unique.

**Rule workflow**:
```
create/update(email) -> findByEmail -> conflict (other id) ? 409
 -> write -> unique index -> P2002 ? 409 CONFLICT
```

---

### Business Rule: Unique product SKU (Rule 11)

**Overview**:
Every product has a unique SKU of up to 64 characters.

**Detailed description**:
`Product.sku` is `@unique @db.VarChar(64)` (`products_sku_key`). `ProductService.create` and `ProductService.update` pre-check with `findBySku` and raise `ConflictError('SKU already in use', 'SKU_ALREADY_USED')` (product.service.ts:31-34,47-52). On update, the product may keep its own SKU.

Uniqueness is case-insensitive under `utf8mb4_unicode_ci`, so `nb-dell-001` and `NB-DELL-001` collide. SKUs are not normalized before storage. The SKU appears in domain errors, for example `INACTIVE_PRODUCT` details list SKUs (order.service.ts:71) and `InsufficientStockError` reports `sku` (order.service.ts:216). In product search it is matched with `contains` (product.repository.ts:19). A leading-wildcard `LIKE '%term%'` cannot use the unique index.

**Rule workflow**:
```
create/update(sku) -> findBySku -> conflict ? 409 SKU_ALREADY_USED -> write -> P2002 fallback 409 CONFLICT
```

---

### Business Rule: Unique order number (Rule 12)

**Overview**:
`orders.orderNumber` is unique and is filled only from the sequence (see Rule 28).

**Detailed description**:
The unique index `orders_orderNumber_key` (migration.sql:63) guarantees that two orders never share a number, even if the sequence were reset or manipulated. Tests reset the sequence before each test by deleting the row (tests/setup.ts:12) and also delete all orders, so the numbering restarts at `ORD-000001` without collision.

The seed also deletes the sequence and all orders (seed.ts:183,187). If an operator deleted only the sequence row on a populated database, the next order would reserve `ORD-000001` again. The unique index would raise P2002 (HTTP 409), and the increment would roll back with the failed transaction. Every later order creation would then fail the same way until the sequence was manually corrected. Confidence: high, from code reading.

No API looks orders up by `orderNumber`. The index serves only uniqueness.

**Rule workflow**:
```
reserveOrderNumber -> INSERT orders(orderNumber) -> unique index check -> commit or P2002 -> rollback
```

---

### Business Rule: Monetary values in integer cents (Rule 13)

**Overview**:
All currency amounts are persisted as integer counts of the smallest currency unit (cents).

**Detailed description**:
The money fields are `Product.priceCents`, `Order.subtotalCents`, `Order.discountCents`, `Order.totalCents`, `OrderItem.unitPriceCents` and `OrderItem.totalCents`. All are Prisma `Int`, which maps to MySQL signed `INTEGER` (32-bit, range -2,147,483,648 to 2,147,483,647). Integer cents avoid floating-point rounding errors, and all arithmetic in `OrderService` is integer multiplication and addition. The one non-integer step is the seed's 5% discount, which uses `Math.floor(subtotalCents * 0.05)` (seed.ts:282) to stay integral.

The upper bound of a signed INT in cents is about 21,474,836.47 currency units. JavaScript computes `unitPriceCents * quantity` and `reduce` sums with doubles, so overflow happens only when the value is written. MySQL strict mode would then reject the out-of-range value with a Prisma error that `error.middleware.ts` does not map, giving HTTP 500. Zod enforces only `int().nonnegative()` for `priceCents` and `positive()` for `quantity`, with no upper bound (product.schemas.ts:9; order.schemas.ts:8). A large order (e.g. quantity 100,000 of a 459,900-cent notebook) can therefore exceed the column range.

The currency is not stored anywhere. The seed data (BRL addresses, CPF/CNPJ) implies Brazilian Real. Confidence: medium.

There are no DB CHECK constraints, so negative values are prevented only by Zod (`nonnegative`) and service logic (`discount <= subtotal`).

**Rule workflow**:
```
Input (Zod int, nonnegative) -> service integer arithmetic -> INT columns
Display/formatting -> not part of the persistence layer (amounts are returned raw in cents)
```

---

### Business Rule: Default values (Rule 14)

**Overview**:
The schema declares defaults: `stockQuantity = 0`, `active = true`, `discountCents = 0`, `role = OPERATOR`, `status = PENDING`, `nextValue = 1`, `OrderNumberSequence.id = 1`.

**Detailed description**:
These defaults exist both in the Prisma schema and as SQL `DEFAULT` clauses in the migration (migration.sql:38-39,56,7,54,103-104), so they apply to both Prisma inserts and raw SQL inserts. The application often repeats the defaults at the validation layer (product.schemas.ts:10-11 `stockQuantity.default(0)`, `active.default(true)`; order.schemas.ts:14 `discountCents.default(0)`; auth/user schemas `role.default('OPERATOR')`). As a result the DB defaults are rarely relied on during API flows.

`Product.active` is a soft-availability flag, not a soft delete. Inactive products cannot be added to new orders (order.service.ts:66-73), but they stay listable and deletable. The `products_active_idx` index supports the `?active=true|false` filter (product.repository.ts:15). The column has low cardinality (two values), so the index is selective only when the distribution is skewed.

Nothing in the persistence layer prevents `stockQuantity` from going negative. The column is a signed INT without a CHECK. Non-negativity is guaranteed only by the application-level availability check before a debit (order.service.ts:212-224) and by Zod on product create/update.

**Rule workflow**:
```
INSERT without column -> SQL DEFAULT applied
API path -> Zod default fills the value before Prisma
```

---

### Business Rule: Field length and type constraints (Rule 15)

**Overview**:
String columns have explicit VARCHAR lengths that set hard limits at the DB level. Long free text uses TEXT.

**Detailed description**:
Physical limits are: `users.email` 255, `users.passwordHash` 255, `users.name` 150, `customers.name` 150, `customers.email` 255, `customers.phone` 32, `customers.document` 20, `products.sku` 64, `products.name` 200, `products.description` TEXT (nullable), `orders.orderNumber` 20, `orders.notes` TEXT (nullable), `order_status_history.reason` 500 (nullable).

The Zod schemas match these limits: emails `max(255)`; names `max(150)` for users and customers and `max(200)` for products; phone `min(8).max(32)`; document `min(11).max(20)`; sku `min(2).max(64)`; reason `max(500)`. A few are stricter than the DB: product description `max(2000)` against TEXT (64 KB), and order notes `max(1000)` against TEXT. Validation therefore almost always fails before the DB truncation/error path is reached.

`passwordHash` stores a bcrypt hash (60 characters), well under its 255 limit. Password input is capped at 72 characters (auth.schemas.ts:5), which matches bcrypt's effective input limit.

Nullable columns: `products.description`, `orders.notes`, `order_status_history.fromStatus`, `order_status_history.reason`. Everything else is `NOT NULL`. Services explicitly convert `undefined` to `null` for optional text (product.service.ts:38; order.service.ts:103,165).

**Rule workflow**:
```
HTTP body -> Zod length checks -> Prisma -> VARCHAR(n)/TEXT
```

---

### Business Rule: Customer address stored as JSON (Rule 16)

**Overview**:
A customer's postal address is one `JSON NOT NULL` column with no structural constraint in the database.

**Detailed description**:
`Customer.address` is typed `Json` in Prisma and `JSON` in MySQL (schema.prisma:46; migration.sql:22). MySQL validates only that the value is well-formed JSON. The expected shape (`street`, `number`, `city`, `state` with length 2, `zipCode`) is enforced only by the Zod `addressSchema` (customer.schemas.ts:7-13). Rows written by the seed (seed.ts:15-21 etc.), the test factory (factories.ts:51-57) or raw SQL bypass that validation. The seed and factory happen to follow the same shape.

On update, `updateCustomerSchema` is `createCustomerSchema.partial()`. That makes the top-level `address` field optional, but the nested address object itself is not partial. When provided, it **replaces the whole JSON document** (customer.service.ts:56); there is no merge. The `Customer` type returned by Prisma exposes `address` as `Prisma.JsonValue`, so consumers get no compile-time typing for the address fields.

No index exists on any JSON path, and customer search (`contains` on name/email/document) does not look inside the address.

**Rule workflow**:
```
POST/PATCH customer -> Zod addressSchema -> prisma.customer.create/update({ address: object }) -> JSON column
read -> JsonValue (untyped) -> returned as-is
```

---

### Business Rule: Order references Customer with RESTRICT (Rule 17)

**Overview**:
A customer cannot be deleted while any order references it.

**Detailed description**:
`orders_customerId_fkey` is `ON DELETE RESTRICT ON UPDATE CASCADE` (migration.sql:110). Prisma's default for a required relation without an explicit `onDelete` is `Restrict` (schema.prisma:87). `CustomerService.delete` checks only that the customer exists (customer.service.ts:60-63) and then calls `prisma.customer.delete`. If the customer has orders, MySQL raises a foreign key failure, which Prisma surfaces as `PrismaClientKnownRequestError` with code `P2003`. **`error.middleware.ts` handles only `P2002` and `P2025`**, so this case falls through to the generic handler: it is logged as `Unhandled error in request` and returns **HTTP 500 INTERNAL_SERVER_ERROR**. The business intent of keeping order history from being orphaned is enforced, but the client gets a server error instead of a domain error (e.g. 409). No test covers this path.

`ON UPDATE CASCADE` would propagate a change of `customers.id` to `orders.customerId`. The API never updates primary keys, so this has no practical effect. `orders.customerId` is indexed (`orders_customerId_idx`), which supports both the FK check and the `?customerId=` list filter.

**Rule workflow**:
```
DELETE /customers/:id -> getById (exists) -> prisma.customer.delete
 -> no orders: row deleted (204)
 -> has orders: MySQL FK error -> P2003 -> unmapped -> HTTP 500
```

---

### Business Rule: Order references creating User with RESTRICT (Rule 18)

**Overview**:
Every order records the user who created it (`createdById`). That user cannot be deleted while such orders exist.

**Detailed description**:
`orders_createdById_fkey` is `ON DELETE RESTRICT` (migration.sql:113). The relation is named `"OrderCreatedBy"` (schema.prisma:34,88). The value comes from the authenticated JWT subject (`userId` parameter in `OrderService.create`, order.service.ts:104). The persistence layer does not check that the user still exists before insert. If a token outlives a deleted user, the FK would fail with P2003, which is not mapped and gives HTTP 500. The API exposes no user deletion endpoint, so in practice this is reachable only through direct DB manipulation or test cleanup. `orders.createdById` is indexed.

**Rule workflow**:
```
POST /orders (JWT sub) -> tx.order.create({ createdById: sub }) -> FK check users.id
```

---

### Business Rule: OrderItem cascades with Order (Rule 19)

**Overview**:
Order lines belong to their order and are deleted automatically with it.

**Detailed description**:
`OrderItem.order` is declared with `onDelete: Cascade` (schema.prisma:108), which becomes `order_items_orderId_fkey ... ON DELETE CASCADE` (migration.sql:116). Together with the cascade on history (Rule 21), this makes `Order` the aggregate root. Deleting an order (`OrderRepository.deleteById`, order.repository.ts:66-68) removes all its lines in the same statement, enforced by InnoDB.

Order items are created only as a nested write inside `tx.order.create({ items: { create: [...] } })` (order.service.ts:105). No repository or service creates, updates or deletes `OrderItem` rows on their own. Items are aggregated per product before insert (order.service.ts:194-202), so each order has at most one line per product. **The database does not enforce this**: there is no unique `(orderId, productId)` constraint.

Deleting an order does **not** restore stock. That is consistent because deletion is allowed only for PENDING (stock never debited) or CANCELLED (stock already replenished when coming from PAID/PROCESSING) orders. See Rule 36.

**Rule workflow**:
```
DELETE orders WHERE id = ? -> InnoDB cascades DELETE order_items WHERE orderId = ?
```

---

### Business Rule: OrderItem references Product with RESTRICT (Rule 20)

**Overview**:
A product that appears on any order line cannot be deleted.

**Detailed description**:
`order_items_productId_fkey` is `ON DELETE RESTRICT` (migration.sql:119). `ProductService.delete` checks only existence (product.service.ts:63-66). Deleting a product that has been ordered, even once, in an order that is now cancelled, raises P2003, which is unmapped and gives **HTTP 500**. The intended way to retire a product is to set `active = false`. That flag blocks new orders but keeps history intact. This intent is inferred from the code (medium confidence); it is not documented in the code.

`order_items.productId` is indexed. The index serves the FK and would support "orders containing product X" queries, which no current endpoint provides.

**Rule workflow**:
```
DELETE /products/:id -> exists -> prisma.product.delete
 -> not referenced: deleted
 -> referenced: P2003 -> HTTP 500
```

---

### Business Rule: OrderStatusHistory cascades with Order (Rule 21)

**Overview**:
The audit trail of an order is physically deleted when the order is deleted.

**Detailed description**:
`OrderStatusHistory.order` has `onDelete: Cascade` (schema.prisma:125; migration.sql:122). The history is an audit log, but it does not outlive its order. When a PENDING or CANCELLED order is deleted through `DELETE /api/v1/orders/:id`, all evidence of who created it, who cancelled it and why disappears. No soft-delete, archive table or outbox event preserves that information. This is a design decision with audit implications: the audit trail is scoped to the life of the order, not retained permanently.

History rows are created in two places. One is the nested write at order creation (order.service.ts:106-113, `reason: 'order created'`, `fromStatus: null`). The other is an explicit `tx.orderStatusHistory.create` on each status change (order.service.ts:159-167). The rows are never updated. Indexes on `orderId` and `changedAt` support retrieving one order's history in ascending time order (order.repository.ts:56; order.service.ts:117,173).

**Rule workflow**:
```
DELETE orders -> cascade DELETE order_status_history WHERE orderId = ?
```

---

### Business Rule: OrderStatusHistory references changing User with RESTRICT (Rule 22)

**Overview**:
Each history row records who made the change (`changedById`). That user cannot be deleted while such rows exist.

**Detailed description**:
`order_status_history_changedById_fkey` is `ON DELETE RESTRICT` (migration.sql:125), through the relation `"StatusChangedBy"`. Together with Rule 18, this means a user who has ever created an order or changed a status can never be deleted while those records exist. The cascade paths make one sequence possible: deleting the user's orders first (allowed only in PENDING/CANCELLED) frees the user, unless the user also has history rows on other users' orders. `changedById` is **not indexed** (only `orderId` and `changedAt` are), so a query like "all changes by user X" would need a full scan. InnoDB requires an index on FK columns and creates one implicitly if none exists. The migration does not declare it, so MySQL generates an internal index named after the constraint. Confidence: high, based on documented InnoDB behavior.

**Rule workflow**:
```
INSERT history(changedById = JWT sub) -> FK check users.id
DELETE users -> blocked if referenced
```

---

### Business Rule: Index strategy (Rule 23)

**Overview**:
Secondary indexes match the list filters and FK lookups that the repositories use.

**Detailed description**:
The declared indexes (excluding PKs and unique keys) are:

| Table | Index | Supports |
|-------|-------|----------|
| customers | `customers_document_idx(document)` | Exact document lookups (none implemented); `contains` search cannot use it |
| products | `products_active_idx(active)` | `?active=` filter |
| products | `products_name_idx(name)` | Name lookup; `contains` (leading `%`) cannot use it |
| orders | `orders_customerId_idx` | FK + `?customerId=` |
| orders | `orders_status_idx` | `?status=` |
| orders | `orders_createdAt_idx` | `ORDER BY createdAt DESC` + `from/to` range |
| orders | `orders_createdById_idx` | FK |
| order_items | `order_items_orderId_idx`, `order_items_productId_idx` | FK + include `items` |
| order_status_history | `order_status_history_orderId_idx`, `order_status_history_changedAt_idx` | include `history` ordered by changedAt |

`customers` and `products` list queries sort by `createdAt desc` (customer.repository.ts:29; product.repository.ts:30), but **neither table has a `createdAt` index**, so every paged list sorts the whole filtered set (filesort). Search uses Prisma `contains`, which becomes `LIKE '%term%'` and cannot use B-tree indexes. Searches therefore scan the full table. There are no composite indexes (e.g. `(status, createdAt)` or `(customerId, createdAt)`) that would let a filtered, sorted order list be served from an index alone.

**Rule workflow**:
```
Repository where/orderBy -> MySQL optimizer -> index (equality filters, createdAt range) or full scan + filesort (contains, createdAt on customers/products)
```

---

### Business Rule: Character set and collation semantics (Rule 24)

**Overview**:
All text is stored in `utf8mb4` with `utf8mb4_unicode_ci`, which makes comparisons, uniqueness and search case-insensitive and largely accent-insensitive.

**Detailed description**:
Every `CREATE TABLE` ends with `DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` (migration.sql:13,29,47,69,84,99,107). The MySQL server is started with the same defaults (docker-compose.yml:23-24). This gives full Unicode support, including the Portuguese accents used throughout the seed data (`São Paulo`, `Acácias`, `Memória`).

The business consequences:
1. Unique constraints on `email` and `sku` are case-insensitive (Rules 9-11).
2. Prisma `contains` filters on MySQL do not support `mode: 'insensitive'`, but they are case-insensitive anyway because of the collation. A search for `sao paulo` would match `São Paulo` under `unicode_ci` accent folding. Confidence: medium; it depends on the exact collation weights.
3. Ordering by name or text columns follows Unicode collation rules.

This behavior comes from the database configuration, not from application code. Changing the collation would silently change search and uniqueness semantics.

**Rule workflow**:
```
Text comparison (=, LIKE, UNIQUE) -> utf8mb4_unicode_ci weights -> case/accent-insensitive match
```

---

### Business Rule: Order status audit trail (Rule 25)

**Overview**:
Every committed status of an order has a matching `OrderStatusHistory` row, written in the same transaction as the status change.

**Detailed description**:
At creation, the nested write inserts `{ fromStatus: null, toStatus: PENDING, changedById: userId, reason: 'order created' }` (order.service.ts:106-113). The nullable `fromStatus` column (schema.prisma:119) exists to represent this initial state. On each status change, `tx.order.update` and `tx.orderStatusHistory.create` run in the same interactive transaction (order.service.ts:158-167). `orders.status` and the latest history entry therefore cannot diverge through the API. The optional `reason` comes from the client (`max(500)`), and `null` is stored when it is absent.

The invariant "the last history row's `toStatus` equals `orders.status`" is **not enforced by the database**. It holds only for writes through `OrderService`. Raw SQL updates or seed logic could break it. The seed rebuilds history with the full path (Rule 41), so seeded data does satisfy it. Tests verify the trail after PENDING -> PAID (orders.test.ts:80-83) and the single initial entry at creation (orders.test.ts:37-38).

**Rule workflow**:
```
create -> order(PENDING) + history(null -> PENDING) [same tx]
changeStatus -> update order.status + insert history(from -> to, reason) [same tx]
read -> include history orderBy changedAt asc
```

---

### Business Rule: Price snapshot on order items (Rule 26)

**Overview**:
The unit price used for an order line is copied from the product at creation time and never recalculated.

**Detailed description**:
In `OrderService.create`, `unitPriceCents = product.priceCents` is read inside the transaction (order.service.ts:77) and stored in `order_items.unitPriceCents`, with `totalCents = unitPriceCents * quantity`. Later edits to `products.priceCents` through `PATCH /products/:id` leave existing orders unchanged, which preserves the commercial terms at order time. The client cannot supply a price: `orderItemInputSchema` accepts only `productId` and `quantity` (order.schemas.ts:6-9). The test "computes totals on the server" covers this (orders.test.ts:12-40).

The product read inside the transaction is a non-locking consistent read. A concurrent price update that commits during the transaction is not visible, and the order uses the price as of the transaction's snapshot. This is acceptable for a snapshot semantic.

**Rule workflow**:
```
tx.product.findMany -> unitPriceCents := product.priceCents -> order_items row (immutable)
```

---

### Business Rule: Derived totals and discount constraint (Rule 27)

**Overview**:
Order totals are computed by the server and persisted denormalized: item totals, subtotal, discount and final total.

**Detailed description**:
`subtotalCents = sum(item.totalCents)` (order.service.ts:86). `discountCents` comes from the input (Zod `int().nonnegative().default(0)`) and must not exceed `subtotalCents`, otherwise `ValidationError('Discount cannot exceed subtotal')` is raised (order.service.ts:87-91). `totalCents = subtotalCents - discountCents` (order.service.ts:92). All three values are stored in `orders`, together with each line's `totalCents` in `order_items`.

The database has no constraint tying these columns together (no CHECK, no generated columns). Consistency depends on writes going through `OrderService.create`. Once created, the values never change: there is no order-update endpoint other than status. The seed computes totals with the same formula plus an automatic 5% discount on every 7th order (seed.ts:281-283).

Because the totals are denormalized, list endpoints can return amounts without joining `order_items`. `OrderRepository.list` returns plain `Order` rows without includes (order.repository.ts:36-41).

**Rule workflow**:
```
items -> line totals -> subtotal -> validate discount <= subtotal -> total -> persisted on orders + order_items
```

---

### Business Rule: Atomic order creation via interactive transaction (Rule 29)

**Overview**:
Order creation is all-or-nothing: either the order, its items, its first history row and the sequence increment are all committed, or none of them are.

**Detailed description**:
`OrderService.create` wraps all reads and writes in `this.prisma.$transaction(async (tx) => {...})` (order.service.ts:58-123). Every query inside uses `tx`, a `Prisma.TransactionClient` aliased as `TxClient` (order.service.ts:24). Any thrown `AppError` (NotFound, UnprocessableEntity, Validation) or DB error makes Prisma roll back. The empty-items check and the item aggregation run before the transaction opens (order.service.ts:51-56).

The transaction uses Prisma's interactive-transaction defaults because no options are passed: `maxWait` 2 s to acquire a connection, `timeout` 5 s for the whole callback, and the database's default isolation level (InnoDB `REPEATABLE READ`). These are Prisma 5 defaults and are not configured anywhere in this code base. The order-number row lock is held for the full duration (Rule 28), so a long creation transaction delays all other order creations. Order creation does not touch stock, so customer and product reads need no locking. Product active status and existence are checked as of the snapshot.

`OrderRepository` is **not used** in this flow. The service calls `tx.customer`, `tx.product`, `tx.orderNumberSequence` and `tx.order` directly, because the repositories cannot accept a transaction client.

**Rule workflow**:
```
$transaction(callback)
 BEGIN
  SELECT customer
  SELECT products IN (...)
  validations (throw -> ROLLBACK)
  UPSERT order_number_sequence (row lock)
  INSERT orders; INSERT order_items (n); INSERT order_status_history
  SELECT order with includes
 COMMIT
```

---

### Business Rule: Atomic status change with stock movement (Rule 30)

**Overview**:
A status change, its stock side effects and its audit record are committed together.

**Detailed description**:
`OrderService.changeStatus` (order.service.ts:126-179) opens an interactive transaction. It:
1. Reads the order with its items.
2. Rejects same-status changes (`ConflictError INVALID_STATUS_TRANSITION`) and disallowed transitions (`InvalidStatusTransitionError`).
3. Debits or replenishes stock if needed.
4. Updates `orders.status`.
5. Inserts the history row.
6. Re-reads the order with the full include for the response.

If the stock check fails, `InsufficientStockError` (HTTP 422) is thrown before any update, and the transaction rolls back with no partial changes. The test at orders.test.ts:109-132 asserts that stock is unchanged after this failure.

**Concurrency caveat (inferred from code; not covered by tests):** The initial `tx.order.findUnique` is a plain, non-locking read, and the later `tx.order.update({ where: { id } })` has no condition on the current status (no optimistic concurrency check such as `where: { id, status: from }` and no version column). Two concurrent requests to move the same PENDING order to PAID can both read `PENDING`, both pass `canTransition`, and both debit stock. The second `UPDATE` waits for the first transaction's row lock and then succeeds. The result is double stock debit and two `PENDING -> PAID` history rows. Under REPEATABLE READ, InnoDB `UPDATE` statements see the latest committed version, but the decision was made from the stale snapshot read. Confidence: high, based on MySQL InnoDB semantics.

The re-read at the end uses a non-null assertion (`refreshed!`, order.service.ts:177). The order was just updated in the same transaction, so this is safe within the transaction.

**Rule workflow**:
```
BEGIN
 SELECT order + items                         (snapshot, no lock)
 validate transition
 [PENDING->PAID]   SELECT products; check all; UPDATE products SET stock = stock - q (per item)
 [PAID|PROCESSING->CANCELLED] UPDATE products SET stock = stock + q (per item)
 UPDATE orders SET status = to                (row lock)
 INSERT order_status_history
 SELECT order + includes
COMMIT
```

---

### Business Rule: Stock debit on payment (Rule 31)

**Overview**:
Inventory is reserved, by decrementing `products.stockQuantity`, only when an order moves from PENDING to PAID. It is never decremented at order creation.

**Detailed description**:
`shouldDebitStock` returns true only for `from === PENDING && to === PAID` (order.status.ts:24-31). `debitStock` (order.service.ts:204-231) loads all products referenced by the order items in one query. It builds a list of every unavailable item (missing product, or `stockQuantity < quantity`) so that all shortfalls are reported together, with `sku`, `requested` and `available`. If any are found it throws `InsufficientStockError` (422). Otherwise it runs one `UPDATE ... SET stockQuantity = stockQuantity - q` per item, sequentially. The decrement is atomic at the SQL level.

Because the availability check uses a non-locking snapshot read and the decrement is a separate statement, **two different orders containing the same product can be paid concurrently** and both pass the check against the same snapshot stock. Both decrements then apply, which can make `stockQuantity` negative. Nothing at the DB level (no CHECK constraint, no conditional `WHERE stockQuantity >= q` update, no `SELECT ... FOR UPDATE`) prevents this. Confidence: high. A PENDING order also holds no reservation, so it can be created for more than the available stock and fail only at payment (tested in orders.test.ts:109-132).

The direct path `PENDING -> CANCELLED` debits nothing and replenishes nothing, which is consistent.

**Rule workflow**:
```
PENDING -> PAID
 -> SELECT products WHERE id IN (...)
 -> any stock < qty ? throw 422 INSUFFICIENT_STOCK (rollback)
 -> for each item: UPDATE products SET stockQuantity = stockQuantity - qty
```

---

### Business Rule: Stock replenishment on cancellation (Rule 32)

**Overview**:
Cancelling an order that had already debited stock (PAID or PROCESSING) returns the quantities to inventory.

**Detailed description**:
`shouldReplenishStock` returns true when `to === CANCELLED` and `from` is `PAID` or `PROCESSING` (order.status.ts:33-37). `replenishStock` runs one atomic increment per item, with no reads (order.service.ts:233-243). If a product had been deleted, the update would fail with `P2025`, mapped to 404 and rolling back the cancellation. In practice the RESTRICT FK on `order_items.productId` makes product deletion impossible while order items reference it, so this path should not occur.

The transition table also allows `PROCESSING -> CANCELLED` but not `SHIPPED -> CANCELLED` (order.status.ts:6-7). Shipped goods are never returned to stock through the API. The replenish operation does not check whether the debit actually happened. It assumes every PAID/PROCESSING order was debited, which holds for orders that went through the API. **Seeded orders in PAID/PROCESSING status were never debited** (Rule 41), so cancelling them through the API inflates stock. Tested by orders.test.ts:134-161 (PAID -> CANCELLED restores the original quantity).

**Rule workflow**:
```
PAID|PROCESSING -> CANCELLED
 -> for each item: UPDATE products SET stockQuantity = stockQuantity + qty
```

---

### Business Rule: Consistent paginated lists via batch transaction (Rule 33)

**Overview**:
Each paged list fetches the page and the total count inside one batch transaction, so both reflect the same database state.

**Detailed description**:
`CustomerRepository.list`, `ProductRepository.list` and `OrderRepository.list` call `this.prisma.$transaction([findMany(...), count(...)])` with the same `where` object (customer.repository.ts:26-34; product.repository.ts:27-35; order.repository.ts:35-43). Prisma runs the array form sequentially inside one DB transaction. Under InnoDB REPEATABLE READ, both statements read from the same snapshot, so `pagination.total` matches the dataset the page came from.

`skip`/`take` give offset pagination. The pageSize ceiling of 100 is enforced by Zod (`max(100)`, e.g. order.schemas.ts:25). Deep pages cost O(offset) because MySQL must scan and discard skipped rows. Combined with the missing `createdAt` indexes on customers/products and the full-table `LIKE '%..%'` searches, large-offset searches are the main performance hotspot of the read path. `createdAt` is not unique and there is no secondary sort key such as `id`, so rows with identical timestamps (likely with the seed's `Promise.all` inserts) can appear on two pages or on none as pages shift.

**Rule workflow**:
```
list(filters)
 -> where = buildWhere(filters)
 -> $transaction([ findMany(where, orderBy createdAt desc, skip, take), count(where) ])
 -> { items, total } -> paginated()
```

---

### Business Rule: Default sorting (Rule 34)

**Overview**:
Lists return the newest records first. Order history is returned oldest first.

**Detailed description**:
All three list methods use `orderBy: { createdAt: 'desc' }`. `findByIdWithRelations` and the transactional includes in `OrderService` order `history` by `changedAt: 'asc'` (order.repository.ts:56; order.service.ts:117,173), which gives a chronological audit trail. `items` inside an order have no `orderBy`, so their order is whatever the database returns, typically PK order. The PKs are random UUIDs, so this does not match insertion order. Confidence: medium.

**Rule workflow**:
```
lists -> createdAt DESC
order detail -> history changedAt ASC; items unspecified
```

---

### Business Rule: Search and filter semantics (Rule 35)

**Overview**:
Each repository turns validated filters into a Prisma `WhereInput` with fixed semantics.

**Detailed description**:
- **Customers** (customer.repository.ts:12-22): when `search` is given (trimmed, at least 1 character), the filter is `OR` of `name contains`, `email contains`, `document contains`. Without search, there is no filter.
- **Products** (product.repository.ts:13-23): `active` (boolean parsed from the strings `'true'`/`'false'`) is an equality filter. `search` is `OR` of `name contains` and `sku contains`. Both combine with AND. `description` is not searched.
- **Orders** (order.repository.ts:21-31): `status` equality, `customerId` equality, and `createdAt` range with an inclusive `gte from` and inclusive `lte to`. There is no free-text search on orders, and no filter by `orderNumber` or `createdById`.

Prisma passes `contains` values as bind parameters, so no SQL injection is possible. `%` and `_` in user input are not escaped by Prisma for `contains` on MySQL. A search for `_` therefore matches any single character. Confidence: medium, based on Prisma 5 behavior. No validation stops `from` from being later than `to`; such a query simply returns an empty result.

**Rule workflow**:
```
query params -> Zod coercion -> service maps to filters -> buildWhere -> Prisma where -> SQL WHERE (parameterized)
```

---

### Business Rule: Order deletion guard (Rule 36)

**Overview**:
Only orders in PENDING or CANCELLED status can be deleted. Deletion is a hard delete that cascades.

**Detailed description**:
`OrderService.delete` (order.service.ts:181-192) reads the order through `OrderRepository.findById`. It throws `NotFoundError` when absent and `ConflictError('INVALID_ORDER_STATE_FOR_DELETE')` when the status is not PENDING or CANCELLED. Otherwise it calls `OrderRepository.deleteById`. The check and the delete are **not in a transaction**. A concurrent status change (e.g. PENDING -> PAID with stock debit) that commits between the two calls would lead to deleting a PAID order whose stock was debited and never returned. That stock would be lost. Confidence: high, based on code reading. The window is small.

These two statuses are allowed because, for API-created orders, neither has net stock impact: PENDING never debited, and CANCELLED from PAID/PROCESSING already replenished. Deletion physically removes items and history through the cascade (Rules 19 and 21). Covered by orders.test.ts:197-218 (PAID order cannot be deleted). The successful deletion path is not tested.

**Rule workflow**:
```
findById -> missing ? 404
 -> status not in {PENDING, CANCELLED} ? 409 INVALID_ORDER_STATE_FOR_DELETE
 -> DELETE orders (cascade items + history) -> 204
```

---

### Business Rule: Uniqueness pre-checks backed by DB constraints (Rule 37)

**Overview**:
Services check uniqueness in the application first to return a domain-specific error. The DB unique indexes remain the authoritative guard.

**Detailed description**:
There are three pairs of pre-check and constraint: user email, customer email and product SKU (see Rules 9-11). The pre-checks are not transactional and therefore race-prone. The DB constraint violation (P2002) is caught globally and returned as 409 `CONFLICT` with a message naming the constraint target (error.middleware.ts:37-47), so the response contract differs between the two paths. The message includes `err.meta.target`, which on MySQL is the index name (e.g. `customers_email_key`) and so exposes schema details to the client. Confidence: medium; the exact `meta.target` format depends on the Prisma connector.

**Rule workflow**:
```
pre-check (findUnique) -> domain 409 (EMAIL_ALREADY_USED / SKU_ALREADY_USED)
 -> write -> P2002 -> generic 409 CONFLICT
```

---

### Business Rule: Prisma not-found translation (Rule 38)

**Overview**:
`P2025` (record required but not found, raised by `update`/`delete` on a missing row) maps to HTTP 404.

**Detailed description**:
Services generally check existence before update or delete (customer.service.ts:44,61; product.service.ts:46,64), so P2025 normally appears only when a row is deleted concurrently between the check and the write. In that case the middleware returns `{ code: 'NOT_FOUND', message: 'Resource not found' }` (error.middleware.ts:48-53), which is less specific than the `NotFoundError('Customer')` message from the pre-check. Every other Prisma error code (P2003 FK, P2034 transaction conflict/deadlock, P2028 transaction API error/timeout, connection errors P1001...) falls through to HTTP 500 with server-side logging.

**Rule workflow**:
```
PrismaClientKnownRequestError
 -> P2002 -> 409
 -> P2025 -> 404
 -> other -> log + 500
```

---

### Business Rule: Prisma client configuration and lifecycle (Rule 39)

**Overview**:
The application uses one PrismaClient for its whole lifetime. Its logging depends on `NODE_ENV`.

**Detailed description**:
`createPrismaClient()` (database.ts:4-8) builds a client with `log: ['warn','error']` in development and `['error']` in `test` and `production`. Query logging is never enabled. The exported `prisma` singleton is created at import time (database.ts:10). Importing `database.ts` therefore triggers env validation (`env.ts:27`), and the process exits on invalid configuration. `env.ts` validates `DATABASE_URL` only as a non-empty string; it is not checked as a URL. `SHADOW_DATABASE_URL` is not validated, because only the migration CLI uses it.

No connection pool parameters are set in code. Pool size and timeouts come from `DATABASE_URL` query parameters such as `connection_limit` and `pool_timeout`. The `.env.example` URL (`mysql://oms_user:oms_password@localhost:3306/oms`) sets none, so Prisma defaults apply (pool size = `num_physical_cpus * 2 + 1`). Prisma extensions, middleware (`$use`), `$on` event handlers and soft-delete or multi-tenant filters are not used.

The connection opens lazily on the first query in the server. Tests open it explicitly (`tests/setup.ts:5`). Graceful shutdown calls `$disconnect()` (server.ts:16). Shutdown does not wait for in-flight HTTP requests or transactions: `server.close` takes a callback, but `$disconnect` and `process.exit(0)` run right away. Requests that are still in progress may therefore lose their DB connection.

`createPrismaClient` is exported but used only inside `database.ts`. The seed builds its own `new PrismaClient()` with default options (seed.ts:4). The `prisma.seed` entry in package.json (`tsx prisma/seed.ts`) and the `db:seed` script (`tsx --env-file=.env prisma/seed.ts`) are two ways to run it. With the first, the Prisma CLI loads `.env` itself.

**Rule workflow**:
```
import database.ts -> env validated -> new PrismaClient(log by NODE_ENV) -> singleton
 -> injected into app -> lazy connect -> SIGINT/SIGTERM -> $disconnect -> exit
```

---

### Business Rule: Password hash persistence and exposure (Rule 40)

**Overview**:
User passwords are stored only as bcrypt hashes. The hash is never returned by the API.

**Detailed description**:
`UserService.createUser` hashes with bcrypt cost 10 (`BCRYPT_ROUNDS`, user.service.ts:16,26) before calling `UserRepository.create`. The repository returns the full `User` entity, including `passwordHash`. Exposure is prevented at the service level by `UserService.toPublic` (user.service.ts:42-51), which lists the public fields explicitly. The repository does not use Prisma `select`/`omit` to exclude the column, so any new code path that returns a raw `User` would leak the hash. Tested in auth.test.ts:6-17 (`not.toHaveProperty('passwordHash')`).

The seed hashes hard-coded passwords (`admin123`, `operator123`) with the same cost (seed.ts:6-7,191-192). The test factory uses `password123` (factories.ts:20).

**Rule workflow**:
```
password -> bcrypt.hash(10) -> users.passwordHash
read -> User (with hash) -> toPublic -> response without hash
```

---

### Business Rule: Seed data generation (Rule 41)

**Overview**:
The seed script resets the database and fills it with a consistent, demonstrative dataset that covers every order status.

**Detailed description**:
`prisma/seed.ts` first deletes all rows in FK-safe order (seed.ts:181-187). It does not use `TRUNCATE` and does not run in a transaction. It then creates:
- **2 users**: `admin@oms.local` (ADMIN, password `admin123`) and `operador@oms.local` (OPERATOR, password `operator123`).
- **10 customers** with Brazilian names, CPF/CNPJ documents, `+55` phone numbers and JSON addresses, inserted concurrently with `Promise.all`.
- **20 products** (electronics, office supplies) with prices and stock, inserted concurrently.
- **26 orders** from a fixed plan (seed.ts:226-253): 4 PENDING, 5 PAID, 4 PROCESSING, 4 SHIPPED, 6 DELIVERED, 3 CANCELLED.

Customers are assigned round-robin (`i % 10`). The author is the admin when `i % 3 === 0`, otherwise the operator. A 5% discount, floored to cents, applies when `i % 7 === 0` (orders 0, 7, 14, 21). Order numbers come from the same upsert/increment algorithm as the service, each reservation in its own small transaction (seed.ts:165-176). The order and its items are created in a separate, non-transactional `prisma.order.create`, so a failure between the two calls would leave a gap in the numbering.

The status history is rebuilt from `flowFromStatus` (seed.ts:255-262): each order gets one history row per step of the canonical path to its target status. For example, DELIVERED gets `null->PENDING, PENDING->PAID, PAID->PROCESSING, PROCESSING->SHIPPED, SHIPPED->DELIVERED`. CANCELLED orders always follow `PENDING -> CANCELLED`. Reasons are `null` for the initial row and `seed transition X->Y` afterwards. The initial row's reason (`null`) differs from the API's `'order created'`. History rows are inserted one by one in sequence, so `changedAt` values are milliseconds apart and do not reflect a realistic timeline.

**Divergences from runtime business rules (high confidence):**
1. Orders are inserted directly with their target status, bypassing the state machine.
2. **Stock is not debited** for seeded PAID/PROCESSING/SHIPPED/DELIVERED orders, so `products.stockQuantity` does not reflect committed sales. Cancelling a seeded PAID or PROCESSING order through the API then increments stock that was never debited (Rule 32).
3. The order-number logic is duplicated, not shared with `OrderService`.

The seed is destructive and has no environment guard. Running `npm run db:seed` against any database pointed to by `.env` wipes all business data.

**Rule workflow**:
```
deleteMany (7 tables) -> hash passwords -> create users
 -> Promise.all customers, products
 -> for each plan entry: compute items/totals/discount -> reserveOrderNumber ($transaction)
    -> order.create (nested items) -> history path inserts
 -> $disconnect
```

---

### Business Rule: Test database isolation by truncation (Rule 42)

**Overview**:
Each integration test starts from empty tables. Data is wiped through Prisma `deleteMany` in FK-safe order.

**Detailed description**:
`tests/setup.ts` (registered in vitest.config.ts:10) connects in `beforeAll`, deletes all rows from the 7 tables in `beforeEach` (history, items, orders, sequence, products, customers, users), and disconnects in `afterAll`. Vitest runs with `fileParallelism: false` and a single fork (vitest.config.ts:11-17), so test files never share the database concurrently.

The tests use the same `prisma` singleton as the application and therefore the same `DATABASE_URL`. **No separate test database, schema or URL override exists** (no `.env.test`, no `DATABASE_URL` switching in vitest config). The `test` script (`vitest run`) does not load `.env` with `--env-file`, so the variables must already be set in the environment. Confidence: high. Running the tests against a development database deletes all its data, including seeded data. Tests do not run migrations; the schema must already be applied.

Factories (`tests/helpers/factories.ts`) create rows directly through Prisma, bypassing services and validation, with unique emails and SKUs from `Date.now()` plus random suffixes.

**Rule workflow**:
```
vitest -> setup.ts beforeAll $connect
 -> beforeEach deleteMany x7
 -> test: factories (direct prisma) + HTTP via supertest -> app -> same prisma
 -> afterAll $disconnect
```

---

### Business Rule: Migration management (Rule 43)

**Overview**:
Schema evolution uses Prisma Migrate with a shadow database. There is currently one baseline migration.

**Detailed description**:
`migration_lock.toml` pins the provider to `mysql`. The datasource declares `shadowDatabaseUrl = env("SHADOW_DATABASE_URL")` (schema.prisma:8). `.env.example` points the shadow database to `oms_shadow` as `root` (`.env.example:6`). `prisma migrate dev` (script `db:migrate`) needs the shadow database to detect drift. Using root credentials lets Prisma create and drop the shadow database. The docker-compose MySQL service creates only the `oms` database and user, so `oms_shadow` must be creatable by root. Prisma does this automatically.

`db:reset` runs `prisma migrate reset --force`. It drops the database, reapplies all migrations and runs the seed configured in `package.json > prisma.seed` without asking for confirmation.

There is only one migration (`20260519182739_init`), with no incremental history. Every DDL statement in it was generated by Prisma, and no hand-written SQL extensions exist: no CHECK constraints, triggers, views or stored procedures. No deploy-time command (`prisma migrate deploy`) appears among the scripts. How production migrations are applied is not specified in the repository.

If `SHADOW_DATABASE_URL` is not set, Prisma CLI commands that read the datasource may fail validation. Confidence: low/medium; behavior varies by Prisma command. The runtime PrismaClient does not use this variable.

**Rule workflow**:
```
edit schema.prisma -> npm run db:migrate (shadow DB diff) -> new migration folder -> commit
npm run db:reset -> drop + apply all migrations + seed
```

---

## 4. Component Structure

```
mba-ia-desafio-design-docs-com-ia/
├── prisma/
│   ├── schema.prisma                         # Datasource (MySQL + shadow DB), generator, 2 enums, 7 models, relations, indexes, @@map
│   ├── seed.ts                               # Destructive reset + demo dataset (users, customers, products, orders, history)
│   └── migrations/
│       ├── migration_lock.toml               # Provider lock: mysql
│       └── 20260519182739_init/
│           └── migration.sql                 # DDL: 7 tables, ENUMs, unique/secondary indexes, 6 FKs (RESTRICT/CASCADE), utf8mb4_unicode_ci
├── src/
│   ├── config/
│   │   ├── database.ts                       # createPrismaClient() + module-level singleton `prisma`
│   │   └── env.ts                            # Zod validation of DATABASE_URL (and others) used by database.ts
│   ├── app.ts                                # Composition root: injects prisma into repositories and OrderService
│   ├── server.ts                             # Imports singleton, graceful $disconnect on SIGINT/SIGTERM
│   ├── middlewares/
│   │   └── error.middleware.ts               # Prisma error translation (P2002 -> 409, P2025 -> 404)
│   └── modules/
│       ├── users/user.repository.ts          # findById, findByEmail, create
│       ├── customers/customer.repository.ts  # list ($transaction batch), findById, findByEmail, create, update, delete
│       ├── products/product.repository.ts    # list ($transaction batch), findById, findBySku, findManyByIds (unused), create, update, delete
│       └── orders/
│           ├── order.repository.ts           # list ($transaction batch), findByIdWithRelations, findById, deleteById; OrderWithRelations type
│           ├── order.service.ts              # Interactive $transaction: create, changeStatus, debit/replenish stock, reserveOrderNumber
│           └── order.status.ts               # Uses generated OrderStatus enum; transition + stock-effect rules
├── tests/
│   ├── setup.ts                              # $connect / per-test deleteMany x7 / $disconnect
│   ├── helpers/factories.ts                  # Direct prisma.create factories for User/Customer/Product
│   ├── orders.test.ts                        # Integration tests touching transactions, stock, history, sequence
│   └── auth.test.ts                          # Integration tests touching users table uniqueness
├── docker-compose.yml                        # MySQL 8.0 service, utf8mb4 server defaults, volume oms_mysql_data
├── .env.example                              # DATABASE_URL, SHADOW_DATABASE_URL, MySQL credentials
├── package.json                              # prisma/@prisma/client 5.22.0, db:migrate/db:reset/db:seed, prisma.seed
└── vitest.config.ts                          # Serial single-fork execution (shared DB)
```

---

## 5. Dependency Analysis

### Internal dependencies

```
server.ts ─────────────► config/database.ts ──► config/env.ts ──► zod
server.ts ─► app.ts(buildApp({prisma}))
app.ts ─► UserRepository(prisma)     ◄── UserService ◄── AuthService
app.ts ─► CustomerRepository(prisma) ◄── CustomerService
app.ts ─► ProductRepository(prisma)  ◄── ProductService
app.ts ─► OrderRepository(prisma)    ◄── OrderService ──► prisma ($transaction, tx.* delegates)
                                             └──────────► order.status.ts ──► @prisma/client (OrderStatus)
order.schemas.ts ─► @prisma/client (OrderStatus enum for z.nativeEnum)
error.middleware.ts ─► @prisma/client (Prisma.PrismaClientKnownRequestError)
customer/product/user services ─► @prisma/client (entity types)
prisma/seed.ts ─► @prisma/client (own PrismaClient, OrderStatus, UserRole) ─► bcrypt
tests/setup.ts, tests/helpers/factories.ts, tests/orders.test.ts ─► config/database.ts (singleton)
@prisma/client (generated) ◄── prisma/schema.prisma (prisma generate)
migration.sql ◄── prisma/schema.prisma (prisma migrate dev)
```

### External dependencies

- **@prisma/client 5.22.0**: generated, type-safe query client and runtime query engine.
- **prisma 5.22.0** (dev): CLI for migrate, generate and seed.
- **MySQL 8.0** (docker image `mysql:8.0`): relational store, InnoDB, `mysql_native_password` auth plugin.
- **bcrypt 5.1.1**: password hashing in the seed and the test factories (and in UserService).
- **tsx 4.19.2** (dev): runs `prisma/seed.ts`.
- **zod 3.23.8**: validates `DATABASE_URL` presence (env.ts).
- **vitest 2.1.4 / supertest 7.0.0** (dev): integration tests against the real database.

---

## 6. Afferent and Efferent Coupling

Units are the TypeScript modules and classes that make up or directly consume the persistence layer. Afferent coupling (Ca) is the number of project modules that import or depend on the unit. Efferent coupling (Ce) is the number of project or external modules the unit imports. Counts come from `import` statements; type-only imports are included.

| Component | Afferent Coupling (Ca) | Efferent Coupling (Ce) | Critical |
|-----------|------------------------|------------------------|----------|
| prisma/schema.prisma (generated `@prisma/client` types/enums) | 15 (app.ts, database.ts, error.middleware.ts, 4 repositories, customer/product/user/order services, order.schemas.ts, order.status.ts, seed.ts, tests/helpers/factories.ts) | 0 | High |
| `prisma` singleton (src/config/database.ts) | 4 (server.ts, tests/setup.ts, tests/helpers/factories.ts, tests/orders.test.ts) + indirect to every repository via app.ts | 2 (@prisma/client, env.ts) | High |
| `createPrismaClient` (src/config/database.ts) | 0 external (internal use only) | 2 | Low |
| OrderService (Prisma consumer) | 2 (app.ts, order.controller.ts) | 6 (@prisma/client, order.repository, order.schemas, shared/errors, order.status, shared/http/response) | High |
| OrderRepository | 2 (app.ts, order.service.ts) | 1 (@prisma/client) | Medium |
| CustomerRepository | 2 (app.ts, customer.service.ts) | 1 (@prisma/client) | Medium |
| ProductRepository | 2 (app.ts, product.service.ts) | 1 (@prisma/client) | Medium |
| UserRepository | 3 (app.ts, user.service.ts, auth.service.ts) | 1 (@prisma/client) | Medium |
| order.status.ts (uses OrderStatus enum) | 1 (order.service.ts) | 1 (@prisma/client) | High |
| error.middleware.ts (Prisma error mapping) | 1 (app.ts) | 4 (@prisma/client, zod, shared/errors, logger) | Medium |
| prisma/seed.ts | 0 (CLI entry) | 2 (@prisma/client, bcrypt) | Low |
| migration 20260519182739_init | 0 (applied by CLI) | 0 | High (production schema) |
| tests/setup.ts | 0 (vitest setupFiles) | 2 (vitest, database.ts) | Medium |

Observations:
- The generated Prisma types act as the domain model. Entity types (`Customer`, `Product`, `Order`, `User`) and enums (`OrderStatus`) flow from the persistence layer into services, schemas (Zod `nativeEnum`) and controllers, with no separate domain or DTO layer. So schema changes ripple directly into every module.
- `OrderService` has the highest efferent coupling. It is the only service that depends on `PrismaClient` directly, bypassing its repository for transactional operations.

---

## 7. Endpoints

The persistence layer does not expose endpoints itself. The table below lists the HTTP endpoints whose handlers reach it, with the persistence operations they cause.

| Endpoint | Method | Persistence operation(s) |
|----------|--------|--------------------------|
| /api/v1/auth/register | POST | users: findUnique(email), create |
| /api/v1/auth/login | POST | users: findUnique(email) |
| /api/v1/auth/me | GET | users: findUnique(id) |
| /api/v1/users/:id | GET (ADMIN) | users: findUnique(id) |
| /api/v1/customers | GET | $transaction[customers.findMany, count] |
| /api/v1/customers/:id | GET | customers.findUnique |
| /api/v1/customers | POST | customers.findUnique(email), create |
| /api/v1/customers/:id | PATCH | customers.findUnique(id), findUnique(email), update |
| /api/v1/customers/:id | DELETE | customers.findUnique, delete (FK RESTRICT from orders) |
| /api/v1/products | GET | $transaction[products.findMany, count] |
| /api/v1/products/:id | GET | products.findUnique |
| /api/v1/products | POST | products.findUnique(sku), create |
| /api/v1/products/:id | PATCH | products.findUnique(id), findUnique(sku), update |
| /api/v1/products/:id | DELETE | products.findUnique, delete (FK RESTRICT from order_items) |
| /api/v1/orders | GET | $transaction[orders.findMany, count] |
| /api/v1/orders/:id | GET | orders.findUnique + include items.product, history, customer |
| /api/v1/orders | POST | interactive $transaction: customer, products, sequence upsert, order+items+history create |
| /api/v1/orders/:id/status | PATCH | interactive $transaction: order read, product stock updates, order update, history create, re-read |
| /api/v1/orders/:id | DELETE | orders.findUnique, delete (cascade items + history) |
| /health | GET | None (does not check DB connectivity) |

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| MySQL 8.0 (`DATABASE_URL`) | Database | Primary persistence for all entities | MySQL wire protocol through the Prisma query engine (connection pool) | Relational rows; `JSON` for customers.address; native ENUM | Prisma errors: P2002 -> 409, P2025 -> 404, others -> 500 with log; no retry, no circuit breaker |
| MySQL shadow DB (`SHADOW_DATABASE_URL`) | Database (dev tooling) | Drift detection for `prisma migrate dev` | MySQL | DDL | CLI failure only |
| Prisma Query Engine (@prisma/client 5.22.0) | Library / native engine | Query building, UUID generation, `@updatedAt`, transactions | In-process (Node-API library engine) | JS objects <-> SQL | Throws typed errors (`PrismaClientKnownRequestError`, etc.) |
| Prisma CLI (prisma 5.22.0) | Dev tooling | migrate dev/reset, generate, seed | Process | schema.prisma, SQL | Non-zero exit |
| Docker Compose `mysql` service | Infrastructure | Local DB with utf8mb4 defaults, healthcheck via `mysqladmin ping` | Docker | n/a | `restart: unless-stopped`; healthcheck 20 retries |
| bcrypt | Library | Password hashing before persistence (seed, factories, UserService) | In-process | String hash | Exceptions propagate |

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Repository Pattern (partial) | `UserRepository`, `CustomerRepository`, `ProductRepository`, `OrderRepository` wrap Prisma delegates | src/modules/*/*.repository.ts | Encapsulate query construction (where, orderBy, pagination, includes) |
| Constructor Dependency Injection | Repositories take `PrismaClient`; `OrderService` takes `OrderRepository` + `PrismaClient` | src/app.ts:26-53 | Testability, single composition root |
| Singleton | Module-level `prisma` instance | src/config/database.ts:10 | One connection pool per process |
| Factory Function | `createPrismaClient()` | src/config/database.ts:4-8 | Environment-dependent client configuration |
| Unit of Work (Prisma interactive transaction) | `prisma.$transaction(async tx => ...)` | src/modules/orders/order.service.ts:58,131; prisma/seed.ts:166 | Atomic multi-entity business operations |
| Batch Transaction | `prisma.$transaction([findMany, count])` | customer/product/order repositories | Snapshot-consistent page + total |
| Aggregate Root with cascading children | `Order` owns `OrderItem` and `OrderStatusHistory` (onDelete: Cascade); nested writes | prisma/schema.prisma:108,125; order.service.ts:105-113 | Lifecycle consistency of the order aggregate |
| Audit Log (append-only history table) | `OrderStatusHistory` | prisma/schema.prisma:116-131 | Traceability of status changes (who, when, why) |
| Sequence Table (DB-backed counter) | `OrderNumberSequence` singleton row + upsert/increment | prisma/schema.prisma:133-138; order.service.ts:245-254 | Gap-free human-readable order numbers |
| Snapshot / Denormalization | `unitPriceCents`, `subtotalCents`, `totalCents` stored on orders/items | order.service.ts:75-92 | Freeze commercial terms; cheap list reads |
| Money as Integer Minor Units | `*Cents` Int fields | prisma/schema.prisma | Exact arithmetic |
| Soft availability flag | `Product.active` | prisma/schema.prisma:63; order.service.ts:66-73 | Retire products without breaking FK history |
| Exception Translation | Prisma error codes -> HTTP | src/middlewares/error.middleware.ts:37-54 | Uniform API errors |
| Atomic counter updates | `{ increment }` / `{ decrement }` | order.service.ts:228,240,249 | Avoid lost updates on stock and sequence |
| Specification-like query builder | Private `buildWhere()` per repository | repositories | Centralize filter semantics |
| Test Data Builder / Object Mother | `createTestUser/Customer/Product` | tests/helpers/factories.ts | Reproducible integration fixtures |
| Database-per-run reset | `deleteMany` in `beforeEach` | tests/setup.ts:8-16 | Test isolation over a shared DB |

Architectural decisions observed (implicit, not documented in an ADR in the code base):
1. Prisma-generated types are used as domain entities (no separate domain model).
2. Transaction boundaries are controlled in the service layer (`OrderService`), not in repositories.
3. Business invariants (state machine, stock non-negativity, totals) live in application code, not in DB constraints.
4. Physical naming: snake_case tables, camelCase columns.
5. UUID v4 surrogate keys generated client-side.

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| High | OrderService.changeStatus / debitStock | Check-then-act without row locking or conditional update: the stock availability check uses a snapshot read, and the order status read is not locked (order.service.ts:132-158,208-230) | Concurrent payments can drive `stockQuantity` negative; concurrent identical transitions can double-debit stock and duplicate history rows |
| High | error.middleware.ts | Prisma `P2003` (FK violation) is not mapped (error.middleware.ts:37-54) | Deleting a customer with orders or a product with order items returns HTTP 500 instead of a domain error |
| High | Test infrastructure | Tests use the same `DATABASE_URL` as the application and `deleteMany` every table before each test (tests/setup.ts:8-16) | Running tests against a development or shared database destroys its data |
| High | prisma/seed.ts | Destructive reset with no environment guard; hard-coded known credentials (`admin123`, `operator123`) (seed.ts:6-7,181-187) | Data loss if run against the wrong database; weak default credentials if seeded in a reachable environment |
| Medium | prisma/seed.ts | Seeded PAID/PROCESSING/SHIPPED/DELIVERED orders never debit stock (seed.ts:264-321) | Inventory figures are inconsistent with orders; cancelling seeded PAID/PROCESSING orders inflates stock |
| Medium | Order numbering | Single-row sequence locked for the whole order-creation transaction (order.service.ts:93,245-254) | Order creation is serialized and limits write throughput; first-insert race on an empty table can yield 409 |
| Medium | OrderService.delete | Status check and delete are not in one transaction (order.service.ts:181-192) | Race with a concurrent PENDING -> PAID could delete a paid order and lose debited stock |
| Medium | Repository abstraction | Repositories accept only `PrismaClient`, so transactional code in OrderService uses `tx.*` directly; `ProductRepository.findManyByIds` is unused | Data access logic is split between repositories and service; duplicated include shapes (order.repository.ts:50-58 vs order.service.ts:115-119,171-175) |
| Medium | Audit trail | `OrderStatusHistory` cascades on order delete (schema.prisma:125) | Audit evidence is permanently lost when PENDING/CANCELLED orders are deleted |
| Medium | Schema constraints | No DB CHECK constraints for non-negative stock, prices, quantities, `discount <= subtotal`, `total = subtotal - discount` | Invariants depend fully on application code; raw SQL or new code paths can corrupt data |
| Medium | Integer money | 32-bit signed INT for cents with no upper-bound validation on quantity/price | Large orders can overflow the column, giving an unhandled DB error (HTTP 500) |
| Medium | Indexing | No `createdAt` index on customers/products although lists sort by it; `contains` searches cannot use indexes; no composite indexes for filtered + sorted order lists | Full scans and filesorts as data grows; deep offset pagination cost |
| Medium | Pagination stability | `orderBy createdAt` without a unique tiebreaker | Duplicate or missing rows across pages when timestamps tie |
| Low | Uniqueness handling | Two error codes for the same condition (`EMAIL_ALREADY_USED`/`SKU_ALREADY_USED` vs generic `CONFLICT`); P2002 message exposes index names | Inconsistent client contract; minor schema disclosure |
| Low | Naming | Hybrid snake_case tables / camelCase columns | Friction for raw SQL, BI tools and CDC/outbox consumers |
| Low | Customer.address | JSON column with no DB schema; full replacement on update | Malformed or partial addresses possible outside the API; no typed access |
| Low | customers.document | Not unique (only indexed) | Duplicate CPF/CNPJ customers possible; intent undocumented |
| Low | Role typing | `'ADMIN' | 'OPERATOR'` literals instead of generated `UserRole` (user.repository.ts:14; user.service.ts:11) | Enum changes require manual synchronization |
| Low | Duplicate logic | `reserveOrderNumber` duplicated in seed and service | Divergence risk if the format changes |
| Low | Graceful shutdown | `$disconnect` and `process.exit(0)` run without waiting for in-flight requests (server.ts:13-18) | In-flight transactions may be aborted on shutdown |
| Low | Transaction configuration | No explicit `timeout`, `maxWait` or `isolationLevel`; no retry for deadlocks/serialization errors (P2034) | Defaults (5 s) may abort long transactions; transient conflicts surface as HTTP 500 |
| Low | Health check | `/health` does not probe DB connectivity (app.ts:62-64) | Orchestrators may route traffic to an instance without DB access |
| Low | Migrations | Single baseline migration; no `migrate deploy` script; shadow DB uses root credentials in `.env.example` | Undefined production migration procedure |
| Low | OrderItem uniqueness | No unique `(orderId, productId)` constraint; aggregation only in code | Duplicate lines possible through non-API writes |

---

## 11. Test Coverage Analysis

Test files (all outside the component folders):
- `tests/setup.ts`: global DB lifecycle and truncation.
- `tests/helpers/factories.ts`: direct Prisma factories.
- `tests/orders.test.ts`: 8 integration tests.
- `tests/auth.test.ts`: 7 integration tests.

Runner: Vitest 2.1.4 (`vitest.config.ts`), serial single fork, 30 s timeouts. All tests are HTTP-level integration tests through supertest against a real MySQL database. There are **no unit tests, no mocks of Prisma and no coverage tooling**: `coverage/` is git-ignored, but no coverage provider or script is configured. The percentages below are qualitative estimates from code-path inspection, not measured values.

| Component | Unit Tests | Integration Tests | Coverage (estimated, paths exercised) | Test Quality |
|-----------|------------|-------------------|---------------------------------------|--------------|
| prisma/schema.prisma + migration (constraints) | 0 | Indirect: users_email unique (auth.test.ts:19-28, via pre-check only) | Low: no test triggers P2002/P2003/P2025, cascades or RESTRICT | DB constraints untested; cascade on order delete untested |
| src/config/database.ts | 0 | Indirect (all tests use the singleton) | High for instantiation; logging branch by NODE_ENV untested | Adequate for its size |
| OrderService.create ($transaction) | 0 | 2 (orders.test.ts:12-40, 42-57) + used by 6 others | Medium: happy path, totals, history, order number format, missing product; not covered: missing customer, inactive product, discount > subtotal, duplicate item aggregation, rollback of sequence | Good assertions on computed totals and history |
| OrderService.changeStatus / debit / replenish | 0 | 4 (orders.test.ts:59-87, 89-107, 109-132, 134-161) | Medium: PENDING->PAID debit, insufficient stock rollback (asserts stock unchanged), invalid transition, PAID->CANCELLED replenish; not covered: PROCESSING->CANCELLED, same-status conflict, concurrency, not-found | Good: verifies DB state directly via prisma after HTTP calls |
| OrderService.delete / OrderRepository.deleteById | 0 | 1 (orders.test.ts:197-218) | Low: only the refusal path; successful delete and cascade not verified | Missing positive case |
| OrderRepository.list ($transaction batch) | 0 | 1 (orders.test.ts:163-195) | Low-Medium: status filter + total; customerId/from/to filters and pagination boundaries untested | Asserts both data and pagination.total |
| OrderRepository.findByIdWithRelations | 0 | 0 direct (GET /orders/:id not called) | Low | Not tested |
| OrderNumberSequence | 0 | Indirect (format regex, orders.test.ts:39) | Low: increment sequence and first-row creation implicitly; no concurrency test | Weak |
| UserRepository | 0 | 7 (auth.test.ts) | Medium-High: findByEmail, create, findById (via /me) | Verifies passwordHash not exposed |
| CustomerRepository | 0 | 0 (customers are created only through factories) | None for repository methods | Not tested |
| ProductRepository | 0 | 0 (products are created only through factories) | None for repository methods | Not tested |
| error.middleware.ts Prisma mapping | 0 | 0 for P2002/P2025 branches | None | Not tested |
| prisma/seed.ts | 0 | 0 | None | Not tested |
| tests/setup.ts truncation order | n/a | Exercised by every test | n/a | Correct FK-safe order |

Key gaps:
- No tests for Customer or Product endpoints or repositories (CRUD, search, pagination, uniqueness conflicts).
- No tests for FK RESTRICT behavior (customer/product deletion with references), so the unhandled P2003 -> 500 path is invisible.
- No concurrency tests for stock debit, status transitions or order numbering.
- No tests of cascade deletion of items and history.
- No migration verification (e.g. schema drift check) in the test suite.
- Tests depend on an externally provisioned, migrated database. There is no automated provisioning or test-specific `DATABASE_URL`.
