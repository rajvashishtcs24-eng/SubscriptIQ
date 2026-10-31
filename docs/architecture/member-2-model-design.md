# `subscriptiq_billing` — Data Model Design
**Owner:** Member 2
**Target:** Odoo 19 Community Edition
**Revision:** 3 — six-state billing ledger; ack fields; proportional allocation formula; reversal policy; `brightloop_base` dependency noted
**Status:** Architecture design — awaiting team review. No implementation code.

---

## 0. Model Overview

| Model | Type | Changes in Rev 3 |
|---|---|---|
| `subscriptiq.billing.run` | Custom | `ack_failure_count` field added |
| `subscriptiq.billing.run.item` | Custom | `ack_failed` state added |
| `subscriptiq.billing.ledger` | Custom | **Six states; ack fields added** |
| `subscriptiq.discount.rule` | Custom | No change |
| `subscriptiq.discount.reservation` | Custom | No change |
| `account.move` | Extended | No change |

No custom accounting ledger. No duplication of `account.move` functionality.

---

## 1. `subscriptiq.billing.run`

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | Char | Yes | Sequence | Auto-generated: `BRUN/2026/001` |
| `state` | Selection | Yes | `draft` | `draft`, `running`, `done`, `partial`, `failed` |
| `run_date` | Datetime | Yes | `now()` | UTC timestamp when run was initiated |
| `billing_date` | Date | Yes | — | The "as of" date used to fetch eligible subscriptions |
| `triggered_by` | Selection | Yes | `cron` | `cron`, `manual` |
| `triggered_by_user_id` | Many2one → `res.users` | No | — | Populated for manual runs only |
| `subscription_count` | Integer | Yes | 0 | Total subscriptions targeted |
| `invoice_count` | Integer | Computed | — | Items where state=success |
| `failure_count` | Integer | Computed | — | Items where state=failed (invoice failures only) |
| `skipped_count` | Integer | Computed | — | Items where state=skipped |
| `ack_failure_count` | Integer | Computed | — | **New Rev 3** — items where state=ack_failed |
| `total_billed` | Monetary | Computed | — | Sum of `amount_total` of all posted invoices in this run |
| `currency_id` | Many2one → `res.currency` | Yes | Company currency | Monetary field context |
| `item_ids` | One2many → `subscriptiq.billing.run.item` | — | — | All per-subscription results |
| `notes` | Text | No | — | Admin notes |
| `error_message` | Text | No | — | Top-level error (stage 2 failures only) |
| `duration_seconds` | Integer | Computed | — | `(run_end_datetime − run_date).seconds` |
| `run_end_datetime` | Datetime | No | — | Set when run finalises |

### State machine

```
draft ──▶ running ──▶ done
                 ├──▶ partial   (some invoice failures or ack failures)
                 └──▶ failed    (stage 2 failure — no invoices created)
```

### Constraints

```sql
CREATE UNIQUE INDEX uq_billing_run_running
    ON subscriptiq_billing_run (state)
    WHERE state = 'running';
```

### Indexes

```sql
CREATE INDEX idx_billing_run_state ON subscriptiq_billing_run (state);
CREATE INDEX idx_billing_run_billing_date ON subscriptiq_billing_run (billing_date);
```

---

## 2. `subscriptiq.billing.run.item`

One record per subscription processed per billing run. Audit trail — not retried directly (ledger governs retries).

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `billing_run_id` | Many2one → `subscriptiq.billing.run` | Yes | — | Parent run |
| `billing_ledger_id` | Many2one → `subscriptiq.billing.ledger` | No | — | Associated ledger |
| `subscription_id` | Integer | Yes | — | Subscription ID from Member 1 |
| `partner_id` | Many2one → `res.partner` | Yes | — | Customer |
| `state` | Selection | Yes | `pending` | `pending`, `success`, `failed`, `skipped`, `ack_failed` |
| `skip_reason` | Selection | No | — | `already_billed`, `inactive`, `payload_error`, `concurrent` |
| `invoice_id` | Many2one → `account.move` | No | — | Invoice created (populated on success or ack_failed) |
| `error_message` | Text | No | — | Invoice or validation error |
| `ack_error_message` | Text | No | — | **New Rev 3** — acknowledgement failure details |
| `billing_period_start` | Date | No | — | Traceability |
| `billing_period_end` | Date | No | — | Traceability |
| `processing_duration_ms` | Integer | No | — | Wall-clock time |

### Constraints

```sql
ALTER TABLE subscriptiq_billing_run_item
    ADD CONSTRAINT uq_run_item_sub_per_run
    UNIQUE (billing_run_id, subscription_id);
```

### Indexes

```sql
CREATE INDEX idx_run_item_state ON subscriptiq_billing_run_item (state);
CREATE INDEX idx_run_item_subscription ON subscriptiq_billing_run_item (subscription_id);
```

---

## 3. `subscriptiq.billing.ledger`

The **central idempotency anchor and state machine**. One record per `(subscription_id, billing_period_start, billing_period_end)`.

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | Char | Yes | Computed | `SUB-{id}/{period_start}` |
| `subscription_id` | Integer | Yes | — | Subscription ID from Member 1 |
| `partner_id` | Many2one → `res.partner` | Yes | — | Customer (denormalized for reporting) |
| `billing_period_start` | Date | Yes | — | Inclusive period start |
| `billing_period_end` | Date | Yes | — | Inclusive period end |
| `billing_frequency` | Selection | Yes | — | `daily`, `weekly`, `monthly`, `yearly` |
| `state` | Selection | Yes | `pending` | `pending`, `in_progress`, `failed`, `ack_pending`, `ack_failed`, `succeeded` |
| `invoice_id` | Many2one → `account.move` | No | — | Populated after stage 3.10 commit |
| `draft_invoice_id` | Many2one → `account.move` | No | — | Holds draft during posting; cleared on success or rollback |
| `discount_reservation_id` | Many2one → `subscriptiq.discount.reservation` | No | — | Active reservation |
| `retry_count` | Integer | Yes | 0 | Invoice retry attempts (pre-posting failures only) |
| `max_retries` | Integer | Yes | 3 | Copied from config at creation |
| `next_retry_at` | Datetime | No | — | Earliest time invoice retry cron may attempt |
| `last_error_message` | Text | No | — | Error from most recent invoice-stage failure |
| `first_attempted_at` | Datetime | No | — | Timestamp of first billing attempt |
| `succeeded_at` | Datetime | No | — | Timestamp of stage 3.10 savepoint commit |
| `billing_run_id` | Many2one → `subscriptiq.billing.run` | No | — | Run that committed the invoice |
| `ack_retry_count` | Integer | Yes | 0 | **New Rev 3** — acknowledgement retry attempts |
| `ack_max_retries` | Integer | Yes | 5 | **New Rev 3** — higher than invoice max (ack failures should resolve quickly) |
| `ack_retry_at` | Datetime | No | — | **New Rev 3** — earliest time ack retry cron may attempt |
| `ack_error_message` | Text | No | — | **New Rev 3** — last acknowledgement failure detail |
| `acknowledged_at` | Datetime | No | — | **New Rev 3** — timestamp when Member 1 acknowledged successfully |

### Six-state machine

```
              pending
                 │  engine acquires row lock
                 ▼
           in_progress
            │         │
     (failure)     (stage 3.10 commit)
            │         │
            ▼         ▼
          failed   ack_pending
            │         │       │
      (retry cron) (ack ok) (ack fails)
            │         │       │
            ▼         ▼       ▼
        in_progress succeeded ack_failed
                               │     │
                         (ack retry) (ack retry ok)
                               │         │
                               ▼         ▼
                           ack_failed  succeeded  ← terminal ✅
```

### Transition table

| From | To | Trigger |
|---|---|---|
| `pending` | `in_progress` | Engine SELECT FOR UPDATE row lock |
| `in_progress` | `failed` | Savepoint rollback (invoice not posted) |
| `in_progress` | `failed` | Draft invoice cancelled by admin |
| `in_progress` | `ack_pending` | Stage 3.10 savepoint commit — invoice posted |
| `ack_pending` | `succeeded` | `register_billing_success` succeeds |
| `ack_pending` | `ack_failed` | `register_billing_success` raises |
| `ack_failed` | `succeeded` | Ack retry succeeds |
| `ack_failed` | `ack_failed` | Ack retry fails again |
| `failed` | `in_progress` | Invoice retry cron |
| `succeeded` | — | **Terminal. No transitions.** |

### Constraints

```sql
-- Core idempotency constraint
ALTER TABLE subscriptiq_billing_ledger
    ADD CONSTRAINT uq_ledger_sub_period
    UNIQUE (subscription_id, billing_period_start, billing_period_end);
```

### Indexes

```sql
CREATE INDEX idx_ledger_state ON subscriptiq_billing_ledger (state);
CREATE INDEX idx_ledger_subscription ON subscriptiq_billing_ledger (subscription_id);
CREATE INDEX idx_ledger_period ON subscriptiq_billing_ledger (billing_period_start, billing_period_end);

-- Invoice retry cron
CREATE INDEX idx_ledger_invoice_retry ON subscriptiq_billing_ledger (next_retry_at)
    WHERE state = 'failed' AND next_retry_at IS NOT NULL;

-- Ack retry cron
CREATE INDEX idx_ledger_ack_retry ON subscriptiq_billing_ledger (ack_retry_at)
    WHERE state IN ('ack_pending', 'ack_failed') AND ack_retry_at IS NOT NULL;
```

### Cancelled-draft behavior (T-21)

1. `draft_invoice_id` cleared on ledger.
2. Active `DiscountReservation` → `released`.
3. `ledger.state` → `failed`.
4. `ledger.retry_count` NOT incremented (admin cancel ≠ system error).
5. `ledger.next_retry_at` set for retry cron pickup.
6. Next attempt reuses this same ledger (T-22).

### Posted-invoice reversal behavior (T-24, T-25)

1. Reversal via `account.move._reverse_moves()` creates `out_refund`. Historical records preserved (T-25).
2. `ledger.state` remains `succeeded`. Period is NOT made billable again (T-24).
3. `discount_rule.current_uses` is NOT decremented (T-20).
4. Rebilling after reversal requires explicit admin action with `group_billing_manager` (Q-9 — process to be confirmed).

---

## 4. `subscriptiq.discount.rule`

No changes from Rev 2. Owned exclusively by Member 2.

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | Char | Yes | — | Human-readable label |
| `code` | Char | No | — | Optional promo code (unique when set) |
| `description` | Text | No | — | Internal notes |
| `discount_type` | Selection | Yes | `percentage` | `percentage`, `fixed` |
| `discount_value` | Float | Yes | — | Percent (0–100) or fixed monetary amount |
| `currency_id` | Many2one → `res.currency` | Conditional | Company currency | Required when `discount_type=fixed` |
| `priority` | Integer | Yes | 10 | Lower number = higher priority |
| `date_start` | Date | No | — | Validity start (inclusive). Null = open |
| `date_end` | Date | No | — | Validity end (inclusive). Null = open |
| `max_uses` | Integer | Yes | 0 | 0 = unlimited |
| `current_uses` | Integer | Yes | 0 | Incremented atomically after successful posting only |
| `min_qty` | Float | Yes | 0.0 | Minimum total quantity. 0 = no minimum |
| `min_amount_untaxed` | Monetary | Yes | 0.0 | Minimum pre-tax amount. 0 = no minimum |
| `min_amount_currency_id` | Many2one → `res.currency` | Yes | Company currency | Currency for min_amount comparison |
| `product_ids` | Many2many → `product.product` | No | — | Empty = applies to all products |
| `subscription_id_filter` | Char | No | — | Optional restriction to specific subscription IDs |
| `active` | Boolean | Yes | True | Odoo native archiving |

### Constraints

```sql
CREATE UNIQUE INDEX uq_discount_code
    ON subscriptiq_discount_rule (code)
    WHERE code IS NOT NULL AND code != '';

ALTER TABLE subscriptiq_discount_rule
    ADD CONSTRAINT chk_discount_value_positive CHECK (discount_value > 0);

ALTER TABLE subscriptiq_discount_rule
    ADD CONSTRAINT chk_percentage_max
    CHECK (discount_type != 'percentage' OR discount_value <= 100);

ALTER TABLE subscriptiq_discount_rule
    ADD CONSTRAINT chk_date_order
    CHECK (date_start IS NULL OR date_end IS NULL OR date_end >= date_start);

ALTER TABLE subscriptiq_discount_rule
    ADD CONSTRAINT chk_max_uses_nonneg CHECK (max_uses >= 0);
```

### Indexes

```sql
CREATE INDEX idx_discount_active_dates ON subscriptiq_discount_rule (active, date_start, date_end);
CREATE INDEX idx_discount_priority ON subscriptiq_discount_rule (priority) WHERE active = TRUE;
```

### No-stacking policy (T-14, confirmed)

Only one rule applies per billing event. `DiscountService` selects the highest-priority eligible rule.

---

## 5. `subscriptiq.discount.reservation`

No structural changes from Rev 2. Snapshot values confirmed important for audit trail.

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `discount_rule_id` | Many2one → `subscriptiq.discount.rule` | Yes | — | Reserved rule |
| `billing_ledger_id` | Many2one → `subscriptiq.billing.ledger` | Yes | — | Owning ledger |
| `state` | Selection | Yes | `reserved` | `reserved`, `consumed`, `released` |
| `reserved_at` | Datetime | Yes | `now()` | When reservation was created |
| `consumed_at` | Datetime | No | — | After successful posting |
| `released_at` | Datetime | No | — | On failure or draft cancellation |
| `discount_type` | Selection | Yes | — | Snapshot of rule type at reservation time |
| `discount_value` | Float | Yes | — | Snapshot of rule value at reservation time |
| `currency_id` | Many2one → `res.currency` | No | — | Snapshot for fixed-type rules |

### State machine

```
reserved ──▶ consumed   (stage 3.9 — after action_post() succeeds)
         └──▶ released  (savepoint rollback OR draft invoice cancellation)
```

> **On savepoint rollback:** The `reserved` record itself is rolled back with the savepoint. No explicit `released` write is needed in that path. An explicit `released` write is required **only** when an admin cancels a draft invoice outside the billing cron (T-21).

> **Cancellation of a posted invoice (T-20):** The reservation for the original invoice is already `consumed`. It is NOT changed back to `released`. `current_uses` is NOT decremented.

### Constraints

```sql
CREATE UNIQUE INDEX uq_reservation_ledger_active
    ON subscriptiq_discount_reservation (billing_ledger_id)
    WHERE state = 'reserved';
```

### Indexes

```sql
CREATE INDEX idx_reservation_rule ON subscriptiq_discount_reservation (discount_rule_id);
CREATE INDEX idx_reservation_ledger ON subscriptiq_discount_reservation (billing_ledger_id);
CREATE INDEX idx_reservation_state ON subscriptiq_discount_reservation (state);
```

---

## 6. Discount Allocation — Full Specification

### 6.1 Percentage discount

```
account.move.line.discount = reservation.discount_value  (percentage)
Odoo computes:
  price_subtotal = price_unit × quantity × (1 − discount / 100)
  taxes computed on price_subtotal by Odoo (_compute_tax_line_ids)
price_unit is NEVER modified (T-13)
```

### 6.2 Fixed discount — proportional allocation algorithm

```
Inputs:
  D          = reservation.discount_value  (in reservation.currency_id)
  lines      = invoice lines that pass the product_ids filter
  currency   = invoice currency

Step 1 — Identify eligible lines:
  eligible_lines = [l for l in invoice_lines if
                    not rule.product_ids OR l.product_id in rule.product_ids]

Step 2 — Compute eligible subtotals:
  S_i = l.price_unit × l.quantity  for each eligible line l  (pre-discount)
  S_total = Σ S_i

Step 3 — Guard: zero-total check:
  if S_total == 0:
    release reservation (non-applicable)
    proceed without discount
    return

Step 4 — Guard: discount exceeds total (⚠️ Q-7/Q-8 — accountant decision):
  if D > S_total:
    [UNRESOLVED — do not implement until Q-7/Q-8 are answered]
    Document as an edge case requiring explicit policy decision

Step 5 — Compute raw allocation per eligible line:
  raw_i = D × (S_i / S_total)

Step 6 — Round each allocation to invoice currency precision:
  alloc_i = currency.round(raw_i)         [use res.currency.round() — never Python round()]

Step 7 — Compute rounding remainder:
  allocated_total = Σ alloc_i
  remainder = currency.round(D) − allocated_total

Step 8 — Allocate remainder (⚠️ Q-8 — accountant to confirm):
  OPTION A (proposed default): add to the first eligible line
  alloc[0] += remainder

Step 9 — Convert allocation to percentage for each eligible line:
  discount_pct_i = (alloc_i / S_i) × 100    [float arithmetic — Odoo will round on display]
  l.discount = discount_pct_i                [native account.move.line.discount field]

Step 10 — Tax computation:
  Odoo _compute_tax_line_ids fires on create()
  Taxes applied to discounted subtotal of each line independently
  [Tax behavior on fixed discounts may vary by tax type — confirm Q-7]

Step 11 — Ineligible lines:
  l.discount = 0.0 for lines not in eligible_lines (unchanged — no discount applied)
```

### 6.3 Tax-inclusive price edge case (⚠️ Requires confirmation — Q-7)

If an eligible line's product has `account.tax.price_include = True`, the `price_unit` already includes tax. Applying the proportional discount reduces the inclusive price, which changes both the base and the tax amount. Odoo handles this extraction automatically, but the accounting treatment should be confirmed by the team's accountant before implementation.

### 6.4 Zero-value lines

Lines where `price_unit × quantity = 0` are excluded from `eligible_lines` automatically (their contribution to `S_total` is 0 and would cause division by zero in Step 5). No discount is applied to zero-value lines.

---

## 7. `account.move` Extension

`account.move` extended via `_inherit`. All native functionality preserved unchanged.

### Added fields

| Field | Type | Index | Description |
|---|---|---|---|
| `x_subscription_id` | Integer | Yes | Subscription ID from Member 1 |
| `x_billing_period_start` | Date | Yes | Start of billed period |
| `x_billing_period_end` | Date | Yes | End of billed period |
| `x_billing_run_id` | Many2one → `subscriptiq.billing.run` | Yes | Run that created this invoice |
| `x_billing_ledger_id` | Many2one → `subscriptiq.billing.ledger` | Yes | Ledger for this invoice |

### Idempotency constraint (last-resort)

```sql
CREATE UNIQUE INDEX uq_move_subscription_period
    ON account_move (x_subscription_id, x_billing_period_start, x_billing_period_end)
    WHERE move_type = 'out_invoice'
      AND state != 'cancel';
```

Excludes cancelled invoices and `out_refund` (credit notes). The billing ledger is the primary guard; this index is the database-level backstop.

### Indexes

```sql
CREATE INDEX idx_move_subscription_id ON account_move (x_subscription_id)
    WHERE x_subscription_id IS NOT NULL;

CREATE INDEX idx_move_billing_period ON account_move (x_billing_period_start, x_billing_period_end)
    WHERE move_type = 'out_invoice';

CREATE INDEX idx_move_billing_run ON account_move (x_billing_run_id)
    WHERE x_billing_run_id IS NOT NULL;

CREATE INDEX idx_move_billing_ledger ON account_move (x_billing_ledger_id)
    WHERE x_billing_ledger_id IS NOT NULL;
```

### Native fields used (read-only — never manipulated by billing)

| Field | Used For |
|---|---|
| `move_type` | Set to `'out_invoice'` on creation |
| `partner_id` | From Member 1 payload |
| `currency_id` | From Member 1 payload |
| `fiscal_position_id` | From Member 1 payload (Q-4) |
| `payment_term_id` | From Member 1 payload (Q-4) |
| `invoice_date` | Set to billing run `billing_date` |
| `invoice_date_due` | Computed by Odoo from payment term |
| `invoice_line_ids` | Built from subscription lines + discount |
| `amount_untaxed` | Read for min_amount discount check |
| `amount_total` | Read for billing run totals |
| `amount_residual` | Read for outstanding balance reporting |
| `payment_state` | Read for overdue detection |
| `state` | Transitions via `action_post()` / `button_cancel()` / `_reverse_moves()` only |

---

## 8. Model Relationship Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                   subscriptiq.billing.run                          │
│  name, state, run_date, billing_date                               │
│  invoice_count, failure_count, ack_failure_count, total_billed     │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ One2many (item_ids)
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                subscriptiq.billing.run.item                        │
│  subscription_id, partner_id                                       │
│  state: pending|success|failed|skipped|ack_failed                  │
│  error_message, ack_error_message                                  │
└────────┬──────────────────────────────────────┬────────────────────┘
         │ Many2one (billing_ledger_id)          │ Many2one (invoice_id)
         ▼                                       ▼
┌──────────────────────────────┐  ┌─────────────────────────────────┐
│  subscriptiq.billing.ledger  │  │       account.move              │
│                              │  │    [NATIVE + EXTENDED]          │
│  subscription_id             │  │                                 │
│  billing_period_start        │  │  x_subscription_id             │
│  billing_period_end          │  │  x_billing_period_start        │
│  state (6 states)            │  │  x_billing_period_end          │
│  retry_count / next_retry_at │  │  x_billing_run_id              │
│  ack_retry_count             │  │  x_billing_ledger_id ─────────▶│
│  ack_retry_at                │  │                                 │
│  invoice_id ────────────────▶│  │  [NATIVE]                       │
│  draft_invoice_id            │  │  partner_id, currency_id        │
│  discount_reservation_id ────┼─▶│  invoice_line_ids              │
└──────────────────────────────┘  │  amount_residual               │
         │ One2many                │  payment_state                  │
         ▼                         └─────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│             subscriptiq.discount.reservation                       │
│  state: reserved → consumed | released                             │
│  discount_type, discount_value, currency_id  (snapshot)           │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ Many2one (discount_rule_id)
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│               subscriptiq.discount.rule                            │
│  code, discount_type, discount_value, currency_id                 │
│  priority, date_start, date_end                                   │
│  max_uses, current_uses (atomic)                                  │
│  min_qty, min_amount_untaxed                                      │
│  product_ids (Many2many → product.product)                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## 9. Security Access (ir.model.access.csv)

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
# Billing Run
access_billing_run_mgr,billing_run_mgr,model_subscriptiq_billing_run,subscriptiq_billing.group_billing_manager,1,1,1,1
access_billing_run_usr,billing_run_usr,model_subscriptiq_billing_run,subscriptiq_billing.group_billing_user,1,0,0,0
# Billing Run Item
access_run_item_mgr,run_item_mgr,model_subscriptiq_billing_run_item,subscriptiq_billing.group_billing_manager,1,1,1,1
access_run_item_usr,run_item_usr,model_subscriptiq_billing_run_item,subscriptiq_billing.group_billing_user,1,0,0,0
# Billing Ledger
access_ledger_mgr,ledger_mgr,model_subscriptiq_billing_ledger,subscriptiq_billing.group_billing_manager,1,1,1,1
access_ledger_usr,ledger_usr,model_subscriptiq_billing_ledger,subscriptiq_billing.group_billing_user,1,0,0,0
# Discount Rule
access_discount_rule_mgr,discount_rule_mgr,model_subscriptiq_discount_rule,subscriptiq_billing.group_billing_manager,1,1,1,1
access_discount_rule_usr,discount_rule_usr,model_subscriptiq_discount_rule,subscriptiq_billing.group_billing_user,1,0,0,0
# Discount Reservation
access_reservation_mgr,reservation_mgr,model_subscriptiq_discount_reservation,subscriptiq_billing.group_billing_manager,1,1,1,1
access_reservation_usr,reservation_usr,model_subscriptiq_discount_reservation,subscriptiq_billing.group_billing_user,1,0,0,0
# Cross-addon read (pending Q-5, Q-6 — placeholder group)
# access_billing_run_portal,billing_run_portal,model_subscriptiq_billing_run,subscriptiq_portal.group_portal_admin,1,0,0,0
# access_ledger_portal,ledger_portal,model_subscriptiq_billing_ledger,subscriptiq_portal.group_portal_admin,1,0,0,0
```

> Cross-addon access lines are commented out until Member 3 confirms group XML IDs (Q-5) and dependency direction is agreed (Q-6).

---

## 10. Billing Configuration (via `res.config.settings`)

| Config Field | Type | Default | Description |
|---|---|---|---|
| `billing_max_retries` | Integer | 3 | Max invoice retry attempts per failed ledger |
| `billing_retry_base_hours` | Integer | 4 | Base delay hours for invoice retry exponential backoff |
| `billing_ack_max_retries` | Integer | 5 | **New Rev 3** — max acknowledgement retry attempts |
| `billing_ack_retry_base_hours` | Integer | 2 | **New Rev 3** — base delay for ack retry backoff |
| `billing_batch_size` | Integer | 100 | Subscriptions committed per transaction |
| `billing_journal_id` | Many2one → `account.journal` | Customer Invoices | Default billing journal |
| `billing_pg_lock_key` | Integer | 1001 | PostgreSQL advisory lock key |

---

## 11. Pricing and Tax Calculation Order

```
1. UNIT PRICE       From Member 1's payload
                    price_unit is pricelist-resolved — Member 1's responsibility
                    Member 2 NEVER modifies price_unit (T-13)

2. QUANTITY         From Member 1's payload

3. LINE SUBTOTAL    quantity × price_unit  (raw, before any discount)

4a. PERCENTAGE      Set account.move.line.discount = reservation.discount_value%
    DISCOUNT        Odoo: price_subtotal = price_unit × qty × (1 − discount/100)
                    Taxes fire on discounted amount

4b. FIXED           Compute proportional alloc_i per eligible line (§6)
    DISCOUNT        Set account.move.line.discount = discount_pct_i per line
                    Odoo: price_subtotal = price_unit × qty × (1 − discount_pct_i/100)
                    Taxes fire on each line's discounted amount independently

5. TAX              Odoo _compute_tax_line_ids fires on ORM create()
                    Respects price_include on account.tax
                    Member 2 NEVER computes tax amounts manually

6. INVOICE TOTAL    Odoo computes amount_untaxed, amount_tax, amount_total natively

7. ROUNDING         res.currency.round() used by Odoo internally
                    Member 2 NEVER calls Python round() on monetary values
```

---

## 12. Billing Period Service — Design Specification

`PeriodService` — plain Python utility class, no Odoo model, no database table.

```python
# DESIGN ONLY — method signatures, no implementation

class PeriodService:

    @staticmethod
    def compute_period(
        frequency: str,         # 'daily' | 'weekly' | 'monthly' | 'yearly'
        anchor_date: date,      # Subscription's current next_billing_date
        day_anchor: int,        # Original billing day (1–31)
    ) -> tuple[date, date, date]:
        """Returns: (period_start, period_end, next_billing_date)"""

    @staticmethod
    def advance_monthly(current: date, day_anchor: int) -> date: ...

    @staticmethod
    def advance_yearly(current: date, day_anchor: int) -> date: ...

    @staticmethod
    def last_day_of_month(year: int, month: int) -> int: ...

    @staticmethod
    def is_leap_year(year: int) -> bool: ...
```

---

*Document revision 3 — six-state billing ledger; ack fields and retry; proportional fixed-discount allocation; reversal policy. No code implemented. Awaiting team review.*
