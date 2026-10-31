# `subscriptiq_billing` — Testing Strategy
**Owner:** Member 2
**Target:** Odoo 19 Community Edition
**Revision:** 3 — adds acknowledgement recovery tests, proportional fixed-discount allocation tests, six-state ledger tests, ack-retry cron tests, reversal policy tests; updates billing engine test for savepoint-external acknowledgement
**Status:** Architecture design — awaiting team review. No tests implemented.

### Rev 3 summary of changes
| Change | Detail |
|---|---|
| Two new test files | `test_acknowledgement.py` (ack-retry cron) and `test_discount_allocation.py` (proportional fixed-discount) |
| `test_billing_engine.py` | `test_register_success_fails` behaviour changed — invoice now preserved, NOT rolled back; three new ack-path test cases added |
| `test_billing_ledger.py` | Six-state machine: `ack_pending` and `ack_failed` states added; disjoint cron state sets verified |
| `test_billing_run.py` | `test_ack_failure_count_computed` added |
| `test_idempotency.py` | Three new cases: ack-state ledgers skip re-billing; reversal does not make period billable |
| `test_member1_interface.py` | `test_register_success_raises` updated — invoice preserved, ledger goes to `ack_failed` |
| Coverage targets | `acknowledgement_service.py` ≥ 90% added |

---

## 0. Testing Philosophy

1. **Use Odoo's native test framework** (`odoo.tests.common`). No pytest or external runners without team agreement.
2. **Never test what Odoo already tests.** Do not test `action_post()` internals, tax arithmetic, reconciliation, or journal entry balance. These are Odoo core.
3. **Test boundaries, not implementations.** Verify that billing calls the right Odoo methods with the right arguments and reads the correct results.
4. **Mock Member 1's interface completely.** All billing unit tests use a controlled `MockSubscriptionService` — they never depend on `subscriptiq_subscription` being installed.
5. **Test failure paths as rigorously as success paths.** Financial systems have no tolerance for silent failures.
6. **Test the billing ledger state machine explicitly.** The ledger is the idempotency backbone — every state transition must have a test.
7. **Test discount reservation lifecycle explicitly.** Reserve, consume, and release paths must each be verified.
8. **Use `TransactionCase`.** Each test rolls back cleanly. No data bleeds between tests.

---

## 1. Test File Inventory

```
subscriptiq_billing/tests/
├── __init__.py
├── common.py                       # Shared fixtures and MockSubscriptionService
├── test_billing_engine.py          # BillingEngine orchestration — all 16 stages (Rev 3: ack stage separated)
├── test_billing_run.py             # BillingRun model and state machine
├── test_billing_ledger.py          # BillingLedger six-state machine and idempotency
├── test_discount_service.py        # DiscountService eligibility and selection
├── test_discount_reservation.py    # Reservation lifecycle: reserve, consume, release
├── test_discount_allocation.py     # ← NEW Rev 3: proportional fixed-discount allocation
├── test_period_service.py          # PeriodService date arithmetic (pure Python)
├── test_idempotency.py             # End-to-end duplicate invoice prevention
├── test_acknowledgement.py         # ← NEW Rev 3: ack-retry cron and recovery
├── test_account_integration.py     # Accounting workflow (invoice, tax, payment)
└── test_member1_interface.py       # Interface adapter and error propagation
```

---

## 2. `common.py` — Shared Fixtures

```python
# DESIGN ONLY — class and method signatures, no implementation

class BillingTestCommon(TransactionCase):
    """
    Base class for all billing tests.

    Creates in setUpClass:
      - Test company with EUR currency
      - Test customer (res.partner)
      - Test service product with a 20% tax
      - Customer invoices journal
      - A billing_manager user
      - Default billing configuration (max_retries=3, batch_size=100)
      - One DiscountRule: 10% percentage, unlimited uses, no date restrictions
    """

class MockSubscriptionService:
    """
    Fully controllable mock of Member 1's ORM interface.
    Used in all unit and billing-engine tests.

    Configurable:
      - subscriptions_to_return: list[int] — returned by get_subscriptions_due_for_billing()
      - payloads: dict[int, dict] — returned by get_billing_payload(subscription_id)
      - fail_payload_for: list[int] — subscription IDs that raise on get_billing_payload()
      - fail_register_success_for: list[int] — raise BillingUpdateError on register_billing_success()
      - register_failure_raises: bool — if True, register_billing_failure() raises

    Records for assertions:
      - success_calls: list[tuple[int, int, date]] — (sub_id, invoice_id, next_date)
      - failure_calls: list[tuple[int, str, datetime]] — (sub_id, error, retry_at)
    """

def make_payload(
    subscription_id: int = 1,
    partner_id: int = None,
    currency_id: int = None,
    frequency: str = 'monthly',
    next_billing_date: date = None,
    day_anchor: int = 1,
    lines: list = None,
) -> dict:
    """Constructs a minimal valid billing payload with sensible defaults."""
```

---

## 3. `test_billing_engine.py`

Tests `BillingEngine.execute_run()` end-to-end. Uses `MockSubscriptionService` throughout.

> **Rev 3 note:** Stage 3.11 (acknowledgement) now executes **outside** the invoice savepoint. `register_billing_success` failure preserves the posted invoice; the ledger transitions to `ack_pending` → `ack_failed`. The invoice-retry cron and ack-retry cron operate on **disjoint** ledger states.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_single_subscription_success` | One subscription, no discount | Invoice posted; ledger.state=succeeded; BillingRun.state=done; register_billing_success called once |
| `test_multiple_subscriptions_all_success` | Three subscriptions | Three invoices; invoice_count=3; failure_count=0 |
| `test_partial_failure` | Three subs, middle fails on invoice creation | Two invoices; BillingRun.state=partial; middle sub's ledger=failed; other subs unaffected |
| `test_all_fail` | All subscriptions fail payload validation | BillingRun.state=failed; no invoices; no ledgers succeeded |
| `test_fetch_fails` | get_subscriptions_due raises | BillingRun.state=failed; no run items created |
| `test_no_subscriptions_due` | Empty list returned | BillingRun.state=done; subscription_count=0 |
| `test_register_success_fails` | register_billing_success raises **(Rev 3)** | Invoice IS committed and posted (not rolled back); ledger.state=ack_failed; BillingRunItem.state=ack_failed; ack_error_message populated |
| `test_ack_failure_preserves_invoice` | **(Rev 3 new)** ack fails after savepoint commit | `account.move.state == 'posted'`; invoice_id is set on ledger; invoice is NOT cancelled or reversed |
| `test_ack_failure_recorded_separately` | **(Rev 3 new)** ack fails | `BillingRunItem.state == 'ack_failed'`; `BillingRunItem.ack_error_message` populated; `BillingRun.ack_failure_count` incremented |
| `test_successful_ack_after_invoice` | **(Rev 3 new)** full success with ack | invoice posted → `ack_pending` (inside savepoint) → `succeeded` (after ack) — all four states visible in sequence |
| `test_manual_trigger` | Wizard triggers run | triggered_by='manual'; triggered_by_user_id populated |
| `test_cron_trigger` | Cron triggers run | triggered_by='cron'; triggered_by_user_id empty |
| `test_concurrent_run_blocked` | Second run while first is running | Advisory lock prevents start; only one BillingRun in 'running' state |
| `test_batch_commit` | 110 subscriptions, batch_size=100 | Two env.cr.commit() calls; all 110 invoiced |
| `test_discount_applied_on_success` | 10% discount rule eligible | Invoice line.discount=10.0; reservation.state=consumed |
| `test_discount_released_on_failure` | Discount reserved, then invoice fails | reservation.state=released; discount_rule.current_uses unchanged |
| `test_next_billing_date_not_advanced_on_failure` | Invoice posting fails | register_billing_success NOT called; next_billing_date unchanged |
| `test_period_computation_used` | Monthly subscription, Jan 31 | period_start=Jan-31; period_end=Jan-31; next_billing_date=Feb-28 |

---

## 4. `test_billing_run.py`

Tests `subscriptiq.billing.run` model — state machine, computed fields, sequence generation.

### Test cases

| Test ID | Verifies |
|---|---|
| `test_sequence_generation` | Name matches `BRUN/YYYY/NNN` pattern |
| `test_initial_state_draft` | New run starts as draft |
| `test_state_draft_to_running` | state=running after engine initiates |
| `test_state_running_to_done` | All items success → state=done |
| `test_state_running_to_partial` | Mix of success and failure → state=partial |
| `test_state_running_to_failed` | Zero successes → state=failed |
| `test_invoice_count_computed` | Computed from successful items |
| `test_failure_count_computed` | Computed from failed items |
| `test_ack_failure_count_computed` | **(Rev 3 new)** Computed from items with state=ack_failed; does NOT include items with state=failed |
| `test_total_billed_computed` | Sum of amount_total across posted invoices |
| `test_duration_computed` | run_end_datetime − run_date in seconds |
| `test_unique_running_constraint` | Second run in 'running' state raises IntegrityError |
| `test_notes_preserved` | Admin notes not overwritten by engine |

---

## 5. `test_billing_ledger.py`

Tests `subscriptiq.billing.ledger` state machine — the idempotency backbone.

> **Rev 3:** The ledger now has **six** states: `pending` → `processing` → `ack_pending` → `succeeded`; and `processing` → `failed`; and `ack_pending` → `ack_failed` → `succeeded` (via ack-retry). The invoice-retry cron and ack-retry cron operate on **disjoint** ledger state sets.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_ledger_created_on_first_attempt` | First billing for sub + period | Ledger created with state=pending |
| `test_ledger_reused_on_retry` | Previous failed ledger exists | Engine reuses existing record; no new ledger created (T-18) |
| `test_ledger_succeeded_is_skipped` | Ledger.state=succeeded already | BillingRunItem.state=skipped, reason=already_billed |
| `test_ledger_processing_concurrent_skip` | Ledger.state=processing from another process | BillingRunItem.state=skipped, reason=concurrent |
| `test_ledger_uniqueness_constraint` | Two creates for same (sub_id, period_start, period_end) | IntegrityError on second create |
| `test_ledger_failed_to_processing_on_retry` | Retry cron picks up failed ledger | state transitions to processing |
| `test_ledger_succeeded_immutable` | Attempt to write to succeeded ledger | State does not change; invoice_id preserved |
| `test_ledger_cancelled_draft_becomes_retryable` | Admin cancels draft invoice | ledger.state=failed; draft_invoice_id cleared; reservation released (T-17) |
| `test_ledger_retry_count_increments` | Failed attempt | retry_count=1 |
| `test_ledger_abandoned_at_max_retries` | retry_count=3 (max) | Invoice-retry cron does not pick up; state remains failed |
| `test_ledger_next_retry_at_exponential` | Three failures | next_retry_at grows: 4h, 16h, 36h (4 × n²) |
| `test_ledger_invoice_id_set_on_success` | Successful billing | ledger.invoice_id = posted invoice |
| `test_ledger_draft_invoice_id_cleared_on_success` | After successful posting | draft_invoice_id = None |
| `test_ledger_ack_pending_after_invoice_commit` | **(Rev 3 new)** Savepoint commits successfully | ledger.state transitions to ack_pending inside savepoint before ack call |
| `test_ledger_ack_failed_after_ack_failure` | **(Rev 3 new)** register_billing_success raises | ledger.state=ack_failed; ack_error_message set; invoice still posted |
| `test_ledger_succeeded_after_ack_retry` | **(Rev 3 new)** Ack-retry cron calls register_billing_success successfully | ledger.state=succeeded; acknowledged_at set |
| `test_ledger_ack_pending_not_picked_up_by_invoice_retry_cron` | **(Rev 3 new)** Ledger in ack_pending state | Invoice-retry cron domain excludes ack_pending; cron does NOT pick it up |
| `test_ledger_failed_not_picked_up_by_ack_retry_cron` | **(Rev 3 new)** Ledger in failed state | Ack-retry cron domain excludes failed; cron does NOT pick it up |
| `test_posted_invoice_reversal_ledger_remains_succeeded` | **(Rev 3 new)** Posted invoice reversed via _reverse_moves() | ledger.state remains succeeded; invoice_id still set to original |

---

## 6. `test_discount_service.py`

Tests `DiscountService.find_eligible_rule()` — eligibility evaluation and rule selection.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_no_rules_returns_none` | No active rules | Returns None |
| `test_percentage_rule_eligible` | Active, in-date, no conditions | Rule returned |
| `test_fixed_rule_eligible` | Fixed-amount rule | Rule returned |
| `test_expired_rule_not_eligible` | date_end in past | Not returned |
| `test_future_rule_not_eligible` | date_start in future | Not returned |
| `test_max_uses_reached` | current_uses == max_uses | Not returned |
| `test_unlimited_uses` | max_uses=0, current_uses=10000 | Returned |
| `test_min_qty_not_met` | Quantity below min_qty | Not returned |
| `test_min_qty_met` | Quantity equals min_qty | Returned |
| `test_min_amount_not_met` | Invoice total below min_amount | Not returned |
| `test_min_amount_met` | Invoice total equals min_amount | Returned |
| `test_product_filter_match` | Rule restricted to product A; product A in lines | Returned |
| `test_product_filter_no_match` | Rule restricted to product A; only product B in lines | Not returned |
| `test_highest_priority_selected` | Rules at priority 1 and 5; both eligible | Priority 1 returned (lowest number = highest priority) |
| `test_inactive_rule_not_eligible` | active=False | Not returned |

---

## 7a. `test_discount_allocation.py` *(Rev 3 — new)*

Tests the proportional fixed-discount allocation algorithm in `DiscountService`.

> Fixed discounts are distributed proportionally across eligible lines by pre-discount subtotal (`quantity × price_unit`). The resulting per-line percentage is applied via the native `account.move.line.discount` field. This test file verifies the allocation math independently of the full billing engine.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_single_eligible_line_full_discount` | EUR 20 fixed discount, one eligible line with subtotal EUR 100 | line.discount = 20.0% |
| `test_two_equal_lines_split_evenly` | EUR 20 discount, two lines each EUR 100 | Each line gets EUR 10 → discount=10.0% each |
| `test_two_unequal_lines_proportional` | EUR 30 discount, line A subtotal EUR 60, line B subtotal EUR 40 | Line A gets EUR 18 (discount=30%), line B gets EUR 12 (discount=30%) |
| `test_rounding_remainder_allocated_to_first_eligible_line` | EUR 10 discount, three lines of EUR 33.33 each | Allocation: 3.33 + 3.33 + 3.34 (remainder on first) → verify sum equals exactly EUR 10 |
| `test_zero_total_eligible_releases_reservation` | EUR 15 fixed discount, all eligible lines have subtotal=0 | Reservation released (cannot divide by zero); discount not applied |
| `test_ineligible_lines_excluded_from_split` | EUR 20 discount; line A eligible (EUR 100), line B ineligible (EUR 50) | Only line A receives discount; line B.discount=0.0 |
| `test_zero_value_line_excluded` | EUR 20 discount; line A subtotal=0 (eligible), line B subtotal=EUR 100 (eligible) | Zero-value line excluded from denominator; all discount on line B |
| `test_discount_pct_computed_correctly_per_line` | EUR 25 discount, line subtotal EUR 200 | `line.discount = 12.5` exactly (25/200 × 100) |
| `test_tax_computed_on_discounted_amount` | Line: qty=1, price_unit=100, 20% tax; discount=10% | Tax base = EUR 90; tax amount = EUR 18 (Odoo core computes this; test verifies amount_tax on invoice) |
| `test_discount_exceeds_line_subtotal` | EUR 200 fixed discount, single line subtotal EUR 100 | Discount capped at 100%; reservation partially consumed; remaining EUR 100 released — pending Q-7 |

> **Q-7 (accounting team):** The case where the fixed discount exceeds the eligible subtotal is unresolved. The last test documents the expected behaviour but is marked `@unittest.skip("pending Q-7")` until the accounting team confirms.

---

## 7b. `test_acknowledgement.py` *(Rev 3 — new)*

Tests `AcknowledgementService` and the `_cron_retry_ack_failed_ledgers` cron.

> The ack-retry cron picks up ledgers in `ack_pending` or `ack_failed` state and retries `register_billing_success`. It must NOT create new invoices. It must NOT interfere with the invoice-retry cron. Exponential backoff applies.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_ack_retry_cron_picks_up_ack_pending` | Ledger in `ack_pending` state, `ack_retry_at ≤ now` | Cron processes this ledger |
| `test_ack_retry_cron_picks_up_ack_failed` | Ledger in `ack_failed`, `ack_retry_at ≤ now` | Cron processes this ledger |
| `test_ack_retry_cron_skips_future_retry_at` | Ledger `ack_failed`, `ack_retry_at > now` | Cron does NOT process it |
| `test_ack_retry_succeeds_sets_succeeded` | Cron calls `register_billing_success` → success | `ledger.state = succeeded`; `acknowledged_at` set; `ack_retry_count` incremented |
| `test_ack_retry_failure_increments_count` | Cron calls `register_billing_success` → raises | `ledger.state = ack_failed`; `ack_retry_count += 1`; `ack_error_message` updated |
| `test_ack_retry_exponential_backoff` | Three consecutive ack failures | `ack_retry_at` grows: base_hours × 2^1, base_hours × 2^2, base_hours × 2^3 |
| `test_ack_retry_abandoned_at_max_retries` | `ack_retry_count == ack_max_retries` | Cron excludes this ledger from processing; state remains `ack_failed`; alert/log written |
| `test_ack_retry_does_not_create_new_invoice` | Ack retry for a ledger that already has `invoice_id` | No new `account.move` created; existing invoice unchanged |
| `test_ack_retry_does_not_interfere_with_invoice_retry` | Mix of `failed` and `ack_failed` ledgers | Invoice-retry cron processes only `failed`; ack-retry cron processes only `ack_pending`/`ack_failed` — no overlap |
| `test_ack_retry_idempotent_on_already_succeeded` | Ledger already `succeeded` when cron runs | Cron skips it (domain filter excludes succeeded); no double-call to Member 1 |

---

## 7. `test_discount_reservation.py`

Tests the discount reservation lifecycle — reserve, consume, release.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_reservation_created_on_eligible_rule` | Eligible rule found | DiscountReservation.state=reserved |
| `test_reservation_snapshots_values` | Rule has 15% value | reservation.discount_value=15.0 (snapshot) |
| `test_reservation_consumed_after_post` | Invoice posts successfully | reservation.state=consumed; discount_rule.current_uses+=1 |
| `test_usage_not_incremented_on_failure` | Savepoint rolled back | current_uses unchanged (reservation rolled back too) |
| `test_reservation_released_on_draft_cancel` | Admin cancels draft invoice | reservation.state=released; current_uses unchanged |
| `test_concurrent_last_use_only_one_wins` | Two threads both try the last available use | SELECT FOR UPDATE ensures only one reservation created |
| `test_no_reservation_when_no_rule` | No eligible rule | No DiscountReservation created |
| `test_unique_active_reservation_per_ledger` | Two reservations for same ledger in reserved state | IntegrityError on second insert |
| `test_snapshot_preserved_if_rule_edited` | Rule value changed between reserve and consume | Invoice reflects reservation snapshot, not new rule value |

---

## 8. `test_period_service.py`

Tests `PeriodService` — pure Python, no database required.

### Test cases

| Test ID | Input | Expected output |
|---|---|---|
| `test_daily_standard` | daily, 2026-11-01 | period: 01→01, next: 02 |
| `test_weekly_standard` | weekly, 2026-11-01 | period: 01→07, next: 08 |
| `test_monthly_standard` | monthly, 2026-11-15, anchor=15 | period: Nov-15→Dec-14, next: Dec-15 |
| `test_monthly_jan31` | monthly, 2026-01-31, anchor=31 | next: 2026-02-28 |
| `test_monthly_feb28_anchor31` | monthly, 2026-02-28, anchor=31 | next: 2026-03-31 |
| `test_monthly_apr30_anchor31` | monthly, 2026-04-30, anchor=31 | next: 2026-05-31 |
| `test_monthly_leap_feb29` | monthly, 2028-02-29, anchor=29 | next: 2028-03-29 |
| `test_monthly_non_leap_anchor29` | monthly, 2027-02-28, anchor=29 | next: 2027-03-29 |
| `test_yearly_standard` | yearly, 2026-06-15 | period: Jun-15-26 → Jun-14-27, next: Jun-15-27 |
| `test_yearly_leap_feb29` | yearly, 2028-02-29 | next: 2029-02-28 |
| `test_is_leap_2028` | 2028 | True |
| `test_is_not_leap_2026` | 2026 | False |
| `test_is_not_leap_1900` | 1900 | False |
| `test_is_leap_2000` | 2000 | True |
| `test_last_day_feb_non_leap` | year=2026, month=2 | 28 |
| `test_last_day_feb_leap` | year=2028, month=2 | 29 |
| `test_last_day_april` | any year, month=4 | 30 |

---

## 9. `test_idempotency.py`

End-to-end duplicate invoice prevention.

### Test cases

| Test ID | Scenario | Verifies |
|---|---|---|
| `test_no_duplicate_same_period` | Run bills sub A; run again for same period | Second attempt: BillingRunItem.state=skipped; ledger.state=succeeded unchanged; no new invoice |
| `test_cancelled_invoice_allows_rebilling` | Invoice cancelled (state=cancel); billing re-run | New invoice created for same period (partial index excludes cancelled) |
| `test_credit_note_does_not_block_rebilling` | Only out_refund exists for period | New out_invoice allowed (credit note has different move_type) |
| `test_sql_constraint_catches_race` | Two concurrent transactions both try create invoice for same period | Second `account.move.create()` raises IntegrityError |
| `test_ledger_constraint_catches_race` | Two concurrent transactions both try create ledger for same period | Second `subscriptiq.billing.ledger.create()` raises IntegrityError |
| `test_different_periods_not_blocked` | Same sub, period-1 and period-2 | Both invoices created |
| `test_different_subs_not_blocked` | Sub A and sub B, same period | Both invoices created |
| `test_retry_uses_existing_ledger` | Sub fails; retry runs | Retry reuses the exact same ledger record — `id` is identical (T-18) |
| `test_crash_recovery` | Simulate run crash mid-loop | Re-run skips already-succeeded ledgers; retries failed ones |
| `test_ack_pending_ledger_skips_invoice_creation` | **(Rev 3 new)** Ledger in ack_pending state when billing runs again | BillingRunItem.state=skipped, reason=already_billed; no new invoice created; existing invoice preserved |
| `test_ack_failed_ledger_skips_invoice_creation` | **(Rev 3 new)** Ledger in ack_failed state when billing runs again | BillingRunItem.state=skipped, reason=already_billed; invoice preserved; ack-retry cron handles recovery independently |
| `test_reversal_does_not_make_period_billable` | **(Rev 3 new)** Posted invoice reversed via _reverse_moves(); billing re-run | ledger.state remains succeeded; second billing attempt skipped; period NOT re-billed (T-24) |

---

## 10. `test_account_integration.py`

Verifies billing's correct use of Odoo accounting primitives.

> Makes real ORM calls in a `TransactionCase`. Tests the boundary — that billing calls the right methods with correct arguments and reads back correct results.

### Test cases

| Test ID | Verifies |
|---|---|
| `test_invoice_move_type` | `account.move.move_type == 'out_invoice'` |
| `test_invoice_partner` | `partner_id` from payload |
| `test_invoice_currency` | `currency_id` from payload |
| `test_invoice_fiscal_position` | `fiscal_position_id` from payload |
| `test_invoice_payment_term` | `payment_term_id` from payload; `invoice_date_due` computed |
| `test_invoice_lines_count` | Two-line subscription → two lines on invoice |
| `test_invoice_line_quantities` | Correct quantity and price_unit from payload |
| `test_price_unit_unmodified` | price_unit on invoice line equals payload price_unit exactly (T-14) |
| `test_invoice_posted` | `account.move.state == 'posted'` after billing |
| `test_tax_computed_by_odoo` | Product has 20% tax → tax lines present; amounts correct |
| `test_percentage_discount_on_line` | 10% reservation → `account.move.line.discount == 10.0` |
| `test_fixed_discount_proportional_allocation` | 15 EUR fixed reservation distributed across lines → per-line `discount` percentage calculated proportionally; native lines discounted without negative lines (T-16) |
| `test_custom_fields_set` | `x_subscription_id`, `x_billing_period_start`, `x_billing_period_end`, `x_billing_run_id`, `x_billing_ledger_id` all populated |
| `test_payment_state_not_paid` | Freshly posted: `payment_state == 'not_paid'` |
| `test_amount_residual_equals_total` | No payments: `amount_residual == amount_total` |
| `test_credit_note_via_reverse_moves` | Reversal via `_reverse_moves()` → `out_refund` created |
| `test_currency_rounding` | Sub-cent amounts rounded to currency precision by Odoo |

---

## 11. `test_member1_interface.py`

Tests the billing engine's behavior when Member 1's interface raises errors.

### Test cases

| Test ID | What raises | Effect on billing |
|---|---|---|
| `test_get_due_raises` | `get_subscriptions_due_for_billing` raises | BillingRun.state=failed; no items |
| `test_payload_validation_missing_partner` | Payload missing `partner_id` | BillingRunItem.state=failed; ledger.state=failed |
| `test_payload_validation_empty_lines` | Payload has no lines | BillingRunItem.state=failed |
| `test_payload_validation_invalid_frequency` | frequency='hourly' | BillingRunItem.state=failed |
| `test_subscription_inactive_between_stages` | Sub becomes inactive → payload raises | BillingRunItem.state=skipped; reason=inactive |
| `test_register_success_raises` | `register_billing_success` raises | Invoice IS committed and posted (external to savepoint); ledger.state=ack_failed; BillingRunItem.state=ack_failed; ack retry cron handles recovery (T-22, T-23) |
| `test_register_failure_raises_best_effort` | `register_billing_failure` raises | Error logged; billing continues to next subscription |
| `test_mock_records_success_calls` | Successful billing | `mock.success_calls` contains (sub_id, invoice_id, next_date) |
| `test_mock_records_failure_calls` | Failed billing | `mock.failure_calls` contains (sub_id, error_message, retry_at) |

---

## 12. Test Data Strategy

All test data is created programmatically in `setUpClass` or `setUp`. No XML demo data files. No dependence on Odoo's demo data (`--without-demo` must be compatible).

Minimal required fixtures:
- `res.partner` — test customer
- `product.product` — service product with a tax
- `account.journal` — customer invoices journal (found by search, not created)
- `account.tax` — 20% sales tax (created if not present)
- `subscriptiq.discount.rule` — one rule per test that needs it

---

## 13. Test Execution Reference

```bash
# Architecture reference — commands for when Odoo is installed in Docker

# Run all billing tests:
odoo-bin --test-enable --stop-after-init \
  -d test_subscriptiq \
  -i subscriptiq_billing \
  --test-tags subscriptiq_billing

# Run a single test class:
odoo-bin --test-enable --stop-after-init \
  -d test_subscriptiq \
  -i subscriptiq_billing \
  --test-tags /subscriptiq_billing/BillingLedgerTest

# Run period service tests only (pure Python — fastest):
odoo-bin --test-enable --stop-after-init \
  -d test_subscriptiq \
  -i subscriptiq_billing \
  --test-tags /subscriptiq_billing/PeriodServiceTest
```

---

## 14. Integration Test Scope (Integration Branch)

| Test | Members | Owner |
|---|---|---|
| Full billing cycle: real subscription → invoice posted | M1 + M2 | Integration branch |
| `register_billing_success` advances `next_billing_date` on real model | M1 + M2 | Integration branch |
| Idempotency: re-run does not rebill already-succeeded subscriptions | M1 + M2 | Integration branch |
| Portal displays correct invoices for portal user | M2 + M3 | Integration branch |
| Overdue invoice visible to admin in portal | M2 + M3 | Integration branch |

Member 2 maintains `MockSubscriptionService` in `tests/common.py` as the canonical interface contract reference. Member 1 can test their real service against it.

---

## 15. What Member 2 Must Not Test

| Do NOT test | Reason |
|---|---|
| Tax amount arithmetic | Odoo core |
| Journal entry debit/credit balance | Odoo core |
| `action_post()` internal mechanics | Odoo core |
| Payment reconciliation algorithm | Odoo core |
| Currency exchange rate application | Odoo core |
| `amount_residual` computation | Odoo core computed field |

Member 2 tests **that** these are invoked and **that** the results on the invoice match expectations — not **how** Odoo computes them internally.

---

## 16. Coverage Targets

| Module | Target |
|---|---|
| `billing_engine.py` | ≥ 90% |
| `acknowledgement_service.py` | ≥ 90% (critical — ack retry & recovery) |
| `discount_service.py` | ≥ 95% |
| `period_service.py` | 100% (pure functions, fully deterministic) |
| `billing_run.py` | ≥ 85% |
| `billing_ledger.py` | ≥ 90% (critical — idempotency backbone) |
| `discount_rule.py` | ≥ 80% |
| `discount_reservation.py` | ≥ 90% (critical — reservation lifecycle) |
| `account_move_extension.py` | ≥ 75% |
| `ack_retry_wizard.py` | ≥ 85% |

---

*Document revision 3 — testing strategy updated for Rev 3: savepoint-external acknowledgement, acknowledgement recovery test suite (`test_acknowledgement.py`), proportional fixed-discount allocation test suite (`test_discount_allocation.py`), six-state ledger machine, ack retry cron, posted invoice reversal policy, and disjoint cron domain verification. No tests implemented. Awaiting team review.*
