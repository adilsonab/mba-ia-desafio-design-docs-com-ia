# Component Deep Analysis Report

**Component:** OrdersModule (`src/modules/orders/`)
**Project:** order-management-api (Node.js 20 + TypeScript + Express 4.21.1 + Prisma 5.22.0 + MySQL)
**Analysis date:** 2026-11-02
**Scope:** `order.service.ts`, `order.status.ts`, `order.repository.ts`, `order.controller.ts`, `order.routes.ts`, `order.schemas.ts`, plus the Prisma models they rely on (`prisma/schema.prisma`), the wiring (`src/app.ts`, `src/routes/index.ts`), shared middlewares/errors, and tests (`tests/orders.test.ts`, `tests/setup.ts`, `tests/helpers/factories.ts`).
**Ignored:** `node_modules`, `dist`, `.git`, `docs`.

---

## 1. Executive Summary

The OrdersModule is the core business component of the Order Management System (OMS). It manages the order lifecycle: creating orders with server-side pricing, listing and reading orders, changing order status through a controlled state machine, and deleting orders under restricted conditions. It is the only module that changes data owned by other modules (it debits and replenishes `Product.stockQuantity`) and the only one that writes an audit trail (`OrderStatusHistory`).

The module follows a layered structure (Routes -> Controller -> Service -> Repository/Prisma) with manual dependency injection in `src/app.ts:42-44`. Order rules sit in two places: a pure, side-effect-free state machine module (`order.status.ts`), and a service (`order.service.ts`) that runs multi-entity changes inside Prisma interactive transactions (`$transaction(async (tx) => ...)`).

Key findings:

- **State machine:** six states (`PENDING`, `PAID`, `PROCESSING`, `SHIPPED`, `DELIVERED`, `CANCELLED`) with a forward-only transition table and two terminal states (`order.status.ts:3-10`). Cancellation is allowed from `PENDING`, `PAID` and `PROCESSING`, but not from `SHIPPED`.
- **Stock control is tied to status, not to order creation:** stock is checked and debited only on `PENDING -> PAID` (`order.status.ts:24-31`, `order.service.ts:151-153`). It is given back only on `PAID|PROCESSING -> CANCELLED` (`order.status.ts:33-37`, `order.service.ts:154-156`). Creating an order does not reserve stock.
- **Atomicity:** order creation and status change each run in a single DB transaction. This covers order number reservation, item snapshot, history entry, stock movement, status update and audit record.
- **Concurrency gap (High risk):** status change and stock debit use read-then-write with no row locking (no `SELECT ... FOR UPDATE`) and no optimistic version check. Concurrent requests can debit stock twice or push stock below zero (Section 10).
- **Audit trail:** every state change, including the initial creation, writes an `OrderStatusHistory` row with actor and optional reason. Deleting an order cascades and removes that history (`prisma/schema.prisma:125`).
- **Order number:** a single-row counter table (`order_number_sequence`) is incremented inside the creation transaction, producing `ORD-000001`-style numbers with no gaps (`order.service.ts:245-254`).
- **Authorization:** all endpoints require a valid JWT (`order.routes.ts:14`), but there is no role-based restriction. Any authenticated `OPERATOR` can delete orders or move them through any valid transition.
- **No outbound integration:** the module emits no events or notifications. The project README describes a planned "Order Notification Webhooks" feature that would need to hook into the status change flow.
- **Tests:** 8 integration tests (supertest + real MySQL) cover the main paths. There are no unit tests for the pure state machine, and no concurrency, delete-success, cancellation-from-PROCESSING or inactive-product tests.

---

## 2. Data Flow Analysis

### 2.1 Create order (`POST /api/v1/orders`)

```
1. Express app receives request (src/app.ts:59 express.json limit 1mb; request logger src/app.ts:60)
2. src/routes/index.ts:28 mounts the router under /orders
3. order.routes.ts:14 authenticate middleware verifies the JWT and fills req.user {id, email, role}
4. order.routes.ts:18 validate({ body: createOrderSchema }) parses and normalizes the body with Zod
   (default discountCents = 0; error -> ValidationError 400)
5. order.controller.ts:28-36 OrderController.create checks req.user and calls OrderService.create(body, userId)
6. order.service.ts:51-53 checks for an empty items list again (unreachable after Zod)
7. order.service.ts:55 aggregateItems merges duplicate productIds and sums quantities
8. order.service.ts:58 opens a Prisma interactive transaction
   8.1 :59-60  load the customer; NotFoundError('Customer') -> 404
   8.2 :62-65  load the products by id; a count mismatch -> NotFoundError('Product') -> 404
   8.3 :66-73  reject inactive products -> 422 INACTIVE_PRODUCT {skus}
   8.4 :75-84  snapshot the price (unitPriceCents = product.priceCents) and compute line totals
   8.5 :86-91  compute subtotal; discount > subtotal -> 400 VALIDATION_ERROR
   8.6 :92     totalCents = subtotal - discount
   8.7 :93     reserveOrderNumber(tx) upserts and increments order_number_sequence
   8.8 :95-120 nested create of the order (status PENDING) + items + first history row,
               with relations included
9. Transaction commits; the controller returns 201 with OrderWithRelations
10. On any thrown error, next(err) -> errorMiddleware (src/middlewares/error.middleware.ts) maps it to JSON
```

### 2.2 Change status (`PATCH /api/v1/orders/:id/status`)

```
1. authenticate (order.routes.ts:14)
2. validate params (uuid) + body { toStatus: OrderStatus enum, reason?: string<=500 } (order.routes.ts:19-23)
3. OrderController.changeStatus (order.controller.ts:38-46) -> OrderService.changeStatus(id, body, userId)
4. Prisma interactive transaction (order.service.ts:131-178):
   4.1 load the order with its items (:132-136) -> 404 if missing
   4.2 same-state guard (:140-146) -> 409 INVALID_STATUS_TRANSITION
   4.3 state machine guard canTransition (:147-149) -> 409 INVALID_STATUS_TRANSITION
   4.4 stock debit if PENDING->PAID (:151-153) -> 422 INSUFFICIENT_STOCK on shortage
   4.5 stock replenish if PAID|PROCESSING->CANCELLED (:154-156)
   4.6 update order.status (:158)
   4.7 insert an OrderStatusHistory row (:159-167)
   4.8 reload the order with relations (:169-176)
5. Commit; 200 with the updated OrderWithRelations
```

### 2.3 List orders (`GET /api/v1/orders`)

```
1. authenticate -> validate({ query: listOrdersQuerySchema }) (order.routes.ts:16)
   - the validate middleware copies the parsed values onto req.query with Object.assign
     (src/middlewares/validate.middleware.ts:16)
2. OrderController.list casts req.query to ListOrdersQuery (order.controller.ts:11)
3. OrderService.list computes skip=(page-1)*pageSize, take=pageSize (order.service.ts:32-42)
4. OrderRepository.list builds the where clause (status, customerId, createdAt range) and runs
   findMany + count in a batch $transaction (order.repository.ts:21-45)
5. paginated() wraps the result as { data, pagination{page,pageSize,total,totalPages} }
   (src/shared/http/response.ts)
6. 200
```

### 2.4 Get order (`GET /api/v1/orders/:id`)

```
1. authenticate -> validate params uuid
2. OrderService.getById -> OrderRepository.findByIdWithRelations (order.repository.ts:47-60)
   includes items (with product id/sku/name), history (asc by changedAt), customer (id/name/email)
3. null -> NotFoundError('Order') 404; otherwise 200
```

### 2.5 Delete order (`DELETE /api/v1/orders/:id`)

```
1. authenticate -> validate params uuid
2. OrderService.delete (order.service.ts:181-192)
   2.1 OrderRepository.findById -> 404 if missing
   2.2 status not in {PENDING, CANCELLED} -> 409 INVALID_ORDER_STATE_FOR_DELETE {status}
   2.3 OrderRepository.deleteById -> DB cascade removes order_items and order_status_history
3. 204 No Content
```

---

## 3. Business Rules & Logic

### Overview of the business rules

| # | Rule Type | Rule Description | Location |
|---|-----------|------------------|----------|
| BR-01 | State Machine | Allowed transitions: PENDING->{PAID,CANCELLED}; PAID->{PROCESSING,CANCELLED}; PROCESSING->{SHIPPED,CANCELLED}; SHIPPED->{DELIVERED}; DELIVERED and CANCELLED are terminal | src/modules/orders/order.status.ts:3-14 |
| BR-02 | Validation | Transition to the same status is rejected with 409 INVALID_STATUS_TRANSITION | src/modules/orders/order.service.ts:140-146 |
| BR-03 | Validation | Transition not in the table is rejected with 409 INVALID_STATUS_TRANSITION {from,to} | src/modules/orders/order.service.ts:147-149; src/shared/errors/http-errors.ts (InvalidStatusTransitionError) |
| BR-04 | Stock | Stock is debited only on PENDING -> PAID | src/modules/orders/order.status.ts:24-31; order.service.ts:151-153 |
| BR-05 | Stock | All-or-nothing stock availability check; shortage -> 422 INSUFFICIENT_STOCK with per-SKU details | src/modules/orders/order.service.ts:204-231 |
| BR-06 | Stock | Stock is replenished only on PAID -> CANCELLED or PROCESSING -> CANCELLED | src/modules/orders/order.status.ts:33-37; order.service.ts:154-156, 233-243 |
| BR-07 | Stock | Order creation does not reserve or check stock | src/modules/orders/order.service.ts:50-124 (absence) |
| BR-08 | Transaction | Status change (guards, stock, status update, history, reload) is one atomic DB transaction | src/modules/orders/order.service.ts:126-179 |
| BR-09 | Audit | Each status change writes an OrderStatusHistory row (from, to, changedById, reason, changedAt) | src/modules/orders/order.service.ts:159-167; prisma/schema.prisma:116-131 |
| BR-10 | Audit | Order creation writes the first history row (fromStatus null -> PENDING, reason "order created") | src/modules/orders/order.service.ts:106-113 |
| BR-11 | Identity | Sequential, human-readable order number ORD-NNNNNN from a single-row sequence table, reserved inside the creation transaction | src/modules/orders/order.service.ts:93, 245-254; prisma/schema.prisma:133-138 |
| BR-12 | Validation | An order needs at least one item | src/modules/orders/order.schemas.ts:13; order.service.ts:51-53 |
| BR-13 | Validation | Item productId must be a UUID; quantity a positive integer | src/modules/orders/order.schemas.ts:6-9 |
| BR-14 | Business Logic | Duplicate product lines are merged and their quantities summed | src/modules/orders/order.service.ts:55, 194-202 |
| BR-15 | Validation | Customer must exist (404 Customer) | src/modules/orders/order.service.ts:59-60 |
| BR-16 | Validation | All products must exist (404 Product) | src/modules/orders/order.service.ts:62-65 |
| BR-17 | Validation | All products must be active (422 INACTIVE_PRODUCT {skus}) | src/modules/orders/order.service.ts:66-73 |
| BR-18 | Pricing | Unit price is taken from the server catalog at creation time (price snapshot); clients cannot send prices | src/modules/orders/order.service.ts:75-84 |
| BR-19 | Pricing | subtotal = sum(unitPrice * qty); total = subtotal - discount; all values in integer cents | src/modules/orders/order.service.ts:86, 92 |
| BR-20 | Validation | discountCents is a non-negative integer, default 0, and must not exceed the subtotal | src/modules/orders/order.schemas.ts:14; order.service.ts:87-91 |
| BR-21 | Validation | notes optional, max 1000 chars; status-change reason optional, max 500 chars | src/modules/orders/order.schemas.ts:15, 20 |
| BR-22 | Initial State | New orders always start in PENDING, regardless of input | src/modules/orders/order.service.ts:99 |
| BR-23 | Deletion | Orders can be deleted only in PENDING or CANCELLED (409 INVALID_ORDER_STATE_FOR_DELETE) | src/modules/orders/order.service.ts:181-192 |
| BR-24 | Deletion | Deleting an order cascades to items and status history | prisma/schema.prisma:108, 125 |
| BR-25 | Query | List pagination: page >= 1 (default 1), pageSize 1..100 (default 20), ordered by createdAt desc | src/modules/orders/order.schemas.ts:23-25; order.repository.ts:38 |
| BR-26 | Query | List filters: status, customerId, createdAt range [from, to] inclusive | src/modules/orders/order.schemas.ts:26-29; order.repository.ts:21-31 |
| BR-27 | Security | All order endpoints require a valid Bearer JWT; no role restriction | src/modules/orders/order.routes.ts:14; src/middlewares/auth.middleware.ts |
| BR-28 | Accountability | Creator (createdById) and status changer (changedById) are taken from the authenticated JWT subject, never from the request body | src/modules/orders/order.controller.ts:31, 41; order.service.ts:104, 110, 164 |
| BR-29 | Read Model | Order detail exposes items (with product id/sku/name), history ascending by changedAt, and customer id/name/email | src/modules/orders/order.repository.ts:47-60; order.service.ts:115-119, 170-175 |
| BR-30 | State Machine (unused helpers) | allowedTransitions() and isTerminal() are exported but not used anywhere | src/modules/orders/order.status.ts:16-22 |

---

### Detailed breakdown of the business rules

---

### Business Rule: BR-01 Order Status State Machine

**Overview**:
The order lifecycle is a finite state machine declared as a read-only lookup table, `transitions: Readonly<Record<OrderStatus, ReadonlyArray<OrderStatus>>>` (`order.status.ts:3-10`). `canTransition(from, to)` (`order.status.ts:12-14`) returns `transitions[from].includes(to)`. The Prisma enum `OrderStatus` (`prisma/schema.prisma:16-23`) is the single source of the state names.

**Detailed description**:
The table defines the following edges:

| From | Allowed To |
|------|------------|
| PENDING | PAID, CANCELLED |
| PAID | PROCESSING, CANCELLED |
| PROCESSING | SHIPPED, CANCELLED |
| SHIPPED | DELIVERED |
| DELIVERED | (none, terminal) |
| CANCELLED | (none, terminal) |

The happy path is strictly linear: PENDING -> PAID -> PROCESSING -> SHIPPED -> DELIVERED. No step can be skipped. A request for PENDING -> SHIPPED is rejected with HTTP 409 and code `INVALID_STATUS_TRANSITION`, which `tests/orders.test.ts:89-107` checks. No backward move exists. An order cannot go from PAID back to PENDING or from SHIPPED back to PROCESSING. Corrections therefore need cancellation (where allowed) and a new order.

Cancellation is possible from every non-terminal state except SHIPPED. Once goods have shipped, the system assumes the order can only end as DELIVERED. The code has no "return" or "refund" path after shipment. Because the `Record<OrderStatus, ...>` type forces an entry for every enum value, adding a new enum value without updating the table fails at compile time. That keeps the state machine exhaustive.

`order.status.ts` also exports `allowedTransitions(from)` (line 16) and `isTerminal(status)` (line 20). Neither is referenced anywhere in `src/`, `tests/` or `prisma/`. A consumer (for example an API that returns the next allowed actions, or a webhook filter) could use them, but today they are dead code. The seed script (`prisma/seed.ts`, `flowFromStatus`) builds history paths that follow this same table: CANCELLED orders are seeded only as PENDING -> CANCELLED.

**Rule workflow**:
```
Client PATCH /orders/:id/status { toStatus }
  -> Zod: toStatus must be one of the six enum values (order.schemas.ts:19)
  -> service loads current status (from)
  -> from === to ?        -> 409 INVALID_STATUS_TRANSITION ("Order is already in X status")
  -> !canTransition(from,to) -> 409 INVALID_STATUS_TRANSITION ("Invalid status transition from X to Y")
  -> proceed to stock side effects, status update and history
```

---

### Business Rule: BR-02 / BR-03 Same-State and Invalid Transition Rejection

**Overview**:
Two guards run before any side effect. The first rejects a no-op transition, the second rejects a transition the state machine does not allow. Both return HTTP 409 with the same error code `INVALID_STATUS_TRANSITION`.

**Detailed description**:
The same-state guard (`order.service.ts:140-146`) throws a `ConflictError` with message `Order is already in ${to} status`, code `INVALID_STATUS_TRANSITION`, and details `{from, to}`. Without this guard the outcome would be the same, since no state lists itself as a target, but the message would be the generic one. The explicit guard gives a clearer message for idempotent retries, for example a client that resends "PAID" after a timeout. Note that the API is therefore not idempotent: a retry of a successful transition returns 409, not 200.

The invalid transition guard (`order.service.ts:147-149`) throws `InvalidStatusTransitionError(from, to)`, a subclass of `ConflictError` (`src/shared/errors/http-errors.ts`). It carries the message `Invalid status transition from X to Y` and details `{from, to}`. `errorMiddleware` serializes it as `{ error: { code, message, details } }`.

Both guards run inside the transaction but before any write, so a rejection rolls back nothing of substance. Both use the `from` value read at the start of the transaction. Under concurrency that value can be stale, because no row lock is taken (see BR-08 and Section 10).

**Rule workflow**:
```
order = tx.order.findUnique(id, include items)      # order.service.ts:132-135
if !order -> 404 NOT_FOUND "Order not found"
if order.status == toStatus -> 409 (ConflictError)  # :140-146
if !canTransition(order.status, toStatus) -> 409 (InvalidStatusTransitionError) # :147-149
```

---

### Business Rule: BR-04 / BR-05 Stock Debit on Payment (PENDING -> PAID)

**Overview**:
Inventory is committed only when an order moves from PENDING to PAID. `shouldDebitStock(from, to)` (`order.status.ts:29-31`) is true only for the pair `STOCK_DEBIT_TRANSITION = {from: PENDING, to: PAID}` (`order.status.ts:24-27`). The service then calls `debitStock(tx, order.items)` (`order.service.ts:151-153`).

**Detailed description**:
`debitStock` (`order.service.ts:204-231`) works in two phases. In the validation phase (`:208-224`), it loads all products referenced by the order items in one query (`findMany where id in [...]`). It then checks every item and collects every shortage, not just the first, into an `unavailable` list of `{sku, requested, available}`. If a product row is missing, it reports the productId in place of the SKU and 0 as available. If any shortage exists, it throws `InsufficientStockError(unavailable)`: HTTP 422, code `INSUFFICIENT_STOCK`, details `{unavailable: [...]}`. This is all-or-nothing. Either every line has enough stock or nothing is debited, and the order stays PENDING. `tests/orders.test.ts:109-132` checks the 422, the SKU in the details, and that stock is unchanged.

In the mutation phase (`:225-230`), each item is decremented with a separate `tx.product.update({ data: { stockQuantity: { decrement: quantity } } })`. The decrement is an atomic SQL `SET stockQuantity = stockQuantity - n`, but the availability check came from a plain consistent read in the previous phase. MySQL InnoDB under REPEATABLE READ does not lock rows on a plain `SELECT`. Two concurrent PENDING -> PAID transactions on different orders for the same product can therefore both pass the check and both decrement, leaving stock negative. The schema has no `CHECK (stockQuantity >= 0)` (`prisma/schema.prisma:62`).

Because stock is debited at payment and not at creation (BR-07), a PENDING order is only an intention to buy. Many PENDING orders can exist for more units than are in stock. The first to be paid wins, and later ones get 422 when they try to move to PAID. The debit does not check `product.active`, so an order created while a product was active can still be paid after the product is deactivated.

**Rule workflow**:
```
if from == PENDING and to == PAID:
   products = tx.product.findMany(id in order.items.productId)
   unavailable = []
   for item in order.items:
       p = products[item.productId]
       if p missing or p.stockQuantity < item.quantity:
           unavailable += {sku: p?.sku ?? productId, requested: item.quantity, available: p?.stockQuantity ?? 0}
   if unavailable not empty -> throw 422 INSUFFICIENT_STOCK {unavailable}   (transaction rolls back)
   for item in order.items:
       tx.product.update(stockQuantity -= item.quantity)
```

---

### Business Rule: BR-06 Stock Replenishment on Cancellation

**Overview**:
When a paid order is cancelled, the stock it consumed is returned. `shouldReplenishStock(from, to)` (`order.status.ts:33-37`) returns true when `to === CANCELLED` and `from` is `PAID` or `PROCESSING`. `replenishStock` (`order.service.ts:233-243`) then increments each product's `stockQuantity` by the item quantity.

**Detailed description**:
The rule mirrors BR-04. Stock was debited on entry to PAID, so any cancellation from a state reached after PAID must give it back. The states after PAID that can be cancelled are PAID and PROCESSING. SHIPPED cannot be cancelled (BR-01), so the module never needs to replenish for shipped goods. PENDING -> CANCELLED does not replenish, which is correct because nothing was debited. `tests/orders.test.ts:134-161` checks the full cycle (stock 10 -> PAID -> 6 -> CANCELLED -> 10). The PROCESSING -> CANCELLED path is not tested.

Replenishment is unconditional. There is no availability check, and each item gets an atomic `increment`, so it is safe under concurrency. It does not check whether the product is still active, and it does not cap stock. Products referenced by order items cannot be deleted while the order exists, because the `order_items.productId` foreign key is `ON DELETE RESTRICT` (`prisma/migrations/20260519182739_init/migration.sql:119`). A product row is therefore always present to increment.

Debit and replenishment use the same `order.items` quantities. Those quantities already merge duplicate product lines (BR-14), so each product gets exactly one update per transition. Correct replenishment depends on the debit having happened. That holds for orders created through the API. It does not hold for seeded data: `prisma/seed.ts` inserts orders directly as PAID or PROCESSING without debiting stock, so cancelling a seeded PAID/PROCESSING order adds stock that was never removed.

**Rule workflow**:
```
if to == CANCELLED and from in {PAID, PROCESSING}:
   for item in order.items:
       tx.product.update(stockQuantity += item.quantity)
```

---

### Business Rule: BR-07 No Stock Reservation at Order Creation

**Overview**:
`OrderService.create` (`order.service.ts:50-124`) checks that products exist and are active, but it never reads or changes `stockQuantity`.

**Detailed description**:
The code shows this design choice by omission, and the tests confirm it. `tests/orders.test.ts:109-119` creates an order for 5 units of a product with stock 1 and expects 201. Customers or operators can therefore place orders for any quantity. The stock constraint is enforced only when payment is confirmed (BR-04).

In business terms, PENDING is a quote or cart. It does not hold inventory, so abandoned PENDING orders never lock stock. The trade-off is that a customer can create an order that later cannot be paid. The 422 shows up at the PENDING -> PAID step, not at checkout.

No code documents this rule explicitly (confidence: High, inferred from code and test behavior).

**Rule workflow**:
```
create(): validate customer, products exist, products active -> compute prices -> persist PENDING
(no stock read, no stock write)
```

---

### Business Rule: BR-08 Atomic Status Change Transaction (step by step)

**Overview**:
`OrderService.changeStatus` (`order.service.ts:126-179`) runs every read, guard, side effect and write inside one Prisma interactive transaction (`this.prisma.$transaction(async (tx) => {...})`, line 131). An exception anywhere rolls everything back.

**Detailed description**:
Steps, with line numbers:

1. **Line 131.** `this.prisma.$transaction(async (tx) => ...)` opens an interactive transaction with Prisma defaults: MySQL connection default isolation (InnoDB REPEATABLE READ), maxWait 2s, timeout 5s. No `isolationLevel` or timeout options are passed (a search for `isolationLevel` in `src/` finds none).
2. **Lines 132-135.** `tx.order.findUnique({ where: { id }, include: { items: true } })` loads the order and its raw items (productId, quantity, unitPriceCents, totalCents). This is a non-locking consistent read.
3. **Line 136.** If the order is missing, `NotFoundError('Order')` (404).
4. **Lines 138-139.** `from = order.status`, `to = input.toStatus`.
5. **Lines 140-146.** Same-state guard -> `ConflictError` 409 `INVALID_STATUS_TRANSITION` `{from,to}`.
6. **Lines 147-149.** `canTransition(from, to)`, otherwise `InvalidStatusTransitionError` 409.
7. **Lines 151-153.** If `shouldDebitStock(from,to)` (PENDING->PAID), `debitStock(tx, order.items)`: one `findMany` on products, all-or-nothing check, then one `UPDATE ... decrement` per item. Shortage -> 422 and rollback.
8. **Lines 154-156.** If `shouldReplenishStock(from,to)` (PAID|PROCESSING->CANCELLED), `replenishStock(tx, order.items)`: one `UPDATE ... increment` per item. The two conditions exclude each other, so at most one runs.
9. **Line 158.** `tx.order.update({ where: { id }, data: { status: to } })`. `updatedAt` is refreshed by Prisma `@updatedAt`. This is an unconditional update keyed only by id. It has no `WHERE status = from` predicate, so it acts as a blind write.
10. **Lines 159-167.** `tx.orderStatusHistory.create({ orderId, fromStatus: from, toStatus: to, changedById: userId, reason: input.reason ?? null })`. `changedAt` defaults to `now()`.
11. **Lines 169-176.** Reload the order with `items.product(id, sku, name)`, `history` ordered by `changedAt asc`, and `customer(id, name, email)`.
12. **Line 177.** Return `refreshed!` (non-null assertion) and commit.

The transaction makes the stock movement, status change and audit record succeed or fail together. A shortage, a failed DB write, or a transaction timeout leaves the order, products and history unchanged. Because the stock side effects come before the status update, a failed debit leaves the order PENDING, as the 422 test confirms.

Isolation against concurrent changes to the same order is weak. Two concurrent `PATCH` requests for PENDING -> PAID on one order can both read `status = PENDING` in step 2, both pass the guards, and both debit stock. The second `UPDATE orders` waits on the first transaction's row lock and then succeeds once the first commits, because the update has no status predicate. The result is a double stock debit and two "PENDING -> PAID" history rows. The same pattern can produce a double replenishment on concurrent cancellations. Section 10 rates this as a high risk.

**Rule workflow**:
```
BEGIN
  SELECT order + items WHERE id            (no lock)
  guard exists / same-state / canTransition
  [PENDING->PAID]       SELECT products; check; UPDATE products SET stock = stock - q (per item)
  [PAID|PROCESSING->CANCELLED] UPDATE products SET stock = stock + q (per item)
  UPDATE orders SET status = to, updatedAt = now() WHERE id
  INSERT order_status_history (orderId, fromStatus, toStatus, changedById, reason, changedAt)
  SELECT order + items.product + history + customer
COMMIT  (or ROLLBACK on any thrown error)
```

---

### Business Rule: BR-09 / BR-10 Status History Auditing

**Overview**:
Every status the order enters is recorded in `order_status_history` (`prisma/schema.prisma:116-131`) with `fromStatus` (nullable), `toStatus`, `changedAt` (default now), `changedById` (FK to users, `ON DELETE RESTRICT`), and `reason` (VarChar 500, nullable). It is indexed on `orderId` and `changedAt`.

**Detailed description**:
At creation (`order.service.ts:106-113`), the order is created with a nested history row `{fromStatus: null, toStatus: PENDING, changedById: userId, reason: 'order created'}` in the same insert. Every order therefore has at least one history entry from the moment it exists, and a null `fromStatus` marks the origin. `tests/orders.test.ts:37-38` checks one history entry with toStatus PENDING.

On each status change (`order.service.ts:159-167`), a new row stores the previous and new status, the authenticated user id from the JWT `sub`, and the optional free-text reason from the request body (max 500 chars, matching the column width). The history is append-only within the module: no code updates or deletes individual history rows. Reads return the history in ascending `changedAt` order (`order.repository.ts:56`, `order.service.ts:117, 173`). `tests/orders.test.ts:80-83` checks that the sequence is `['PENDING','PAID']`.

The audit trail has limits. First, it is not tamper-proof against order deletion: `onDelete: Cascade` on `OrderStatusHistory.order` (`prisma/schema.prisma:125`) removes all history when a PENDING or CANCELLED order is deleted (BR-23), so cancelled orders can disappear with no trace. Second, `changedAt` has the default DateTime precision. Two entries written within the same instant could sort ambiguously, since there is no secondary sort key. Third, users referenced by history cannot be deleted because of the `ON DELETE RESTRICT` foreign key (`migration.sql:125`). That keeps the audit intact but constrains the Users module.

**Rule workflow**:
```
create:        INSERT history(fromStatus=NULL, toStatus=PENDING, changedById=user, reason='order created')
changeStatus:  INSERT history(fromStatus=from, toStatus=to, changedById=user, reason=input.reason|NULL)
read:          history ORDER BY changedAt ASC
delete order:  CASCADE DELETE history
```

---

### Business Rule: BR-11 Order Number Sequence

**Overview**:
Each order gets a unique, human-readable, sequential `orderNumber` such as `ORD-000001`. `reserveOrderNumber(tx)` (`order.service.ts:245-254`) generates it from a single-row counter table `order_number_sequence` (`prisma/schema.prisma:133-138`; `id Int @id @default(1)`, `nextValue Int @default(1)`). `orders.orderNumber` has a unique index (`migration.sql:63`, VarChar(20)).

**Detailed description**:
The function runs `tx.orderNumberSequence.upsert({ where: {id: 1}, create: {id: 1, nextValue: 2}, update: {nextValue: {increment: 1}}, select: {nextValue: true} })`. On the first order ever, the row does not exist, so it is created with `nextValue = 2` and the current number is `2 - 1 = 1`. On later orders, `nextValue` is incremented and the current number is the new `nextValue - 1`. Either way, `nextValue` always holds the number the next order will use. The value is formatted as `ORD-` plus the number zero-padded to 6 digits (`padStart(6,'0')`). After 999999 the number simply grows to 7 or more digits, which still fits VarChar(20). `tests/orders.test.ts:39` checks the format `/^ORD-\d{6}$/`.

The reservation happens inside the creation transaction (line 93), after customer and product validation. If creation fails afterwards, the increment rolls back with it, so the sequence has no gaps under normal operation. The UPDATE takes an exclusive row lock on the single sequence row, held until the transaction commits. All concurrent order creations are serialized on that row from the reservation to commit. This guarantees uniqueness but makes the row a throughput hotspot.

On a fresh database, two concurrent first-order transactions can both find no row and both try to INSERT id=1. One fails with a primary-key violation. Prisma `upsert` against MySQL is not guaranteed to be a native atomic upsert. The error would be P2002, which `errorMiddleware` maps to 409 CONFLICT (`src/middlewares/error.middleware.ts`), so one of the two concurrent first orders fails. The seed script (`prisma/seed.ts`) has its own copy of this logic in a separate transaction. The test setup (`tests/setup.ts:12`) clears the sequence before each test, so numbering restarts at ORD-000001 per test.

**Rule workflow**:
```
inside create transaction, after validations:
  row = UPSERT order_number_sequence(id=1) create{nextValue:2} update{nextValue+=1}
  n = row.nextValue - 1
  orderNumber = "ORD-" + leftpad(n, 6, '0')
  INSERT orders(orderNumber, ...)   # unique index guarantees no duplicates
```

---

### Business Rule: BR-12 / BR-13 / BR-14 Order Item Input Rules and Aggregation

**Overview**:
The request must contain at least one item (`z.array(...).min(1, 'order must contain at least one item')`, `order.schemas.ts:13`). Each item needs a UUID `productId` and a positive integer `quantity` (`order.schemas.ts:6-9`). Duplicate product lines are merged before processing (`aggregateItems`, `order.service.ts:194-202`).

**Detailed description**:
Zod rejects an empty `items` array with 400 VALIDATION_ERROR before the service runs. The service-level check at `order.service.ts:51-53` repeats the rule as defense in depth for callers that bypass the route, but it cannot be reached through HTTP. Quantities must be integers >= 1. There is no upper bound on quantity or number of lines beyond the 1 MB JSON body limit (`src/app.ts:59`).

`aggregateItems` uses a `Map<productId, quantity>` to sum quantities for repeated productIds while keeping first-seen order (Map preserves insertion order). An input of `[{A,2},{B,1},{A,3}]` becomes `[{A,5},{B,1}]`. This guarantees one `OrderItem` per product per order. That matters for the later product existence check (count comparison at line 63), which would wrongly fail with duplicates. It also keeps stock debit and replenishment at one update per product. Clients therefore cannot create two lines for the same product with different quantities, and the stored order will have fewer lines than the request if duplicates were sent.

**Rule workflow**:
```
Zod: items.length >= 1; productId uuid; quantity int > 0
service: items -> Map(productId -> sum(quantity)) -> [{productId, quantity}]
```

---

### Business Rule: BR-15 / BR-16 / BR-17 Customer and Product Eligibility at Creation

**Overview**:
Inside the creation transaction the customer must exist (`order.service.ts:59-60`), every referenced product must exist (`:62-65`), and every product must be active (`:66-73`).

**Detailed description**:
A missing customer raises `NotFoundError('Customer')`: 404, message "Customer not found". The product check compares the number of products found with the number of distinct requested ids. Any missing product raises `NotFoundError('Product')` (404) without saying which id is missing. `tests/orders.test.ts:42-57` checks this case.

Inactive products are collected and reported together: `UnprocessableEntityError('One or more products are inactive', 'INACTIVE_PRODUCT', {skus})`, HTTP 422. The response lists the SKUs of the inactive products so the client can fix the request. The active flag is checked only at creation. Later transitions (including the stock debit) ignore it, as noted in BR-04.

These reads happen inside the transaction, but they do not lock rows. A product could be deactivated, or its price changed, between the read and the commit, and the order would still use the values that were read.

**Rule workflow**:
```
customer = findUnique(customerId)        -> 404 Customer
products = findMany(id in ids)           -> count mismatch -> 404 Product
inactive = products where !active        -> 422 INACTIVE_PRODUCT {skus}
```

---

### Business Rule: BR-18 / BR-19 / BR-20 Server-side Pricing and Discount

**Overview**:
The server computes all monetary values from the catalog: line `unitPriceCents = product.priceCents`, `totalCents = unitPriceCents * quantity`, `subtotalCents = sum(totalCents)`, `totalCents(order) = subtotalCents - discountCents` (`order.service.ts:75-92`). The client can only send `discountCents` (non-negative integer, default 0, `order.schemas.ts:14`), which must not exceed the subtotal (`order.service.ts:87-91`).

**Detailed description**:
Prices are captured on each `OrderItem` at creation (`unitPriceCents`, `totalCents`) and never recalculated. Later catalog price changes do not affect existing orders. This snapshot protects historical totals and invoices. `tests/orders.test.ts:12-40` checks subtotal 5000*3 + 1500*2 = 18000, discount 1000, and total 17000.

All amounts are integers in cents (Prisma `Int`, MySQL INT 32-bit), which avoids floating-point rounding. The code does not guard against overflow. A large quantity times price can exceed 2,147,483,647 cents (about 21.4 million in currency units). JavaScript would compute it correctly, but the DB insert would fail and surface as an unhandled Prisma error (HTTP 500).

The discount is a fixed amount in cents. Percentage discounts, coupons and per-line discounts do not exist. A discount greater than the subtotal raises `ValidationError('Discount cannot exceed subtotal', [{path: 'discountCents', message: 'Discount exceeds subtotal'}])` (400). A discount equal to the subtotal is allowed, giving a zero-total order. The code does not check who may grant discounts. Any authenticated user can apply any discount up to 100%.

**Rule workflow**:
```
for each aggregated item: unit = product.priceCents; line = unit * qty
subtotal = sum(line)
if discount > subtotal -> 400 VALIDATION_ERROR
total = subtotal - discount
```

---

### Business Rule: BR-21 / BR-22 Notes, Reason and Initial State

**Overview**:
`notes` is optional, at most 1000 characters (`order.schemas.ts:15`), and stored as `Text` (null when omitted, `order.service.ts:103`). The status change `reason` is optional, at most 500 characters (`order.schemas.ts:20`), matching `VarChar(500)` (`prisma/schema.prisma:123`). New orders are always created with `status: OrderStatus.PENDING` (`order.service.ts:99`).

**Detailed description**:
The create schema has no `status` field. Zod `z.object` strips unknown keys by default, so a client that sends `status: "PAID"` is ignored silently. This makes PENDING the only entry point into the state machine. Every order must then pass through the transition guards and stock debit, so the stock controls cannot be skipped at creation. The `prisma/seed.ts` script bypasses this by writing statuses directly, and it does not debit stock.

`notes` has no update endpoint. Notes are set only at creation. The reason is purely informational and is stored only in history. No business decision depends on it.

**Rule workflow**:
```
create: status := PENDING (ignores client input), notes := input.notes ?? NULL
changeStatus: history.reason := input.reason ?? NULL
```

---

### Business Rule: BR-23 / BR-24 Order Deletion Constraints

**Overview**:
`OrderService.delete` (`order.service.ts:181-192`) allows hard deletion only when the order is `PENDING` or `CANCELLED`. Otherwise it raises `ConflictError('Order can only be deleted while in PENDING or CANCELLED status', 'INVALID_ORDER_STATE_FOR_DELETE', {status})` (409). Deletion cascades to `order_items` and `order_status_history` (`prisma/schema.prisma:108, 125`).

**Detailed description**:
These two states have no outstanding stock commitment. PENDING never debited stock, and CANCELLED already returned it if needed. Deleting them never leaves inventory inconsistent. Orders in PAID, PROCESSING, SHIPPED or DELIVERED represent committed stock or fulfilled transactions and are protected. `tests/orders.test.ts:197-218` checks that deleting a PAID order is rejected.

Deletion is a hard delete, with no soft-delete flag. The cascade removes items and the full audit history. The order number is not reused, because the sequence only moves forward, so deleted orders leave gaps in the visible numbering.

The operation is not transactional. The status check (`findById`) and the delete (`deleteById`) are separate statements outside a transaction. A concurrent `PATCH` could move the order from PENDING to PAID between the check and the delete. That would delete a PAID order and lose its stock debit for good (stock stays decremented with no order to replenish it). If the order is deleted concurrently by someone else, Prisma raises P2025, which `errorMiddleware` maps to 404. No role check applies: any authenticated OPERATOR can delete.

**Rule workflow**:
```
order = findById(id)                     -> 404 if null
if status not in {PENDING, CANCELLED}    -> 409 INVALID_ORDER_STATE_FOR_DELETE {status}
DELETE orders WHERE id                    -> CASCADE order_items, order_status_history
204
```

---

### Business Rule: BR-25 / BR-26 Listing, Pagination and Filters

**Overview**:
`GET /orders` accepts `page` (int >= 1, default 1), `pageSize` (int 1..100, default 20), `status` (enum), `customerId` (uuid), `from` and `to` (dates, coerced) (`order.schemas.ts:23-30`). Results are ordered by `createdAt desc` and returned with the pagination metadata `{page, pageSize, total, totalPages}`.

**Detailed description**:
`OrderRepository.buildWhere` (`order.repository.ts:21-31`) adds only the filters that are present. The `createdAt` range is inclusive (`gte from`, `lte to`). `z.coerce.date()` parses `to=2026-01-31` as midnight UTC, so orders later that day are excluded. The schema does not check that `from <= to`. An inverted range simply returns nothing. Filters combine with AND.

The list and the count run in a batch `$transaction([...])` (`order.repository.ts:35-43`), so `total` matches the page under concurrent inserts. The list returns bare `Order` rows without items, customer or history. Clients need `GET /orders/:id` for details. Indexes on `status`, `customerId` and `createdAt` (`prisma/schema.prisma:92-94`) support the filters and sort individually. There is no composite index for combined filters. `tests/orders.test.ts:163-195` checks the status filter and `pagination.total`.

The list does not restrict by user. Every authenticated user sees all orders.

**Rule workflow**:
```
where = {} + status? + customerId? + createdAt{gte from?, lte to?}
[items, total] = $transaction([findMany(where, orderBy createdAt desc, skip, take), count(where)])
return { data: items, pagination: { page, pageSize, total, totalPages = ceil(total/pageSize) } }
```

---

### Business Rule: BR-27 / BR-28 Authentication and Actor Attribution

**Overview**:
The router applies `authenticate` to every route (`order.routes.ts:14`). Controllers that write data check `req.user` again (`order.controller.ts:30, 40`) and pass `req.user.id` as `createdById` or `changedById`.

**Detailed description**:
`authenticate` (`src/middlewares/auth.middleware.ts`) needs `Authorization: Bearer <jwt>` signed with `env.JWT_SECRET`. On failure it returns 401 UNAUTHORIZED. The JWT `sub` becomes `req.user.id`. The module never accepts actor identity from the request body, which keeps the audit trail trustworthy as long as the JWT is.

The project has a `requireRole` middleware, but only the Users module uses it (`src/modules/users/user.routes.ts:15`). In the OrdersModule, ADMIN and OPERATOR have identical rights: they can create, list, read, change the status of, and delete any order, and apply any discount. No ownership or tenancy filtering exists. Because the controller's `req.user` checks come after `authenticate`, they are redundant at runtime (defensive only).

The JWT is verified for signature and expiry, but the user is not looked up in the DB. If a user is deleted while the token is still valid, the history insert fails on the `changedById` foreign key (P2003). `errorMiddleware` does not map P2003, so the client gets a 500.

**Rule workflow**:
```
authenticate -> req.user = {id: sub, email, role}
controller: if !req.user -> 401
service: createdById / changedById = req.user.id
```

---

### Business Rule: BR-29 Order Read Model

**Overview**:
`OrderWithRelations` (`order.repository.ts:12-16`) is the detailed shape returned by get, create and changeStatus: the order fields, plus `items[]` each with `product {id, sku, name}`, plus `history[]` ascending, plus `customer {id, name, email}`.

**Detailed description**:
The same `include` block appears three times: `order.repository.ts:50-58`, `order.service.ts:115-119`, and `order.service.ts:170-175`. The responses look the same today, but each copy must be kept in sync by hand. The product projection leaves out price and stock, so clients see the snapshot price on the item, not the current catalog price. The customer projection includes email (PII), which is exposed to every authenticated user. The address and document are not exposed.

**Rule workflow**:
```
include: items -> product(id, sku, name); history orderBy changedAt asc; customer(id, name, email)
```

---

### Business Rule: BR-30 Unused State Machine Helpers

**Overview**:
`allowedTransitions(from)` and `isTerminal(status)` are exported from `order.status.ts:16-22` but nothing references them (confirmed by a project-wide search).

**Detailed description**:
They make it possible to expose allowed next actions or to recognize terminal states, for example to skip notifications or block edits. No current endpoint returns the allowed transitions, and no code uses terminal status for decisions. The delete rule (BR-23) hard-codes `PENDING`/`CANCELLED` and does not use `isTerminal`. `STOCK_DEBIT_TRANSITION` is exported but used only inside the same file. Confidence that these are intended extension points: Medium (not documented).

**Rule workflow**:
```
allowedTransitions(s) = transitions[s]
isTerminal(s) = transitions[s].length == 0     # true for DELIVERED, CANCELLED
```

---

## 4. Component Structure

```
src/modules/orders/
├── order.routes.ts       # 27 lines. Express Router factory; applies authenticate + Zod validate per route
├── order.controller.ts   # 56 lines. OrderController: HTTP adapter (status codes, req.user check, next(err))
├── order.schemas.ts      # 34 lines. Zod schemas: id param, create body, status body, list query + inferred types
├── order.service.ts      # 255 lines. OrderService: business logic, transactions, stock, history, order number
├── order.status.ts       # 37 lines. Pure state machine: transition table, canTransition, stock side-effect predicates
└── order.repository.ts   # 69 lines. OrderRepository: list with filters/pagination, find by id (with relations), delete
```

Supporting artifacts outside the folder:

```
prisma/schema.prisma                      # Order, OrderItem, OrderStatusHistory, OrderNumberSequence, OrderStatus enum
prisma/migrations/20260519182739_init/    # DDL: indexes, FKs (CASCADE on items/history, RESTRICT on product/customer/user)
prisma/seed.ts                            # Seeds 26 orders in all statuses with synthetic history (no stock debit)
src/app.ts:42-44                          # Composition root: OrderRepository(prisma) -> OrderService(repo, prisma) -> OrderController
src/routes/index.ts:28                    # Mount point /api/v1/orders
src/middlewares/auth.middleware.ts        # authenticate
src/middlewares/validate.middleware.ts    # validate (Zod)
src/middlewares/error.middleware.ts       # AppError / Zod / Prisma P2002, P2025 -> JSON
src/shared/errors/http-errors.ts          # NotFound, Conflict, Validation, UnprocessableEntity, InvalidStatusTransition, InsufficientStock
src/shared/http/response.ts               # paginated()
tests/orders.test.ts                      # 8 integration tests
tests/setup.ts, tests/helpers/factories.ts
```

Layer responsibilities:

- **Routes:** routing, authentication and validation middleware only.
- **Controller:** request/response translation. No business logic beyond the `req.user` check.
- **Service:** all business rules. Uses the repository for simple reads and deletes, and the `PrismaClient` directly for transactional, multi-aggregate operations (create, changeStatus).
- **Status:** pure functions, no I/O. The most unit-testable part.
- **Repository:** query construction for orders only. It does not cover create or status updates, which live in the service.

---

## 5. Dependency Analysis

```
Internal Dependencies (compile-time imports):
order.routes.ts      -> middlewares/auth.middleware (authenticate)
                     -> middlewares/validate.middleware (validate)
                     -> order.schemas (createOrderSchema, listOrdersQuerySchema, orderIdParamSchema, updateOrderStatusSchema)
                     -> order.controller (type only)
order.controller.ts  -> order.service (type only)
                     -> order.schemas (type ListOrdersQuery)
                     -> shared/errors (UnauthorizedError)
order.service.ts     -> order.repository (types OrderRepository, OrderWithRelations)
                     -> order.schemas (types)
                     -> order.status (canTransition, shouldDebitStock, shouldReplenishStock)
                     -> shared/errors (ConflictError, InsufficientStockError, InvalidStatusTransitionError,
                                       NotFoundError, UnprocessableEntityError, ValidationError)
                     -> shared/http/response (paginated, PaginatedResponse)
                     -> @prisma/client (OrderStatus enum, Prisma, PrismaClient types)
order.repository.ts  -> @prisma/client (types only)
order.status.ts      -> @prisma/client (OrderStatus enum)
order.schemas.ts     -> zod, @prisma/client (OrderStatus enum)

Runtime call chain:
Router -> authenticate -> validate -> OrderController -> OrderService
OrderService -> OrderRepository -> PrismaClient (list, getById, delete)
OrderService -> PrismaClient.$transaction -> tx.customer / tx.product / tx.order / tx.orderStatusHistory /
                tx.orderNumberSequence (create, changeStatus)
OrderService -> order.status (pure)

Cross-module data dependencies (via Prisma, not via module services):
OrderService reads Customer (customers module table)
OrderService reads and writes Product.stockQuantity, reads Product.active/priceCents/sku (products module table)
Order/OrderStatusHistory reference User (users module table) via createdById / changedById

Inbound:
src/app.ts (composition), src/routes/index.ts (mount), tests/orders.test.ts (HTTP)

External Dependencies (package.json):
- @prisma/client 5.22.0 - ORM / data access, interactive transactions
- prisma 5.22.0 (dev) - schema, migrations
- MySQL (docker-compose) - persistence
- express 4.21.1 - HTTP routing
- zod 3.23.8 - input validation and coercion
- jsonwebtoken 9.0.2 - via authenticate middleware
- vitest 2.1.4, supertest 7.0.0 (dev) - tests
```

The OrdersModule does not call `ProductService` or `CustomerService`. It reaches into the `product` and `customer` tables directly through the transaction client. This bypasses any rules those modules enforce, and it couples the OrdersModule to their schemas.

---

## 6. Afferent and Efferent Coupling

Counts are distinct types/modules (Ca = number of units that depend on it; Ce = number of units it depends on). Prisma generated types are counted as one unit, `@prisma/client`.

| Component | Afferent Coupling (Ca) | Efferent Coupling (Ce) | Critical |
|-----------|------------------------|------------------------|----------|
| OrderService (order.service.ts) | 2 (OrderController, app.ts) | 6 (OrderRepository, order.schemas, order.status, shared/errors, shared/http/response, @prisma/client) | High |
| order.status (canTransition, shouldDebitStock, shouldReplenishStock, allowedTransitions, isTerminal) | 1 (OrderService) | 1 (@prisma/client OrderStatus) | High |
| OrderRepository (order.repository.ts) | 2 (OrderService, app.ts) | 1 (@prisma/client) | Medium |
| order.schemas (Zod schemas + types) | 3 (order.routes, OrderController, OrderService) | 2 (zod, @prisma/client) | Medium |
| OrderController (order.controller.ts) | 3 (order.routes, routes/index.ts, app.ts) | 3 (OrderService, order.schemas, shared/errors) | Low |
| buildOrderRouter (order.routes.ts) | 1 (routes/index.ts) | 4 (auth.middleware, validate.middleware, order.schemas, OrderController) | Low |
| OrderWithRelations / OrderListFilters (types) | 1 (OrderService) | 1 (@prisma/client) | Low |

Notes:
- OrderService is the most critical unit: highest efferent coupling, plus hidden runtime coupling to the Customer, Product, User and OrderNumberSequence tables through `tx`.
- order.status has low coupling but high criticality. A change to its table changes stock and lifecycle behavior across the system.
- Module-level coupling: the OrdersModule depends on the shared kernel (errors, http, middlewares) and on the data of 3 other modules (Customers, Products, Users). Only the composition root and the API router depend on it.

---

## 7. Endpoints

All endpoints are mounted under `/api/v1/orders` (`src/app.ts:67`, `src/routes/index.ts:28`) and require `Authorization: Bearer <JWT>`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/v1/orders | GET | List orders, paginated, with filters `page`, `pageSize`, `status`, `customerId`, `from`, `to`. 200 `{data: Order[], pagination}` |
| /api/v1/orders/{id} | GET | Get an order with items (product id/sku/name), history and customer. 200 / 404 |
| /api/v1/orders | POST | Create an order in PENDING. Body `{customerId, items[{productId, quantity}], discountCents?, notes?}`. 201 / 400 / 404 / 422 |
| /api/v1/orders/{id}/status | PATCH | Change status. Body `{toStatus, reason?}`. 200 / 400 / 404 / 409 / 422 |
| /api/v1/orders/{id} | DELETE | Delete an order (only PENDING or CANCELLED). 204 / 404 / 409 |

Error codes produced by the module:

| HTTP | Code | Source |
|------|------|--------|
| 400 | VALIDATION_ERROR | Zod validation (validate.middleware.ts); discount > subtotal (order.service.ts:88); empty items (order.service.ts:52) |
| 401 | UNAUTHORIZED | authenticate; controller `req.user` check |
| 404 | NOT_FOUND | Order / Customer / Product not found; Prisma P2025 |
| 409 | INVALID_STATUS_TRANSITION | same status, or transition not allowed |
| 409 | INVALID_ORDER_STATE_FOR_DELETE | delete outside PENDING/CANCELLED |
| 409 | CONFLICT | Prisma P2002 (for example a concurrent first sequence insert) |
| 422 | INACTIVE_PRODUCT | inactive product at creation (details.skus) |
| 422 | INSUFFICIENT_STOCK | PENDING -> PAID without stock (details.unavailable[]) |
| 500 | INTERNAL_SERVER_ERROR | unmapped errors (for example P2003 FK, INT overflow, transaction timeout) |

---

## 8. Integration Points

| Integration | Type | Purpose | Protocol | Data Format | Error Handling |
|-------------|------|---------|----------|-------------|----------------|
| MySQL via Prisma Client 5.22.0 | Database | Persist orders, items, history, sequence; read customers; read/write products | Prisma engine / MySQL wire | SQL rows <-> typed objects | Interactive transactions roll back on exception; P2002 -> 409, P2025 -> 404 in errorMiddleware; others -> 500 logged with requestId |
| Products module data (`products` table) | Internal (shared DB) | Price snapshot, active check, stock debit/replenish | In-process Prisma `tx.product` | Prisma model | Shortage -> 422 INSUFFICIENT_STOCK; missing -> 404 |
| Customers module data (`customers` table) | Internal (shared DB) | Customer existence check; customer projection in responses | In-process Prisma `tx.customer` | Prisma model | Missing -> 404 |
| Users module data (`users` table) | Internal (shared DB) | FK for createdById / changedById | FK constraint | UUID | FK violation not mapped -> 500 |
| Auth (JWT) | Internal middleware | Authenticate caller, supply actor id | HTTP header Bearer | JWT (HS, env.JWT_SECRET) | 401 UNAUTHORIZED |
| Validation (Zod) | Internal middleware | Parse and coerce body, query, params | In-process | JSON | 400 VALIDATION_ERROR with details[{path, message}] |
| HTTP clients | Inbound | REST API | HTTP/JSON | JSON | Standard error envelope `{error:{code, message, details?}}` |
| Event bus / webhooks / notifications | None | Not implemented | - | - | No outbound side effects on order lifecycle events. README describes a planned webhook notification feature |

---

## 9. Design Patterns & Architecture

| Pattern | Implementation | Location | Purpose |
|---------|----------------|----------|---------|
| Layered Architecture | Routes -> Controller -> Service -> Repository | src/modules/orders/* | Separation of HTTP, business and data access concerns |
| Feature Module (Vertical Slice) | All order files in one folder | src/modules/orders/ | High cohesion per business capability |
| Table-driven State Machine | `transitions` Record + `canTransition` | order.status.ts:3-14 | Declarative, exhaustive lifecycle rules |
| Predicate Functions for Side Effects | `shouldDebitStock`, `shouldReplenishStock` | order.status.ts:29-37 | Separate the decision from the effect; pure and testable |
| Unit of Work / Transaction Script | `prisma.$transaction(async tx => ...)` | order.service.ts:58-123, 131-178 | Atomic multi-entity changes |
| Repository Pattern (partial) | OrderRepository | order.repository.ts | Query encapsulation for reads and delete; writes stay in the service |
| Constructor Dependency Injection (manual) | `new OrderService(orderRepository, prisma)` | src/app.ts:42-44 | Composition root, testability |
| Router Factory | `buildOrderRouter(controller)` | order.routes.ts:12 | Inject controller into routes |
| Schema Validation at the Edge | Zod schemas + `validate` middleware | order.schemas.ts; order.routes.ts:16-24 | Reject invalid input early; coercion and defaults |
| Error Hierarchy + Central Error Handler | AppError subclasses; `errorMiddleware` | src/shared/errors; src/middlewares/error.middleware.ts | Consistent error envelope and status codes |
| Snapshot Pattern | unitPriceCents / totalCents copied onto OrderItem | order.service.ts:75-84 | Historical price integrity |
| Audit Log (append-only) | OrderStatusHistory inserts | order.service.ts:106-113, 159-167 | Traceability of lifecycle changes |
| Sequence Table (counter row) | `order_number_sequence` upsert/increment | order.service.ts:245-254 | Gap-free human-readable identifiers |
| Money as Integer Cents | `*Cents` Int fields | prisma/schema.prisma; order.service.ts | Avoid floating-point errors |
| Pagination DTO | `paginated()` | src/shared/http/response.ts | Uniform list response |

Architectural decisions observed:
- Stock is committed at payment, not at order creation (BR-07).
- The service bypasses other modules' services and works directly on their tables inside one transaction, which favors atomicity over module encapsulation.
- Hard delete with cascade, not soft delete.
- Default isolation, with no explicit locking or optimistic concurrency.

---

## 10. Technical Debt & Risks

| Risk Level | Component Area | Issue | Impact |
|------------|----------------|-------|--------|
| High | OrderService.changeStatus (order.service.ts:132-158) | Status is read without a lock, and `UPDATE orders SET status` has no `WHERE status = from` predicate and no version column. Concurrent identical transitions both succeed | Double stock debit on concurrent PENDING->PAID; double replenishment on concurrent cancels; duplicate history rows |
| High | OrderService.debitStock (order.service.ts:208-230) | Availability check uses a plain non-locking SELECT, then a decrement; no DB CHECK on stockQuantity >= 0 | Overselling: stock can go negative when different orders for the same product are paid concurrently |
| High | OrderService.delete (order.service.ts:181-192) | Check-then-delete outside a transaction | A concurrent PENDING->PAID can be followed by deletion of the now-PAID order, so stock debit is lost and never replenished |
| Medium | Audit trail (prisma/schema.prisma:125) | History is cascade-deleted with the order; hard delete | Loss of audit evidence for deleted orders (including CANCELLED ones) |
| Medium | Authorization (order.routes.ts:14) | No role checks; OPERATOR can delete orders, apply unlimited discounts, and run every transition | Privilege and fraud exposure; no separation of duties |
| Medium | Order number (order.service.ts:245-254) | Single-row hot lock held until commit; first-row creation race can raise P2002 | Serialized order creation throughput; rare 409 on an empty DB |
| Medium | Cross-module coupling | Direct writes to `product.stockQuantity` and reads of customers/products bypass ProductService/CustomerService | Rules added in those modules are not applied; schema changes ripple into orders |
| Medium | Error mapping (error.middleware.ts) | P2003 (FK), INT overflow and transaction timeouts (P2028) are not mapped | Users get 500 for foreseeable conditions (deleted user with a valid token, huge quantity) |
| Medium | Monetary bounds (order.schemas.ts:8, 14) | No upper bound on quantity or line count; MySQL INT 32-bit | Overflow -> 500; very large orders inflate transaction duration |
| Medium | Seed data (prisma/seed.ts) | Seeded PAID/PROCESSING orders were never debited from stock | Cancelling seeded orders inflates stock (dev/demo data inconsistency) |
| Low | Duplicated include blocks (order.repository.ts:50-58; order.service.ts:115-119, 170-175) | Same relation projection repeated 3 times | Response shape drift risk |
| Low | Dead code (order.status.ts:16-22; order.service.ts:51-53) | `allowedTransitions`, `isTerminal` unused; unreachable empty-items check | Maintenance noise |
| Low | Non-null assertions (order.controller.ts:21, 41, 50; order.service.ts:76, 177) | `!` on params and refreshed order | Hides possible nulls; type-safety erosion |
| Low | Idempotency | Retrying a successful transition returns 409 | Client retry logic must treat 409 "already in status" as success |
| Low | List query (order.repository.ts:25-29; order.schemas.ts:28-29) | No `from <= to` check; date-only `to` treated as midnight UTC | Surprising empty or partial results |
| Low | N+1 writes (order.service.ts:225-230, 237-242) | One UPDATE per item, sequentially | Longer transactions for large orders (Prisma 5s default timeout) |
| Low | Active flag only at creation (order.service.ts:66-73 vs 204-231) | Deactivated products can still be paid and debited | Possible business inconsistency (confidence: unclear whether intended) |
| Low | Missing domain events | No hook or event on status change | The planned webhook feature has no extension point; it will need changes inside the transaction |
| Low | PII exposure (order.repository.ts:57) | Customer email returned to all authenticated users | Data-minimization concern |

---

## 11. Test Coverage Analysis

Test infrastructure:
- Runner: Vitest 2.1.4 (`vitest.config.ts`), `include: tests/**/*.test.ts`, single fork, no file parallelism, 30s timeouts.
- `tests/setup.ts` connects Prisma and, before each test, truncates `order_status_history`, `order_items`, `orders`, `order_number_sequence`, `products`, `customers`, `users`.
- `tests/helpers/factories.ts` provides `getTestApp` (real `buildApp({prisma})`), `createTestUser`, `loginAndGetToken` (real `/auth/login`), `createTestCustomer`, `createTestProduct`, `bootstrapAuthenticatedUser`.
- Style: black-box HTTP integration tests via supertest against a real MySQL database. No mocks or stubs.
- No coverage tool (for example `@vitest/coverage-v8`) is configured, so the coverage figures below are estimates from tracing the code paths each test runs.

Test inventory (`tests/orders.test.ts`):

| # | Test | Lines | Rules covered |
|---|------|-------|---------------|
| 1 | creates an order in PENDING status and computes totals on the server | 12-40 | BR-10, BR-11 (format), BR-18, BR-19, BR-20 (valid), BR-22, BR-29 |
| 2 | rejects an order with non-existent product | 42-57 | BR-16 |
| 3 | transitions PENDING -> PAID and decrements stock | 59-87 | BR-01, BR-04, BR-08, BR-09 |
| 4 | returns 409 on invalid status transition (PENDING -> SHIPPED) | 89-107 | BR-03 |
| 5 | returns 422 when transitioning PENDING -> PAID without enough stock | 109-132 | BR-05, BR-07, BR-08 (rollback) |
| 6 | replenishes stock when going PAID -> CANCELLED | 134-161 | BR-06 (PAID path) |
| 7 | lists orders filtered by status | 163-195 | BR-25, BR-26 (status filter only) |
| 8 | refuses to delete an order that is not PENDING or CANCELLED | 197-218 | BR-23 (negative path) |

Coverage by unit:

| Component | Unit Tests | Integration Tests | Coverage (estimated, line-level) | Test Quality |
|-----------|------------|-------------------|----------------------------------|--------------|
| order.status.ts | 0 | 4 (indirect: tests 3, 4, 5, 6) | ~80% (allowedTransitions, isTerminal never run; 4 of 10 valid edges run) | No table-driven test of all 36 from/to pairs; PROCESSING->CANCELLED replenish and PENDING->CANCELLED no-replenish untested |
| OrderService.create | 0 | 3 (tests 1, 2 plus setup in others) | ~75% | Good total assertions; missing: customer 404, inactive product 422, discount > subtotal 400, duplicate-item aggregation, notes |
| OrderService.changeStatus | 0 | 4 (tests 3-6) | ~85% | Checks stock side effects in the DB and history order; missing: same-status 409, order 404, terminal-state transitions, full lifecycle to DELIVERED |
| OrderService.debitStock | 0 | 2 (tests 3, 5) | ~90% | Checks rollback; missing: multi-item partial shortage report |
| OrderService.replenishStock | 0 | 1 (test 6) | 100% lines | Single-item only |
| OrderService.reserveOrderNumber | 0 | indirect (test 1 format) | 100% lines (create branch only per test, because setup truncates) | Increment branch and sequential values never asserted; no concurrency test |
| OrderService.delete | 0 | 1 (test 8) | ~60% | Success path (204, cascade) and 404 untested; CANCELLED delete untested |
| OrderService.list / OrderRepository.list | 0 | 1 (test 7) | ~60% | customerId, from/to filters, pagination math (page 2, totalPages), pageSize bounds untested |
| OrderService.getById / findByIdWithRelations | 0 | 0 direct (relations seen via create/changeStatus responses) | ~0% direct | GET /orders/:id never called; 404 untested |
| OrderController | 0 | indirect via all tests | ~85% | 401 paths untested in the orders suite (`tests/auth.test.ts` covers auth generally) |
| order.schemas.ts | 0 | indirect | Partial | No tests for invalid UUIDs, quantity 0, negative discount, empty items 400, oversized reason/notes, invalid enum |
| order.routes.ts | 0 | indirect | All 5 routes registered; 4 of 5 called | GET /:id never called |

Gaps and risks:
- No tests for concurrency (double payment, concurrent stock debit, sequence race). These are the highest-risk areas in Section 10.
- No pure unit tests for `order.status.ts`, even though it is a pure module.
- No authorization tests on order routes (missing or invalid token -> 401).
- No test checks that history is cascade-deleted, or that `changedById` and `reason` are stored.
- The tests share one global app instance and a real DB with per-test truncation, which keeps them isolated but needs a running MySQL (docker-compose).

---

*Report generated by Component Deep Analyzer. Analysis-only; no project files were modified.*
