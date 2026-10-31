# `subscriptiq_billing` — Billing Architecture
**Owner:** Member 2
**Target:** Odoo 19 Community Edition
**Environment:** Docker Compose + PostgreSQL 16
**Revision:** 3 — incorporates `brightloop_base` decision, fixed-discount proportional allocation, acknowledgement-recovery separation, posted-invoice reversal policy
**Status:** Architecture final — awaiting team review before implementation. No implementation code.

---

## 0. Environment Verification

| Item | Confirmed Value |
|---|---|
| Git branch | `feature/member-2-billing` ✅ |
| Odoo edition | 19 Community — no Enterprise modules |
| Development environment | Docker Compose |
| Database | PostgreSQL 16 |
| Addon name | `subscriptiq_billing` |
| Ownership | Member 2 |

---

## 1. Decision Register

### 1.1 Confirmed team decisions

| # | Decision | Source |
|---|---|---|
| T-1 | Odoo 19 Community Edition | Team |
| T-2 | Docker Compose + PostgreSQL 16 for all members | Team |
| T-3 | Three business addons: `subscriptiq_subscription`, `subscriptiq_billing`, `subscriptiq_portal` | Team |
| T-4 | `brightloop_base` is approved as a minimal shared addon for groups only — no business logic | **Team — new Rev 3** |
| T-5 | No `sale.subscription` (Enterprise-only) — all recurring logic is custom | Team |
| T-6 | Member 2 owns all discount logic: rules, eligibility, application, usage limits | Team |
| T-7 | `subscriptiq_billing` declares `subscriptiq_subscription` in its `depends` list — dependency flows in one direction only | Member 1 confirmed |
| T-8 | Subscriptions use a standalone `subscriptiq.subscription` model — NOT `sale.order` | Member 1 confirmed |
| T-9 | Member 1 uses a standalone subscription-line model (not `sale.order.line`) | Member 1 confirmed |
| T-10 | `sale.order` is extended by Member 1 for quotation-to-subscription conversion only — billing never touches `sale.order` | Member 1 confirmed |
| T-11 | Member 1 exposes public ORM methods on `subscriptiq.subscription` — no Python imports between addons, no raw SQL across boundaries | Member 1 confirmed |
| T-12 | No circular dependencies between any addons | Member 1 confirmed |
| T-13 | Agreed subscription prices must never be modified — discounts affect only invoice calculation | Member 1 confirmed |
| T-14 | No discount stacking — at most one discount rule applies per billing event | Team |
| T-15 | Percentage discounts apply to eligible invoice-line amounts before tax calculation | **Team — new Rev 3** |
| T-16 | Fixed discounts are distributed proportionally across eligible invoice lines | **Team — new Rev 3** |
| T-17 | Discount usage is reserved atomically before invoice creation | Team |
| T-18 | Discount usage is consumed only after successful invoice posting | Team |
| T-19 | Failed invoice creation releases the discount reservation | **Team — new Rev 3** |
| T-20 | Cancellation of a posted invoice does NOT automatically restore discount usage | **Team — new Rev 3** |
| T-21 | A cancelled draft invoice releases its reservation and makes the ledger retryable | Team |
| T-22 | A retry reuses the existing billing ledger record — never creates a second record for the same period | Team |
| T-23 | If acknowledgement (next-billing-date advance) fails after successful posting: preserve the invoice, preserve succeeded status, retry only the acknowledgement — never regenerate the invoice | **Team — new Rev 3** |
| T-24 | Reversing a posted invoice must use an explicit reversal process (`_reverse_moves()`); it does not automatically make the period billable again | **Team — new Rev 3** |
| T-25 | Historical invoice and discount usage records must be preserved through reversals | **Team — new Rev 3** |

### 1.2 Proposed by Member 2 — pending team review

| # | Proposal | Requires |
|---|---|---|
| P-1 | Model names, field names and service class names as documented | Team sign-off |
| P-2 | ORM method names for Member 1's public interface | Member 1 agreement |
| P-3 | Billing ledger with separate `ack_pending` and `ack_failed` states for acknowledgement recovery | Team review |
| P-4 | `brightloop_base` group XML IDs (proposed but not final) | **Member 3 must confirm** |
| P-5 | Batch size and retry configuration defaults | Team |
| P-6 | Savepoint-per-subscription isolation strategy | Team |
| P-7 | PostgreSQL advisory lock key value (1001) | Team — reserve in project namespace |
| P-8 | Rounding-remainder allocation strategy for proportional fixed discounts | **Accountant confirmation** |

### 1.3 Open questions requiring confirmation

| # | Question | Blocking? | Asks |
|---|---|---|---|
| Q-1 | Exact ORM method names Member 1 will publish on `subscriptiq.subscription` | **Yes** | Member 1 |
| Q-2 | Exact field name for `next_billing_date` on `subscriptiq.subscription` | **Yes** | Member 1 |
| Q-3 | What lifecycle statuses does `subscriptiq.subscription` use, and which are billable? | **Yes** | Member 1 |
| Q-4 | Do subscriptions carry `fiscal_position_id` and `payment_term_id`, or are these on `res.partner`? | Medium | Member 1 |
| Q-5 | Exact `brightloop_base` group XML IDs and group inheritance from Odoo base groups | **Yes — blocks `brightloop_base` creation** | Member 3 |
| Q-6 | Does `subscriptiq_portal` need a direct `depends` on `subscriptiq_billing`, or will it consume a published interface only? | **Yes — affects dependency graph** | Member 3 |
| Q-7 | Tax treatment of fixed-discount lines: taxed at same rates as the lines being discounted, or tax-free? | Medium | **Accountant** |
| Q-8 | Rounding remainder allocation for proportional fixed discounts: first-line, last-line, or largest-line? | Medium | **Accountant** |
| Q-9 | How should a manual reversal of a posted billing invoice be recorded — as a one-off event or as a signal to rebill? | Medium | **Accountant + Member 1** |
| Q-10 | Agreed UTC server timezone for the Docker Compose environment | Low | Team |

---

## 2. Addon Overview

```
                    subscriptiq_subscription
                         [Member 1]
                    standalone sub model,
                    public ORM interface
                             │
                       (depends — ↓ only)
                             │
                    subscriptiq_billing
                         [Member 2]
                    billing engine, discounts
                    ledger, runs, invoices
                             │
                       (depends — ↓ only)
                             │
                    subscriptiq_portal
                         [Member 3]
                    portal, analytics, admin

    All three addons depend on:  brightloop_base  (shared groups only)
```

**Key distinction — dependency direction vs data flow:**

| Direction | Meaning |
|---|---|
| Addon dependency (`depends`) | Installation order; `billing` is installed after `subscription`; `portal` is installed after `billing`. Dependency flows **downward** only. |
| Business data flow | Subscriptions data flows **upward** from Member 1 to Member 2 via ORM method calls. Invoice and payment data flows **upward** from Member 2 to Member 3 via read access. |

The dependency arrow and the data-flow arrow point in **opposite directions**. This is normal and correct in Odoo — the consuming addon declares the dependency on the providing addon.

---

## 3. Addon File Structure

```
subscriptiq_billing/
│
├── __init__.py
├── __manifest__.py
│
├── models/
│   ├── __init__.py
│   ├── billing_run.py                  # subscriptiq.billing.run
│   ├── billing_run_item.py             # subscriptiq.billing.run.item
│   ├── billing_ledger.py               # subscriptiq.billing.ledger  (idempotency anchor)
│   ├── discount_rule.py                # subscriptiq.discount.rule
│   ├── discount_reservation.py         # subscriptiq.discount.reservation
│   └── account_move_extension.py       # extends account.move
│
├── services/
│   ├── __init__.py
│   ├── billing_engine.py               # Orchestrates the full billing workflow
│   ├── discount_service.py             # Eligibility, allocation, reservation lifecycle
│   ├── period_service.py               # Billing period boundaries and date arithmetic
│   └── acknowledgement_service.py      # Acknowledgement retry — separate from invoice retry
│
├── wizards/
│   ├── __init__.py
│   ├── billing_run_wizard.py           # Manual billing run trigger
│   └── ack_retry_wizard.py             # Manual acknowledgement retry trigger
│
├── views/
│   ├── billing_run_views.xml
│   ├── billing_run_item_views.xml
│   ├── billing_ledger_views.xml
│   ├── discount_rule_views.xml
│   ├── discount_reservation_views.xml
│   ├── account_move_views.xml
│   └── menu_actions.xml
│
├── data/
│   ├── ir_cron_billing.xml             # Primary daily billing cron
│   ├── ir_cron_invoice_retry.xml       # Retry cron for failed ledger entries (pre-posting)
│   ├── ir_cron_ack_retry.xml           # Retry cron for acknowledgement failures (post-posting)
│   └── ir_sequence_billing_run.xml
│
├── report/
│   ├── billing_run_report.xml
│   └── billing_run_report_template.xml
│
├── security/
│   ├── ir.model.access.csv
│   └── subscriptiq_billing_groups.xml
│
└── tests/
    ├── __init__.py
    ├── common.py
    ├── test_billing_engine.py
    ├── test_billing_run.py
    ├── test_billing_ledger.py
    ├── test_discount_service.py
    ├── test_discount_allocation.py     # Proportional fixed-discount allocation tests
    ├── test_discount_reservation.py
    ├── test_period_service.py
    ├── test_idempotency.py
    ├── test_account_integration.py
    ├── test_acknowledgement.py         # Acknowledgement failure and retry tests
    └── test_member1_interface.py
```

---

## 4. `__manifest__.py` Design

```python
# subscriptiq_billing/__manifest__.py
# ARCHITECTURE ONLY — no implementation code

{
    'name': 'SubscriptIQ Billing',
    'version': '19.0.1.0.0',
    'summary': 'Recurring billing, invoice generation, discount engine and payment tracking',
    'author': 'SubscriptIQ Team — Member 2',
    'category': 'Accounting/Billing',
    'license': 'LGPL-3',

    'depends': [
        'account',                    # account.move, account.tax, account.payment
        'product',                    # product.product — invoice lines
        'mail',                       # mail.thread, mail.activity.mixin — BillingRun chatter
        'base_setup',                 # res.config.settings — billing configuration
        'subscriptiq_subscription',   # Member 1's addon — ORM interface
        # 'brightloop_base',          # PROPOSED — add when team approves and Member 3 confirms group XML IDs (Q-5)
    ],

    # sale is NOT in depends.
    # Member 1 confirmed subscriptions are standalone (not sale.order).
    # Billing does not touch sale.order at any point.

    'data': [
        'security/subscriptiq_billing_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_billing_run.xml',
        'data/ir_cron_billing.xml',
        'data/ir_cron_invoice_retry.xml',
        'data/ir_cron_ack_retry.xml',
        'views/discount_rule_views.xml',
        'views/discount_reservation_views.xml',
        'views/billing_ledger_views.xml',
        'views/billing_run_views.xml',
        'views/billing_run_item_views.xml',
        'views/account_move_views.xml',
        'views/menu_actions.xml',
        'report/billing_run_report.xml',
        'report/billing_run_report_template.xml',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,
}
```

### Dependency justification

| Dependency | Reason | Removable? |
|---|---|---|
| `account` | Core — all invoice, tax, payment, reconciliation models | No |
| `product` | `product.product` required to build invoice lines | No |
| `mail` | Chatter and activity scheduling on `BillingRun` | Optional |
| `base_setup` | `res.config.settings` for billing configuration | Optional |
| `subscriptiq_subscription` | **Confirmed** — billing calls Member 1's ORM methods | No |
| `brightloop_base` | **Proposed** — shared groups; add after Q-5 is confirmed | Pending Q-5 |
| `sale` | **Not included** — Member 1 confirmed subscriptions are standalone | Removed |

---

## 5. `brightloop_base` — Shared Base Addon (APPROVED, PENDING DETAIL)

### Status

The team has agreed to introduce `brightloop_base`. It will contain **only shared groups** — no business logic, no models, no billing or subscription code.

### Proposed contents

| Proposed Group XML ID | Proposed Name | Purpose |
|---|---|---|
| `brightloop_base.group_subscriptiq_admin` | SubscriptIQ Administrator | Full system access across all three addons |
| `brightloop_base.group_subscriptiq_staff` | SubscriptIQ Staff | Internal operational user |
| `brightloop_base.group_subscriptiq_customer` | SubscriptIQ Customer | Portal customer |

### Dependency impact

If `brightloop_base` is approved and group XML IDs are confirmed:
- All three addons (`subscriptiq_subscription`, `subscriptiq_billing`, `subscriptiq_portal`) add `brightloop_base` to their `depends` list.
- `brightloop_base` depends only on `base` (Odoo core) — nothing else.
- No circular dependency is introduced.

### Proposed full dependency graph (including `brightloop_base`)

```
                      [Odoo 19 Community Core]
                                │
          ┌─────────────────────┼──────────────────┐
          │                     │                  │
      [account]             [product]          [mail] [base_setup]
          │                                         │
          └─────────────────────────────────────────┘
                                │
                        [brightloop_base]          ← shared groups only
                        (pending Q-5)
                                │
              ┌─────────────────┴────────────────────┐
              │                                      │
 [subscriptiq_subscription]            (portal will also depend here)
       [Member 1]
              │
        (depends ↓)
              │
    [subscriptiq_billing]              ← Member 2 (this addon)
       [Member 2]
              │
        (depends ↓)      ← Q-6: confirm whether portal needs direct dependency
              │
    [subscriptiq_portal]               ← Member 3
       [Member 3]
```

> **Q-6 open:** Does `subscriptiq_portal` need a direct `depends` on `subscriptiq_billing`? If portal only reads `account.move` (native) and uses ORM-accessible custom fields, a direct dependency on `subscriptiq_billing` is appropriate and avoids field resolution problems. If portal consumes only native accounting models, it may not need the direct dependency. This must be confirmed with Member 3.

### What `brightloop_base` must NOT contain

- Subscription models or fields.
- Billing models or fields.
- Invoice logic.
- Portal controllers.
- Any module-specific business rules.

---

## 6. Security Groups

### Member 2's own groups (defined in `subscriptiq_billing/security/subscriptiq_billing_groups.xml`)

| Group XML ID | Name | Inherits | Permissions |
|---|---|---|---|
| `subscriptiq_billing.group_billing_manager` | Billing Manager | Proposed: `brightloop_base.group_subscriptiq_staff` (pending Q-5) | Full CRUD on all billing models; triggers manual runs; manages discounts |
| `subscriptiq_billing.group_billing_user` | Billing User | Proposed: `brightloop_base.group_subscriptiq_staff` (pending Q-5) | Read-only on billing runs, ledger, discount rules |

Until `brightloop_base` is confirmed, these groups inherit from `base.group_user` as a development placeholder.

---

## 7. Billing Workflow — 16-Stage Lifecycle

The workflow now separates invoice-posting stages from the acknowledgement stage. Acknowledgement failure no longer rolls back a successfully posted invoice.

```
┌──────────────────────────────────────────────────────────────────────┐
│  BILLING ORCHESTRATION                                               │
│  BillingEngine.execute_run() — called by ir.cron or manual wizard    │
└──────────────────────────────────────────────────────────────────────┘

STAGE 1 ── INITIATE RUN
  ├─ Acquire PostgreSQL advisory lock  →  abort if already locked
  ├─ Create BillingRun (state: draft → running)
  ├─ Record run_date (UTC), billing_date, triggered_by
  └─ FAILURE: release lock; no BillingRun persisted

STAGE 2 ── FETCH ELIGIBLE SUBSCRIPTIONS
  ├─ Call: env['subscriptiq.subscription'].get_subscriptions_due_for_billing(billing_date)
  ├─ Returns: list[int] of subscription IDs
  ├─ FAILURE: BillingRun.state=failed; release lock; stop
  └─ EMPTY: BillingRun.state=done; release lock; stop

STAGE 3 ── PER-SUBSCRIPTION LOOP  [each iteration in its own SAVEPOINT]
  │
  ├─ STAGE 3.1 ── LOAD AND VALIDATE PAYLOAD
  │     ├─ Call: env['subscriptiq.subscription'].get_billing_payload(subscription_id)
  │     ├─ Validate: all required fields present, types correct, at least one line
  │     └─ FAILURE → ROLLBACK SAVEPOINT → ledger.state=failed → BillingRunItem(state=failed)
  │
  ├─ STAGE 3.2 ── COMPUTE BILLING PERIOD
  │     ├─ PeriodService.compute_period(frequency, next_billing_date, day_anchor)
  │     ├─ Returns: (period_start, period_end, computed_next_billing_date)
  │     └─ FAILURE → ROLLBACK SAVEPOINT → BillingRunItem(state=failed)
  │
  ├─ STAGE 3.3 ── FIND OR CREATE BILLING LEDGER
  │     ├─ SELECT-FOR-UPDATE on ledger WHERE (subscription_id, period_start, period_end)
  │     ├─ NOT EXISTS      → CREATE ledger(state=pending)          [first attempt]
  │     ├─ state=succeeded → SKIP → BillingRunItem(state=skipped, reason=already_billed)
  │     ├─ state=ack_pending or state=ack_failed → SKIP to STAGE 3.11 (acknowledgement-only retry)
  │     ├─ state=pending or state=failed → REUSE record             [invoice retry — T-22]
  │     └─ state=processing → SKIP → BillingRunItem(state=skipped, reason=concurrent)
  │
  ├─ STAGE 3.4 ── MARK LEDGER IN-PROGRESS
  │     ├─ ledger.state = processing
  │     └─ FAILURE → ROLLBACK SAVEPOINT → BillingRunItem(state=skipped, reason=concurrent)
  │
  ├─ STAGE 3.5 ── EVALUATE AND RESERVE DISCOUNT
  │     ├─ DiscountService.find_eligible_rule(partner_id, product_ids, quantities, amounts, date)
  │     ├─ No stacking — at most one rule (T-14)
  │     ├─ If eligible: SELECT FOR UPDATE on discount_rule → check remaining uses
  │     ├─ CREATE DiscountReservation(state=reserved, snapshot type/value/currency)
  │     └─ FAILURE or limit exceeded → no reservation; billing continues without discount
  │
  ├─ STAGE 3.6 ── BUILD INVOICE LINES WITH DISCOUNT
  │     ├─ For each subscription line from payload:
  │     │     - product_id, name, quantity, price_unit, tax_ids, uom_id — all from payload
  │     │     - price_unit is NEVER modified (T-13)
  │     ├─ If reservation.discount_type = 'percentage':
  │     │     - Set account.move.line.discount = reservation.discount_value%
  │     │     - Odoo computes: price_subtotal = price_unit × qty × (1 − discount/100)
  │     └─ If reservation.discount_type = 'fixed':
  │           - DiscountService.allocate_fixed_discount(lines, fixed_amount, currency)
  │           - See §9 for proportional allocation formula
  │           - Each eligible line receives discount field representing its allocated share
  │           - OR: negative line approach (Q-7 — accountant to confirm preferred method)
  │
  ├─ STAGE 3.7 ── CREATE INVOICE
  │     ├─ account.move.create({ move_type='out_invoice', partner_id, currency_id,
  │     │                         fiscal_position_id, payment_term_id, invoice_date,
  │     │                         invoice_line_ids, x_subscription_id,
  │     │                         x_billing_period_start, x_billing_period_end,
  │     │                         x_billing_run_id, x_billing_ledger_id })
  │     ├─ Odoo ORM triggers _compute_tax_line_ids — taxes computed natively
  │     ├─ ledger.draft_invoice_id = new invoice.id
  │     └─ FAILURE → ROLLBACK SAVEPOINT → release reservation → ledger.state=failed
  │
  ├─ STAGE 3.8 ── POST INVOICE
  │     ├─ account.move.action_post()
  │     ├─ Odoo creates journal entries, payment_state='not_paid'
  │     └─ FAILURE → ROLLBACK SAVEPOINT → release reservation → ledger.state=failed
  │
  ├─ STAGE 3.9 ── CONSUME DISCOUNT RESERVATION
  │     ├─ Only reached after action_post() succeeds
  │     ├─ reservation.state = consumed; reservation.consumed_at = now()
  │     ├─ discount_rule.current_uses += 1  (atomic within this transaction)
  │     └─ FAILURE → ROLLBACK SAVEPOINT (invoice rolled back too) → ledger.state=failed
  │
  ├─ STAGE 3.10 ── COMMIT SAVEPOINT (invoice is now durably posted)
  │     ├─ ledger.state = ack_pending          ← NEW in Rev 3
  │     ├─ ledger.invoice_id = posted invoice
  │     ├─ ledger.draft_invoice_id = cleared
  │     ├─ ledger.succeeded_at = now()
  │     └─ RELEASE savepoint — invoice is committed to the database
  │
  ├─ STAGE 3.11 ── ACKNOWLEDGE MEMBER 1  [outside the invoice savepoint]
  │     ├─ Call: env['subscriptiq.subscription'].register_billing_success(
  │     │           subscription_id, invoice_id, computed_next_billing_date)
  │     ├─ Member 1 advances next_billing_date within the same DB transaction
  │     ├─ FAILURE:
  │     │     - Invoice is already committed — it is NOT rolled back (T-23)
  │     │     - ledger.state = ack_failed
  │     │     - ledger.ack_error_message = error
  │     │     - ledger.ack_retry_at = now() + ack_retry_delay
  │     │     - BillingRunItem(state=ack_failed) — separate from billing failure
  │     └─ SUCCESS: ledger.state = succeeded; BillingRunItem(state=success)
  │
  └─ Continue to next subscription

STAGE 4 ── BATCH COMMIT
  ├─ Every N subscriptions (batch_size): env.cr.commit()
  └─ Reduces memory and rollback scope

STAGE 5 ── FINALISE RUN
  ├─ Aggregate: invoice_count, failure_count, skipped_count, ack_failure_count, total_billed
  ├─ Set BillingRun.state = done | partial | failed
  ├─ Record run_end_datetime
  ├─ Send chatter notification
  └─ Release advisory lock
```

### Stage failure behavior table

| Stage | Failure scope | Rollback | Recovery |
|---|---|---|---|
| 1: Initiate | Entire run | No run created | Manual trigger / next cron |
| 2: Fetch | Entire run | `BillingRun.state=failed` | Manual re-trigger |
| 3.1–3.4: Payload / period / ledger | Single subscription | Savepoint rollback | Invoice retry cron |
| 3.5: Discount reserve | Non-fatal | No rollback — billing proceeds without discount | — |
| 3.6–3.9: Build / create / post / consume | Single subscription | Savepoint rollback + reservation released | Invoice retry cron; `ledger.state=failed` |
| 3.10: Commit savepoint | Single subscription | Entire savepoint rolled back | Invoice retry cron |
| 3.11: Acknowledge | **Invoice preserved** | **No rollback** | Ack retry cron; `ledger.state=ack_failed` |
| 4: Batch commit | Prior batches preserved | Last batch may be incomplete | Resume from last commit |
| 5: Finalise | Non-critical | Counts not updated | Manual correction |

---

## 8. Billing Ledger State Machine (Extended)

The ledger now has six states to cleanly separate invoice lifecycle from acknowledgement lifecycle.

```
                  ┌──────────┐
                  │ pending  │  ← created on first attempt
                  └────┬─────┘
                       │ engine acquires row lock
                  ┌────▼──────────┐
                  │  processing  │  ← row-locked during active processing
                  └──┬────────┬───┘
                     │        │
         ┌───────────▼─┐    ┌─▼────────────────┐
         │ ack_pending  │    │     failed        │
         │ (inv. posted │    │ (retryable ♻️ if  │
         │  ack pending)│    │  retry_count <    │
         └──┬──────┬────┘    │  max_retries)     │
            │      │         └────────┬──────────┘
            │      │                  │
            │      │  ack fails       │  retry cron
            │   ┌──▼───────────┐      │
            │   │  ack_failed  │   ┌──▼─────────────┐
            │   │ (ack-only    │   │  processing   │
            │   │  retry ♻️)   │   │  (on retry)    │
            │   └──┬───────────┘   └────────────────┘
            │      │ ack retry succeeds
         ┌──▼──────▼──┐
         │  succeeded  │  ← terminal ✅ — immutable
         └─────────────┘
```

### State definitions

| State | Meaning | Invoice exists? | Retryable? |
|---|---|---|---|
| `pending` | Ledger created; no billing attempt yet | No | Yes — first attempt |
| `processing` | Engine is actively processing this subscription | No (being created) | Implicit |
| `failed` | Invoice creation or posting failed; reservation released | No | Yes — invoice retry cron |
| `ack_pending` | Invoice is posted and committed; waiting for Member 1 acknowledgement | Yes — posted | Yes — ack retry only |
| `ack_failed` | Acknowledgement failed; invoice preserved; retry pending | Yes — posted | Yes — ack retry cron |
| `succeeded` | Invoice posted AND Member 1 acknowledged | Yes — posted | No — terminal |

### Transition table

| From | To | Trigger |
|---|---|---|
| `pending` | `processing` | Engine acquires SELECT FOR UPDATE row lock |
| `processing` | `failed` | Any savepoint rollback before stage 3.10 |
| `processing` | `processing` | Draft invoice cancelled before posting |
| `processing` | `ack_pending` | Savepoint committed after stage 3.10 |
| `ack_pending` | `succeeded` | `register_billing_success` call succeeds |
| `ack_pending` | `ack_failed` | `register_billing_success` call fails |
| `ack_failed` | `succeeded` | Acknowledgement retry succeeds |
| `ack_failed` | `ack_failed` | Acknowledgement retry fails again (count increments) |
| `failed` | `processing` | Invoice retry cron picks up ledger |
| `succeeded` | — | **No exit. Terminal.** |

### Cancelled draft invoice behavior (T-21)

1. `draft_invoice_id` cleared.
2. Active `DiscountReservation` → `released`.
3. `ledger.state` → `failed` (retryable).
4. `ledger.retry_count` is **not** incremented (admin cancellation ≠ system failure).
5. Next attempt reuses this same ledger record (T-22).

### Posted invoice reversal behavior (T-24, T-25)

1. Reversal must be done via `account.move._reverse_moves()` — never by cancelling a posted invoice directly.
2. Reversal creates a credit note (`out_refund` move). Historical records preserved (T-25).
3. `ledger.state` remains `succeeded`. The period is **not** made billable again (T-24).
4. `discount_rule.current_uses` is **not** decremented (T-20).
5. If rebilling is required after a reversal, it must be an explicit admin action that creates a new billing ledger for the same period — a separate workflow outside the automated cron.
6. **Q-9 open:** The exact workflow for admin-triggered rebilling after reversal requires team and accountant confirmation.

---

## 9. Discount Allocation — Fixed Discount Proportional Distribution

### 9.1 Percentage discount (confirmed: T-15)

```
For each eligible invoice line:
  account.move.line.discount = reservation.discount_value  (%)
  Odoo computes: price_subtotal = price_unit × quantity × (1 − discount / 100)
  Tax computation fires on the discounted amount
```

Price_unit is never modified.

### 9.2 Fixed discount proportional allocation (confirmed: T-16)

A fixed-amount discount (e.g., $10 off) must be distributed across eligible invoice lines in proportion to their pre-discount subtotals. This ensures each eligible product bears a fair share of the discount and tax is calculated correctly on each individual line.

#### Step-by-step formula (PROPOSED — accountant confirmation needed for Q-7, Q-8)

```
Given:
  D       = total fixed discount amount (from reservation snapshot)
  n       = number of eligible lines
  S_i     = pre-discount subtotal of line i  = price_unit_i × quantity_i
  S_total = Σ S_i  (sum across all eligible lines)

Step 1 — Compute raw allocation per line:
  raw_i = D × (S_i / S_total)

Step 2 — Round each allocation to currency precision:
  alloc_i = currency.round(raw_i)
  Use res.currency.round() — never Python round()

Step 3 — Compute rounding remainder:
  remainder = currency.round(D) − Σ alloc_i
  (Due to rounding, Σ alloc_i may differ from D by one currency unit)

Step 4 — Allocate remainder (Q-8 — accountant to confirm method):
  OPTION A: Add remainder to the first eligible line
  OPTION B: Add remainder to the last eligible line
  OPTION C: Add remainder to the line with the largest subtotal

Step 5 — Apply per-line allocation as a percentage discount:
  discount_pct_i = (alloc_i / S_i) × 100
  Set account.move.line.discount = discount_pct_i
  Odoo applies the percentage discount natively
  Tax is computed on the discounted subtotal by Odoo

Step 6 — Verify:
  Σ (S_i × discount_pct_i / 100) should equal D within currency rounding tolerance
```

#### Special cases

| Case | Handling |
|---|---|
| S_total = 0 (all eligible lines are zero-value) | No discount applied; reservation released as non-applicable |
| D > S_total (discount exceeds total eligible amount) | **Q-7/Q-8 — accountant decision required.** Options: cap discount at S_total; apply as 100% on all lines; reject reservation. Do not implement until confirmed. |
| Only one eligible line | full discount applied to that line; no proportional split needed |
| Tax-inclusive prices on eligible lines | Proportional split is on the inclusive price. Tax extraction is then handled by Odoo. Verify with accountant that this is correct behavior (Q-7). |
| Ineligible lines (not in `product_ids` filter) | Excluded from S_total calculation and receive no discount allocation |

---

## 10. Acknowledgement Recovery — Separate from Invoice Retry

### Rationale

After stage 3.10 the invoice is durably posted and committed. Rolling it back on acknowledgement failure would orphan a real accounting entry. The billing engine therefore separates invoice failure recovery from acknowledgement failure recovery (T-23).

### Acknowledgement retry cron

| Property | Value |
|---|---|
| Name | `SubscriptIQ: Billing Acknowledgement Retry` |
| Model | `subscriptiq.billing.ledger` |
| Method | `_cron_retry_ack_failed_ledgers` |
| Frequency | Every 2 hours (more frequent than invoice retry — acknowledgement failures should resolve quickly) |
| Filter | `state in ('ack_pending', 'ack_failed') AND ack_retry_at <= now() AND ack_retry_count < ack_max_retries` |

### Acknowledgement retry logic

```
AcknowledgementService.retry_pending():
  1. Fetch ledgers where state in (ack_pending, ack_failed) AND ack_retry_at <= now()
  2. For each ledger:
       a. Call: env['subscriptiq.subscription'].register_billing_success(
                    subscription_id, invoice_id, computed_next_billing_date)
       b. SUCCESS:
            ledger.state = succeeded
            ledger.ack_retry_count unchanged
       c. FAILURE:
            ledger.state = ack_failed
            ledger.ack_retry_count += 1
            ledger.ack_error_message = error
            ledger.ack_retry_at = now() + (ack_retry_count² × ack_base_delay_hours)
            [exponential backoff]
  3. If ack_retry_count >= ack_max_retries:
       Admin alert via mail.activity or logging
       ledger remains ack_failed — requires manual resolution
```

### Key guarantee

A ledger in `ack_pending` or `ack_failed` state has a **committed, posted invoice**. It will **never** be picked up by the invoice retry cron. The two retry crns operate on disjoint sets of ledger states:

| Cron | Processes states | Does NOT process |
|---|---|---|
| Invoice retry cron | `failed` | `ack_pending`, `ack_failed`, `succeeded` |
| Ack retry cron | `ack_pending`, `ack_failed` | `failed`, `pending`, `processing`, `succeeded` |

---

## 11. Posted Invoice Reversal Policy (T-24, T-25)

### What billing guarantees

1. `_reverse_moves()` creates an `out_refund` credit note linked to the original invoice.
2. The original invoice remains in the accounting ledger with its original amounts — history preserved (T-25).
3. The billing ledger remains in `succeeded` state — the period remains "billed" from the system's perspective.
4. `discount_rule.current_uses` is NOT decremented (T-20).
5. The partner's `amount_residual` on the original invoice drops to 0 after reconciliation with the credit note — Odoo handles this natively.

### What billing does NOT do automatically on reversal

- Make the period retryable.
- Generate a new invoice for the same period.
- Restore the discount usage count.

### Admin-triggered rebilling after reversal (design to be confirmed — Q-9)

If business policy requires a new invoice after a reversal:
- Admin creates a new `subscriptiq.billing.ledger` record for the same period with a fresh `pending` state.
- This is an explicit override — it bypasses the normal idempotency check.
- Requires `group_billing_manager` permission.
- The original ledger and invoice are preserved as historical records.

---

## 12. Scheduled Actions Design

### Three crons (new in Rev 3)

| Cron | Model | Method | Frequency | Processes |
|---|---|---|---|---|
| Primary billing | `subscriptiq.billing.run` | `_cron_run_scheduled_billing` | Daily 00:05 UTC | New billing runs |
| Invoice retry | `subscriptiq.billing.ledger` | `_cron_retry_failed_ledgers` | Every 4 hours | `state=failed` ledgers |
| Ack retry | `subscriptiq.billing.ledger` | `_cron_retry_ack_failed_ledgers` | Every 2 hours | `state=ack_pending/ack_failed` ledgers |

---

## 13. Idempotency Design — Three Layers

| Layer | Mechanism | Guard type |
|---|---|---|
| **1. Billing ledger** | `UNIQUE (subscription_id, period_start, period_end)` on `subscriptiq_billing_ledger` | Database — prevents duplicate ledger creation |
| **2. Ledger state check** | `succeeded`, `ack_pending`, `ack_failed` ledger found → skip invoice attempt immediately | Application — primary guard |
| **3. Invoice partial index** | `UNIQUE (x_subscription_id, x_billing_period_start, x_billing_period_end) WHERE move_type='out_invoice' AND state!='cancel'` on `account_move` | Database — last-resort race guard |

---

## 14. Native Odoo Functionality Reused

| Capability | Odoo Mechanism |
|---|---|
| Invoice creation | `account.move.create()` |
| Invoice posting | `account.move.action_post()` |
| Invoice cancellation (draft only) | `account.move.button_cancel()` |
| Posted invoice reversal | `account.move._reverse_moves()` |
| Tax computation | `_compute_tax_line_ids` via ORM — never manually computed |
| Percentage discount on line | `account.move.line.discount` native field |
| Payment registration | `account.payment` + `action_post()` |
| Payment reconciliation | `account.move.line` matched pairs — native engine |
| Outstanding balances | `account.move.amount_residual` — read-only computed |
| Payment state | `account.move.payment_state` — native selection |
| Overdue detection | `invoice_date_due < today AND payment_state not in ('paid','reversed')` |
| Chatter / activities | `mail.thread`, `mail.activity.mixin` |
| Sequences | `ir.sequence` |
| Scheduled actions | `ir.cron` |
| Currency rounding | `res.currency.round()` — all monetary rounding |
| Fiscal position | `account.fiscal.position` on `account.move` |
| Payment terms | `account.payment.term` on `account.move` |

---

## 15. Custom Functionality Required

| Capability | Component | Reason |
|---|---|---|
| Recurring billing orchestration | `BillingEngine` service | No Community recurring engine |
| Billing period computation | `PeriodService` | Month-end anchoring, leap-year rules |
| Discount engine | `DiscountService` + `DiscountRule` + `DiscountReservation` | No native subscription discount model |
| Fixed-discount proportional allocation | `DiscountService.allocate_fixed_discount()` | Native `account.move.line.discount` is percentage-only |
| Billing run tracking | `BillingRun` + `BillingRunItem` | No native billing batch concept |
| Idempotency anchor | `BillingLedger` with 6-state machine | No native subscription-period uniqueness |
| Acknowledgement recovery | `AcknowledgementService` + ack retry cron | Separate from invoice retry |
| Concurrent run protection | PostgreSQL advisory lock | No Odoo-native cron mutex |

---

## 16. Risks and Unresolved Issues

| Risk | Severity | Status |
|---|---|---|
| Q-1: Member 1 ORM method names not confirmed | **High** | Open — mock in tests |
| Q-2/Q-3: `next_billing_date` field name and billable statuses not confirmed | **High** | Open |
| Q-4: `fiscal_position_id` / `payment_term_id` in payload not confirmed | Medium | Open |
| Q-5: `brightloop_base` group XML IDs not confirmed by Member 3 | **High** | Open — blocks `brightloop_base` |
| Q-6: Portal direct dependency on billing not confirmed | **High** | Open — affects final dep graph |
| Q-7: Fixed-discount tax treatment not confirmed | Medium | Accountant needed |
| Q-8: Rounding remainder allocation method | Medium | Accountant needed |
| Q-9: Post-reversal rebilling workflow | Medium | Accountant + Member 1 |
| Q-10: Docker timezone confirmed as UTC? | Low | Team |
| Odoo 19 `account.move` API specifics | Medium | Verify vs source before impl |
| Savepoint behavior in Odoo 19 ORM | Low | Validate in test env |

---

*Document revision 3 — incorporates `brightloop_base` decision, six-state ledger, acknowledgement recovery separation, fixed-discount proportional allocation, and posted-invoice reversal policy. No implementation code. Awaiting team review.*
