# `subscriptiq_billing` — Integration Contract Proposal
**Author:** Member 2
**Revision:** 3 — incorporates Rev 3 confirmed decisions: `brightloop_base` approved, acknowledgement recovery design, posted-invoice reversal policy, six-state ledger machine, ack-retry cron, Q-5 through Q-10 added
**Status:** PROPOSAL — requires Member 1 confirmation on Q-1 through Q-4; requires Member 3 confirmation on Q-5 and Q-6; accounting team review required on Q-7 through Q-9.

### Rev 3 summary of changes
| Change | Detail |
|---|---|
| `register_billing_success` now runs **outside** the invoice savepoint | Method executes in the same DB transaction but after savepoint commit; failure no longer rolls back the invoice — ledger goes to `ack_pending` instead |
| Acknowledgement recovery section added | `ack_pending` and `ack_failed` states represent committed, posted invoices that were not yet acknowledged by Member 1; separate ack-retry cron handles recovery |
| `brightloop_base` status updated | Team approved; blocked only on Member 3 confirming XML IDs (Q-5) |
| Dependency table expanded | All three addons now depend on `brightloop_base`; dependency direction vs data-flow direction clarified |
| Portal section expanded | Q-6 added (does portal need direct `depends` on billing?); posted-invoice reversal behavior documented; `ack_pending`/`ack_failed` invoice visibility guidance added |
| Open questions table expanded | Q-1 through Q-10 all listed |
| Reversal policy documented | Posted invoice reversal uses `_reverse_moves()`; billing period NOT made billable again; `current_uses` NOT decremented |

---

## Part A: Integration with Member 1 (`subscriptiq_subscription`)

### A.0 Confirmed architecture facts from Member 1

| Fact | Decision ref | Source |
|---|---|---|
| Subscriptions use a standalone `subscriptiq.subscription` model | T-1 | Member 1 confirmed |
| Subscriptions have their own subscription-line model | T-2 | Member 1 confirmed |
| `sale.order` is extended for quotation-to-subscription conversion only; subscriptions are NOT stored as sale orders | T-3 | Member 1 confirmed |
| `subscriptiq_billing` will declare `subscriptiq_subscription` in its `depends` list | T-4 | Member 1 confirmed |
| Member 1 will expose public ORM methods on `subscriptiq.subscription` | T-5 | Member 1 confirmed |
| No Python imports between the two addons | T-6 | Member 1 confirmed |
| No circular dependencies | T-7 | Member 1 confirmed |
| Agreed subscription prices must never be modified by discounts | T-13 | Member 1 confirmed |
| `price_unit` must already reflect pricelist/negotiated pricing; Member 2 never modifies it | T-13 | Member 1 confirmed |
| `register_billing_success` executes **outside** the invoice savepoint (after savepoint commit) | T-22 | Rev 3 confirmed |
| Acknowledgement failure does NOT roll back a committed, posted invoice | T-23 | Rev 3 confirmed |
| Cancellation of a posted invoice does NOT restore discount `current_uses` | T-20 | Rev 3 confirmed |
| `brightloop_base` addon is approved; contains only shared security groups | T-8 | Team confirmed (Rev 3) |

### A.1 Integration mechanism

Member 2 calls Member 1's methods via the Odoo ORM environment — the standard inter-addon call pattern in Odoo:

```python
# DESIGN ONLY — how billing will call Member 1's interface at runtime
# No imports. No direct table access. No raw SQL against Member 1's tables.

env['subscriptiq.subscription'].get_subscriptions_due_for_billing(billing_date)
env['subscriptiq.subscription'].get_billing_payload(subscription_id)
env['subscriptiq.subscription'].register_billing_success(subscription_id, invoice_id, next_billing_date)
env['subscriptiq.subscription'].register_billing_failure(subscription_id, error_message, retry_at)
```

Member 2 does NOT import any Python module from `subscriptiq_subscription`. All calls go through `self.env[...]`.

---

### A.2 Proposed public ORM methods on `subscriptiq.subscription`

> **These are Member 2's proposals.** Method names, argument names, and return structures require Member 1's confirmation before implementation begins (Q-1).

---

#### Method 1: `get_subscriptions_due_for_billing`

**Proposed signature:**
```python
# PROPOSED — design only

def get_subscriptions_due_for_billing(self, billing_date: date) -> list[int]:
    """
    Return a list of subscription database IDs for all active subscriptions
    whose next_billing_date is on or before billing_date.

    Called at the start of each billing run.

    Return type:
        list[int] — database IDs of subscriptiq.subscription records

    Caller (Member 2) will call get_billing_payload() for each returned ID.

    Error behavior:
        - If the query fails: raise an exception (billing run aborts entirely)
        - If no subscriptions are due: return []

    Idempotency: read-only, safe to call multiple times.
    """
```

**What "billable" means — requires Member 1 to define:**
- Lifecycle statuses that qualify (e.g., `active` only, or also `trial`?) → **(Q-3)**
- Whether paused subscriptions are ever returned → **(Q-3)**

---

#### Method 2: `get_billing_payload`

**Proposed signature:**
```python
# PROPOSED — design only

def get_billing_payload(self, subscription_id: int) -> dict:
    """
    Return all data required by billing to generate one invoice for
    the given subscription.

    Called once per subscription per billing run, after get_subscriptions_due_for_billing().

    Return type:
        dict with the following structure (all keys required unless marked optional):

        {
            # ── Identity ─────────────────────────────────────────────────
            'subscription_id': int,               # subscriptiq.subscription DB ID

            # ── Customer ─────────────────────────────────────────────────
            'partner_id': int,                    # res.partner DB ID

            # ── Currency and accounting ───────────────────────────────────
            'currency_id': int,                   # res.currency DB ID
            'fiscal_position_id': int | None,     # account.fiscal.position DB ID  (Q-4)
            'payment_term_id': int | None,        # account.payment.term DB ID     (Q-4)

            # ── Billing schedule ─────────────────────────────────────────
            'next_billing_date': str,             # ISO-8601 date: '2026-11-01'
            'billing_frequency': str,             # 'daily' | 'weekly' | 'monthly' | 'yearly'
            'billing_day_anchor': int,            # Original billing day (1–31)

            # ── Subscription lines ────────────────────────────────────────
            'lines': [
                {
                    'product_id': int,            # product.product DB ID
                    'name': str,                  # Invoice line description
                    'quantity': float,            # Billed quantity
                    'price_unit': float,          # Agreed unit price — pricelist-resolved
                                                  # Member 2 NEVER modifies this value
                    'tax_ids': [int, ...],        # account.tax DB IDs
                    'uom_id': int,                # uom.uom DB ID
                },
                ...
            ],
        }

    Note: 'discount' is NOT in the payload. Discount is Member 2's domain.
    Note: 'price_unit' must already reflect any negotiated/pricelist pricing.
          Member 2 applies discounts to the invoice only — never modifies price_unit.

    Error behavior:
        - Subscription not found: raise appropriate exception
        - Subscription no longer billable (became inactive between step 2 and step 3):
          raise appropriate exception → BillingRunItem.state=skipped
        - Payload incomplete: raise appropriate exception → BillingRunItem.state=failed

    Idempotency: read-only, safe to call multiple times.
    """
```

---

#### Method 3: `register_billing_success`

**Proposed signature:**
```python
# PROPOSED — design only

def register_billing_success(
    self,
    subscription_id: int,
    invoice_id: int,
    next_billing_date: date,
) -> None:
    """
    Called AFTER account.move.action_post() has succeeded AND the invoice
    savepoint has been committed. This call executes OUTSIDE the invoice
    savepoint — in the same outer DB transaction, but after the savepoint
    has been released (committed).  (T-22)

    Member 1 must:
      1. Advance the subscription's next_billing_date to next_billing_date.
      2. Record the invoice_id for portal history display (optional but recommended).
      3. Clear any previous billing failure indicators on the subscription.

    Transactional guarantee (Rev 3):
      - The invoice IS already committed when this method is called.
      - Member 1 must NOT assume rollback of this call will undo the invoice.
      - Member 1 must NOT commit independently inside this method.
      - If Member 1 raises an exception, the invoice is NOT rolled back.
        The billing engine:
          (a) Records BillingLedger.state = ack_pending
          (b) Records BillingRunItem.state = ack_failed
          (c) Records ack_error_message
          (d) Schedules retry via the ack-retry cron (ir_cron_ack_retry)

    Error behavior (Rev 3):
        - On exception: invoice IS committed and posted. It is preserved.
          Ledger transitions to ack_pending → ack_failed.
          Ack-retry cron picks up ack_failed ledgers and retries this call.
          Invoice retry cron does NOT re-bill ack_pending/ack_failed subscriptions.
          (The invoice-retry and ack-retry crrons operate on DISJOINT ledger states.)
    """
```

> **Critical constraint (T-22, T-23):** `register_billing_success` is called **after** the invoice savepoint is committed. It runs in the same outer transaction, but failure here does **not** roll back the invoice. `next_billing_date` is advanced by Member 1 **only** inside this call. Member 2 never updates `next_billing_date` directly.

---

#### Method 3a: Acknowledgement recovery sequence (Rev 3)

When `register_billing_success` fails after the invoice savepoint is committed, the following recovery sequence applies:

```
Member 2 (BillingEngine / AckRetryCron)              Member 1 (subscriptiq.subscription)
         │                                                       │
         │  [invoice savepoint committed — invoice posted]       │
         │                                                       │
         │── register_billing_success(sub_id, inv_id, next_date)▶│
         │◀─ RAISES EXCEPTION ────────────────────────────────── │
         │                                                       │
         │  [ledger.state = ack_pending]                         │
         │  [ledger.ack_error_message = str(exception)]          │
         │  [BillingRunItem.state = ack_failed]                  │
         │  [invoice remains posted — NOT rolled back]           │
         │                                                       │
         │  ... ack-retry cron runs (ir_cron_ack_retry) ...      │
         │                                                       │
         │── register_billing_success(sub_id, inv_id, next_date)▶│
         │◀─ None (success) ──────────────────────────────────── │
         │                                                       │
         │  [ledger.state = succeeded]                           │
         │  [ledger.acknowledged_at = utcnow()]                  │
         │  [ack_retry_count incremented]                        │
```

> **Important for Member 1:** `register_billing_success` may be called **more than once** for the same `subscription_id` and `invoice_id` during ack recovery. Member 1's implementation must be **idempotent** — a repeated call with the same arguments must not advance `next_billing_date` a second time or create duplicate records. Confirm idempotency behavior (Q-1).

---

#### Method 4: `register_billing_failure`

**Proposed signature:**
```python
# PROPOSED — design only

def register_billing_failure(
    self,
    subscription_id: int,
    error_message: str,
    retry_at: datetime,
) -> None:
    """
    Best-effort notification that billing failed for this subscription.
    Called OUTSIDE the failed savepoint (after rollback).

    Member 1 may use this to display failure status on a subscription
    detail page or dashboard.

    Guarantees:
      - next_billing_date is NOT updated.
      - Member 1 must not raise on failure of this notification —
        or if it does, billing logs it and continues.
      - This call does not affect billing retry logic (retry is governed
        by BillingLedger.next_retry_at).

    Error behavior:
        - Best-effort. If this call raises, billing logs the error
          and continues processing the next subscription.
    """
```

---

### A.3 Confirmed payload fields

| Field | Owner | Notes |
|---|---|---|
| `subscription_id` | Member 1 provides | Opaque integer ID — used as key |
| `partner_id` | Member 1 provides | `res.partner` DB ID |
| `product_id` (per line) | Member 1 provides | `product.product` DB ID |
| `quantity` (per line) | Member 1 provides | Billed quantity |
| `price_unit` (per line) | Member 1 provides | Agreed price — pricelist-resolved, never modified by billing |
| `currency_id` | Member 1 provides | `res.currency` DB ID |
| `payment_term_id` | Member 1 provides (Q-4) | `account.payment.term` DB ID |
| `billing_frequency` | Member 1 provides | `daily`, `weekly`, `monthly`, `yearly` |
| `next_billing_date` | Member 1 provides | Becomes `period_start` in billing engine |
| `tax_ids` (per line) | Member 1 provides | `account.tax` DB IDs |
| `fiscal_position_id` | Member 1 provides (Q-4) | `account.fiscal.position` DB ID |
| `discount` | **Member 2 owns** | Never in payload — billing applies discounts independently |

---

### A.4 Responsibility boundary

| Responsibility | Owner |
|---|---|
| Pricelist resolution | **Member 1** |
| Tax ID selection per product line | **Member 1** |
| Fiscal position determination | **Member 1** (Q-4) |
| Payment terms | **Member 1** (Q-4) |
| Subscription lifecycle status | **Member 1** |
| `next_billing_date` storage and advancement | **Member 1** (advanced via `register_billing_success`) |
| Subscription-line data | **Member 1** |
| Discount eligibility and selection | **Member 2** |
| Discount reservation lifecycle | **Member 2** |
| Discount usage tracking | **Member 2** |
| Invoice creation and posting | **Member 2** |
| Billing period computation | **Member 2** |
| Billing ledger (idempotency) | **Member 2** |
| Billing run tracking | **Member 2** |

---

### A.5 Billing acknowledgement sequence diagram (Rev 3)

> **Rev 3 change:** `register_billing_success` now executes **outside** the invoice savepoint, after the savepoint is committed. The invoice is preserved even if this call fails.

```
Member 2 (BillingEngine)                         Member 1 (subscriptiq.subscription)
         │                                                       │
         │── get_subscriptions_due_for_billing(billing_date) ──▶│
         │◀─ [subscription_id_1, subscription_id_2, ...]  ──────│
         │                                                       │
         │  ┌──────── SAVEPOINT for subscription_id_1 ──────┐   │
         │  │                                               │   │
         │  │── get_billing_payload(subscription_id_1) ────▶│   │
         │  │◀─ {partner_id, currency, lines, ...} ─────────│   │
         │  │                                               │   │
         │  │  [find/create billing ledger]                 │   │
         │  │  [ledger.state = in_progress]                 │   │
         │  │  [evaluate & reserve discount]                │   │
         │  │  [account.move.create()]                      │   │
         │  │  [account.move.action_post()]                 │   │
         │  │  [consume discount reservation]               │   │
         │  │  [ledger.state = ack_pending]  ◀── NEW        │   │
         │  │                                               │   │
         │  └──────── COMMIT SAVEPOINT ─────────────────────┘   │
         │                                                       │
         │  (invoice IS now committed and posted)                │
         │                                                       │
         │── register_billing_success(                           │
         │       subscription_id_1,                              │
         │       invoice_id,                                     │
         │       next_billing_date)  ───────────────────────────▶│
         │                                                       │
         │  Member 1 advances next_billing_date (idempotent)     │
         │                                                       │
         │◀─ None (success) ─────────────────────────────────── │
         │                                                       │
         │  [ledger.state = succeeded]                           │
         │  [ledger.acknowledged_at = utcnow()]                  │
         │                                                       │
         │── register_billing_success RAISES? ─ see §3a above    │
```

---

### A.6 Open questions for Member 1

| # | Question | Blocking implementation? |
|---|---|---|
| Q-1 | Exact method names Member 1 will use on `subscriptiq.subscription` | **Yes** |
| Q-2 | Exact field name for `next_billing_date` on `subscriptiq.subscription` | **Yes** |
| Q-3 | What lifecycle statuses does `subscriptiq.subscription` have, and which are billable? | **Yes** |
| Q-4 | Do subscriptions carry `fiscal_position_id` and `payment_term_id`, or are these resolved from `res.partner`? | Medium |
| Q-1 (idempotency addendum) | Will `register_billing_success` be idempotent (safe to call twice with same args during ack retry)? | **Yes** — required for Rev 3 ack-retry design |

---

## Part B: Integration with Member 3 (`subscriptiq_portal`)

### B.1 Principle

Member 3 consumes billing data **read-only**. Member 3 never writes to any model owned by Member 2. Data is accessed through Odoo's native ORM domain filters and computed fields — not through custom API methods (unless Member 3 explicitly requests a helper).

### B.2 Data available to Member 3

| Data | Source | How to access |
|---|---|---|
| Customer invoices | `account.move` (native) | ORM: `move_type='out_invoice'`, filter by `partner_id` |
| Invoice amounts | `amount_untaxed`, `amount_tax`, `amount_total` | Native computed fields |
| Outstanding balance | `amount_residual` | Native computed field |
| Payment state | `payment_state` | Native selection field |
| Invoice due date | `invoice_date_due` | Native date field |
| Overdue invoices | `invoice_date_due < today AND payment_state not in ('paid','reversed')` | ORM domain filter |
| Billing period | `x_billing_period_start`, `x_billing_period_end` on `account.move` | Custom fields — Member 2 exposes |
| Subscription reference | `x_subscription_id` on `account.move` | Custom field — Member 2 exposes |
| Billing run status | `subscriptiq.billing.run` | Member 2 grants read access |
| Billing run items | `subscriptiq.billing.run.item` | Member 2 grants read access (error_message excluded from portal display) |
| Billing ledger | `subscriptiq.billing.ledger` | Member 2 grants read access |
| Payment records | `account.payment` (native) | ORM — reconciled to `account.move.line` natively |
| Revenue aggregates | Query `account.move` with ORM filters | Prefer ORM filters over custom SQL |
| **Ack-pending / ack-failed invoices** (Rev 3) | `subscriptiq.billing.ledger` where `state in ('ack_pending','ack_failed')` | Ledger carries `invoice_id` — invoice IS posted; display as normal invoices |

### B.3 Portal customer access to their own invoices

Odoo's native `account` module already includes portal record rules scoped to `partner_id`. Member 2 does not add custom portal record rules for `account.move`. Member 3 leverages the existing native portal mechanism.

### B.3a Ack-pending and ack-failed invoices — visibility guidance (Rev 3)

Invoices in ledger states `ack_pending` or `ack_failed` represent **committed, posted invoices** where Member 1's acknowledgement call has not yet succeeded. These invoices:

- Have `account.move.state = 'posted'` — they are fully valid.
- Have `payment_state = 'not_paid'` — they are outstanding.
- **Should be displayed normally** in the portal invoice list and admin billing history.
- Are NOT errors from an accounting perspective — only the internal acknowledgement is pending.

Member 3 can identify these invoices by joining `subscriptiq.billing.ledger` on `invoice_id` and checking `ledger.state in ('ack_pending', 'ack_failed')`. Member 3 may optionally display a system note to admins (not customers) that acknowledgement is pending.

### B.3b Posted invoice reversal — behaviour for Member 3 (Rev 3)

When a billing administrator reverses a posted invoice using `_reverse_moves()`:

| Aspect | Behaviour |
|---|---|
| Reversal creates | An `out_refund` (credit note) on `account.move` with `move_type='out_refund'` |
| Original invoice | Remains in `state='posted'`; `payment_state` transitions to `'reversed'` |
| Billing ledger | `ledger.state` remains `'succeeded'` — reversal does NOT change the ledger |
| Billing period | NOT made billable again (T-24) |
| Discount `current_uses` | NOT decremented (T-20) |
| Rebilling after reversal | Requires explicit admin action — process undefined pending Q-9 |

Member 3 portal display guidance:
- Filter customer invoice list to `move_type='out_invoice'` — reversed invoices appear with `payment_state='reversed'`.
- Credit notes appear separately with `move_type='out_refund'`.
- Do NOT attempt to programmatically "undo" the billing ledger or make the period rebillable — that is a Member 2 admin responsibility.

### B.4 Security access for Member 3's groups

The following rows are proposed for inclusion in `subscriptiq_billing/security/ir.model.access.csv` once Member 3 publishes their group XML IDs (Q-5). Until then, placeholders reference `base.group_user` for development:

```csv
# ── Billing models readable by Member 3's admin group (Q-5) ──────────────────
# NOTE: XML IDs below use placeholder subscriptiq_portal.group_portal_admin
# Blocked pending Member 3 confirmation (Q-5)
access_billing_run_portal_admin,billing_run_portal_admin,model_subscriptiq_billing_run,subscriptiq_portal.group_portal_admin,1,0,0,0
access_run_item_portal_admin,run_item_portal_admin,model_subscriptiq_billing_run_item,subscriptiq_portal.group_portal_admin,1,0,0,0
access_ledger_portal_admin,ledger_portal_admin,model_subscriptiq_billing_ledger,subscriptiq_portal.group_portal_admin,1,0,0,0
access_discount_rule_portal_admin,discount_rule_portal_admin,model_subscriptiq_discount_rule,subscriptiq_portal.group_portal_admin,1,0,0,0
```

> **Blocked on Q-5:** Member 3 must confirm the XML ID `subscriptiq_portal.group_portal_admin` (or equivalent) before these rows can be finalized.

### B.4a Dependency direction — Q-6 (Rev 3)

| Question | Status |
|---|---|
| Does `subscriptiq_portal` need `subscriptiq_billing` in its `depends` list? | **Q-6 — OPEN — requires Member 3 confirmation** |

**Member 2's position:**
- If Member 3 only reads `account.move` native fields and custom `x_*` fields on it, no direct dependency is strictly necessary (Odoo resolves field extensions at runtime).
- If Member 3's views or controllers reference `subscriptiq.billing.run`, `subscriptiq.billing.ledger`, or other custom models by name — a direct `depends` is required.
- A direct `depends` on `subscriptiq_billing` does **not** create a circular dependency (data flows: subscription → billing → portal; dependency arrow goes the same direction).

**Until Q-6 is resolved:** Member 2 assumes no direct `depends` from portal to billing. If Member 3 needs to reference billing models in views, Member 3 adds `subscriptiq_billing` to their addon's `depends` list.

### B.5 Conflict resolution map

| Conflict Area | Risk | Resolution |
|---|---|---|
| `account.move` form view inheritance | Both Member 2 and 3 may inherit | Member 2 owns the primary inheritance; Member 3 creates a separate `inherit_id` pointing to the native view or Member 2's view |
| `res.partner` field additions | Both may add fields | Each uses a namespaced prefix. Member 2: none planned. Member 3: `x_portal_*` |
| Menu hierarchy | Both may add menu items | Member 2: Billing menu. Member 3: Portal/Analytics menu. No shared parent menu without team agreement |
| `ir.model.access.csv` duplication | Two addons defining same access record ID | Each addon defines access only for models it owns |
| `account.move` record rules for portal customers | Member 3 may add | Member 2 does not add customer-scoping record rules. Odoo native rule is sufficient |
| Revenue reporting SQL | Both may compute | Member 2 exposes computed fields or helper methods; Member 3 reads, does not duplicate SQL |
| Reversal workflow | Member 3 may want to trigger reversals | Member 3 uses native Odoo credit-note wizard; Member 2 does not expose a custom reversal API |

### B.6 Data Member 3 must NOT access

| Restricted | Reason |
|---|---|
| `subscriptiq.discount.rule` write access | Discount creation is Member 2's exclusive domain |
| `subscriptiq.billing.run.item.error_message` in portal views | Internal failure details — not for customer display |
| `account.payment` write operations via portal | Payments use native Odoo payment wizard only |
| `subscriptiq.billing.ledger.last_error_message` in portal | Internal debugging field |
| `subscriptiq.billing.ledger.ack_error_message` in portal | Internal ack-retry debugging field — admin use only |
| Direct queries on Member 1's subscription tables | Member 3 must use Member 1's public ORM methods for subscription data |

---

## Part C: Shared Base Addon (`brightloop_base`) — Approved, Pending Detail

### C.1 Current status (Rev 3)

The team has **approved** the introduction of `brightloop_base` (T-8). The addon will contain only shared security groups — no subscription or billing business logic.

Current state:
- The addon does **not yet exist** — no files created.
- No addon should reference it until Member 3 confirms group XML IDs (Q-5).
- Member 2 continues using `subscriptiq_billing.group_billing_manager` and `subscriptiq_billing.group_billing_user` as internal groups.
- Cross-addon access CSV rows remain commented out pending Q-5.

### C.2 Proposed addon dependency graph (Rev 3)

```
brightloop_base          ← shared groups only, no business logic
     ▲       ▲       ▲
     │       │       │    (depends on = install after = ▲)
subscriptiq_ subscriptiq_ subscriptiq_
subscription  billing     portal
     ▲                   ▲
     │    (data flow)    │    (data flows upward — subscriptions feed billing,
     └──────────────── billing feeds portal)
```

**Dependency direction vs data-flow direction:**

| Relationship | Direction | Explanation |
|---|---|---|
| `subscriptiq_billing` depends on `subscriptiq_subscription` | Subscription ← Billing | Billing is installed after subscription; references subscription models at runtime |
| `subscriptiq_billing` depends on `brightloop_base` | Base ← Billing | Billing references shared groups from base |
| `subscriptiq_subscription` depends on `brightloop_base` | Base ← Subscription | Subscription references shared groups from base |
| `subscriptiq_portal` depends on `brightloop_base` | Base ← Portal | Portal references shared groups from base |
| `subscriptiq_portal` depends on `subscriptiq_billing` (Q-6) | Billing ← Portal | **Unresolved** — portal may need billing models in views |
| Data flows: subscription → billing → portal | Opposite to dependency arrows | This is correct Odoo pattern — consuming module installs last, data produced by dependencies |

### C.3 Proposed shared groups

If Member 3 approves, `brightloop_base` would contain only:

| Proposed XML ID | Name | Description |
|---|---|---|
| `brightloop_base.group_subscriptiq_admin` | SubscriptIQ Administrator | Full access across all three addons |
| `brightloop_base.group_subscriptiq_staff` | SubscriptIQ Staff | Internal operational user |
| `brightloop_base.group_subscriptiq_customer` | SubscriptIQ Customer | Portal customer |

### C.4 Questions for Member 3 (Q-5) — blocking

1. Are these the correct group names and XML IDs?
2. Should the customer group inherit from `base.group_portal`?
3. Should the admin group inherit from `base.group_system` or stand alone?
4. Are there additional groups needed for Member 3's portal analytics?

Until Member 3 answers Q-5, Member 2:
- Defines only `subscriptiq_billing.group_billing_manager` and `subscriptiq_billing.group_billing_user`.
- Uses `base.group_user` as a development placeholder in any cross-addon access lines.
- Does NOT create the `brightloop_base` directory or any files within it.

---

## Part D: Shared Conventions

### D.1 Field naming

| Context | Convention | Example |
|---|---|---|
| Custom fields on native models | `x_` prefix | `x_subscription_id`, `x_billing_period_start` |
| Custom model names | `subscriptiq.` namespace | `subscriptiq.billing.run` |
| XML view record IDs | `subscriptiq_billing_` prefix | `subscriptiq_billing_billing_run_form_view` |
| Security group XML IDs | Addon-namespaced | `subscriptiq_billing.group_billing_manager` |
| `brightloop_base` group XML IDs | `brightloop_base.` prefix | `brightloop_base.group_subscriptiq_admin` (pending Q-5) |

### D.2 Change management protocol

**If Member 1 changes the payload shape:**
1. Communicate before merging to `integration`.
2. Member 2 updates payload validation and tests in the same sprint.
3. Both addons updated in coordinated PRs.

**If Member 1 renames an ORM method:**
1. Notify Member 2 immediately — it is a breaking change.
2. Member 2 updates all callers and mock in tests.

**If Member 1 changes `register_billing_success` behaviour:**
1. Critical — this method is called outside the savepoint in Rev 3. Any signature or behaviour change is a breaking change.
2. Notify Member 2 before any merge to `integration`.

**If Member 3 needs additional billing data:**
1. Member 3 opens a request — Member 2 evaluates.
2. Member 2 adds field or helper method; Member 3 reads it.
3. Member 3 never writes to billing models.

### D.3 Integration test boundary

| Test | Who owns it |
|---|---|
| Billing engine with mock Member 1 | Member 2 (`tests/test_member1_interface.py`) |
| Full billing cycle with real Member 1 addon | Integration branch — both Member 1 and 2 |
| Portal invoice display | Integration branch — Member 2 and 3 |
| Ack-retry cron with real Member 1 | Integration branch — both Member 1 and 2 |
| Reversal visible in portal | Integration branch — Member 2 and 3 |

Member 2 maintains `MockSubscriptionBillingService` in `tests/common.py`. Member 1 may use it to verify their real implementation is interface-compatible — including the idempotency requirement on `register_billing_success`.

---

## Part E: Complete Open Questions Register (Rev 3)

| # | Directed to | Question | Blocking? |
|---|---|---|---|
| Q-1 | Member 1 | Exact method names on `subscriptiq.subscription`; confirm `register_billing_success` idempotency | **Yes** |
| Q-2 | Member 1 | Exact field name for `next_billing_date` on `subscriptiq.subscription` | **Yes** |
| Q-3 | Member 1 | What lifecycle statuses exist, and which are billable? Are paused subscriptions ever returned? | **Yes** |
| Q-4 | Member 1 | Do subscriptions carry `fiscal_position_id` / `payment_term_id`, or are these from `res.partner`? | Medium |
| Q-5 | Member 3 | Confirm `brightloop_base` group XML IDs, inheritance, and any additional groups needed | **Yes** |
| Q-6 | Member 3 | Does `subscriptiq_portal` need direct `depends` on `subscriptiq_billing`? | **Yes** |
| Q-7 | Accounting team | Tax treatment of fixed-discount lines: use native `discount` percentage field (per-line) or a separate negative invoice line? | **Yes** |
| Q-8 | Accounting team | Rounding remainder allocation for fixed discount: first eligible line, last eligible line, or largest-subtotal line? | Medium |
| Q-9 | Accounting team + Member 1 | Post-reversal rebilling workflow: does billing period become billable again? Does admin create a new billing run? | Medium |
| Q-10 | Team | Confirm all Docker containers run UTC timezone | Low |

---

*Document revision 3 — integration contract updated with Rev 3 confirmed decisions: `register_billing_success` moved outside invoice savepoint; acknowledgement recovery design; `brightloop_base` approved pending Member 3 XML ID confirmation; portal reversal guidance added; Q-5 through Q-10 added. Awaiting Member 1 confirmation on Q-1 through Q-4, Member 3 confirmation on Q-5 and Q-6, and accounting team review on Q-7 through Q-9.*
