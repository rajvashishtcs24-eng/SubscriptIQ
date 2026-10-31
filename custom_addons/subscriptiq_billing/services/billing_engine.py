# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import time
import logging
from datetime import timedelta
from odoo import fields, _
from odoo.exceptions import UserError

from .period_service import PeriodService
from .discount_service import DiscountService
from .subscription_adapter import SubscriptionAdapter
from .acknowledgement_service import AcknowledgementService

_logger = logging.getLogger(__name__)


class BillingEngine:
    """
    Orchestrates the 16-stage recurring billing lifecycle for SubscriptIQ.
    Enforces transaction savepoint isolation for invoice generation and
    external execution for post-invoice acknowledgement recovery.
    """

    @classmethod
    def _acquire_advisory_lock(cls, env, lock_key: int) -> bool:
        """Attempts to acquire a PostgreSQL session-level advisory lock."""
        try:
            env.cr.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
            res = env.cr.fetchone()
            return bool(res and res[0])
        except Exception as e:
            _logger.warning("Failed to execute pg_try_advisory_lock: %s", e)
            return True  # Fallback for environments where advisory locks are mocked or restricted

    @classmethod
    def _release_advisory_lock(cls, env, lock_key: int) -> None:
        """Releases the PostgreSQL session-level advisory lock."""
        try:
            env.cr.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
        except Exception as e:
            _logger.warning("Failed to execute pg_advisory_unlock: %s", e)

    @classmethod
    def execute_run(
        cls,
        env,
        billing_date=None,
        triggered_by: str = 'cron',
        user_id: int = None,
        subscription_ids=None,
    ):
        """
        Main entry point for executing a billing run.
        Called by ir_cron_billing_engine or the manual run wizard.
        """
        params = env['ir.config_parameter'].sudo()
        lock_key = int(params.get_param('subscriptiq_billing.billing_pg_lock_key', 1001))
        batch_size = int(params.get_param('subscriptiq_billing.billing_batch_size', 100))

        if not billing_date:
            billing_date = fields.Date.context_today(env.user)

        # STAGE 1: INITIATE RUN & ACQUIRE LOCK
        lock_acquired = cls._acquire_advisory_lock(env, lock_key)
        if not lock_acquired:
            _logger.warning("Billing run already in progress (advisory lock %s held). Aborting.", lock_key)
            return False

        run = env['subscriptiq.billing.run'].create({
            'billing_date': billing_date,
            'triggered_by': triggered_by,
            'triggered_by_user_id': user_id or env.user.id,
            'state': 'running',
            'run_date': fields.Datetime.now(),
        })
        _logger.info("Initiated BillingRun %s (ID: %s, date: %s)", run.name, run.id, billing_date)

        try:
            # STAGE 2: FETCH ELIGIBLE SUBSCRIPTIONS
            if subscription_ids is None:
                try:
                    subscription_ids = SubscriptionAdapter.get_subscriptions_due_for_billing(env, billing_date)
                except Exception as exc:
                    _logger.exception("Failed to fetch subscriptions due for billing: %s", exc)
                    run.write({
                        'state': 'failed',
                        'error_message': f"Fetch failed: {exc}",
                        'run_end_datetime': fields.Datetime.now(),
                    })
                    return run

            if not subscription_ids:
                _logger.info("No subscriptions due for billing on %s.", billing_date)
                run.write({
                    'state': 'done',
                    'run_end_datetime': fields.Datetime.now(),
                })
                return run

            # STAGE 3: PER-SUBSCRIPTION PROCESSING LOOP
            processed_count = 0
            for sub_id in subscription_ids:
                cls._process_single_subscription(env, run, sub_id, billing_date)
                processed_count += 1

                # STAGE 4: BATCH COMMIT
                if processed_count % batch_size == 0:
                    try:
                        env.cr.commit()
                    except Exception as commit_err:
                        _logger.warning("Batch commit at count %d encountered: %s", processed_count, commit_err)

            # STAGE 5: FINALISE RUN
            run.action_finish()
            _logger.info(
                "BillingRun %s finished. State: %s (Invoices: %d, Failures: %d, AckFailures: %d, Total: %s)",
                run.name, run.state, run.invoice_count, run.failure_count, run.ack_failure_count, run.total_billed
            )

        finally:
            cls._release_advisory_lock(env, lock_key)

        return run

    @classmethod
    def _process_single_subscription(cls, env, run, subscription_id: int, billing_date):
        """
        Executes stages 3.1 to 3.11 for a single subscription.
        Uses savepoint isolation for invoice generation and handles external acknowledgement.
        """
        start_time = time.time()
        item = env['subscriptiq.billing.run.item'].create({
            'billing_run_id': run.id,
            'subscription_id': subscription_id,
            'state': 'pending',
        })

        savepoint_name = f"subscriptiq_sub_{subscription_id}_{int(start_time * 1000) % 100000}"
        savepoint_active = False

        invoice = None
        ledger = None
        computed_next_date = None

        try:
            env.cr.execute(f"SAVEPOINT {savepoint_name}")
            savepoint_active = True

            # STAGE 3.1: LOAD AND VALIDATE PAYLOAD
            try:
                payload = SubscriptionAdapter.get_billing_payload(env, subscription_id)
            except Exception as payload_err:
                _logger.warning("Failed to load payload for sub %s: %s", subscription_id, payload_err)
                item.write({
                    'state': 'skipped',
                    'skip_reason': 'payload_error',
                    'error_message': str(payload_err),
                })
                env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                savepoint_active = False
                return

            partner_id = payload.get('partner_id')
            currency_id = payload.get('currency_id') or env.company.currency_id.id
            frequency = payload.get('billing_frequency', 'monthly')
            lines = payload.get('lines', [])
            day_anchor = payload.get('billing_day_anchor') or (billing_date.day if billing_date else 1)

            if not partner_id or not lines:
                raise ValueError("Payload missing required partner_id or has empty lines.")

            item.partner_id = partner_id

            # STAGE 3.2: COMPUTE BILLING PERIOD
            period_start, period_end, computed_next_date = PeriodService.compute_period(
                frequency, billing_date, day_anchor
            )
            item.write({
                'billing_period_start': period_start,
                'billing_period_end': period_end,
            })

            # STAGE 3.3: FIND OR CREATE BILLING LEDGER (IDEMPOTENCY ANCHOR)
            LedgerModel = env['subscriptiq.billing.ledger']
            ledger = LedgerModel.search([
                ('subscription_id', '=', subscription_id),
                ('billing_period_start', '=', period_start),
                ('billing_period_end', '=', period_end),
            ], limit=1)

            if ledger:
                if ledger.state == 'succeeded':
                    item.write({'state': 'skipped', 'skip_reason': 'already_billed'})
                    env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                    savepoint_active = False
                    return
                elif ledger.state in ('ack_pending', 'ack_failed'):
                    # Invoice is already posted! Skip invoice creation and proceed to acknowledgement
                    item.write({
                        'state': 'skipped',
                        'skip_reason': 'already_billed',
                        'invoice_id': ledger.invoice_id.id if ledger.invoice_id else False,
                    })
                    env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                    savepoint_active = False
                    return
                elif ledger.state == 'processing':
                    item.write({'state': 'skipped', 'skip_reason': 'concurrent'})
                    env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                    savepoint_active = False
                    return
            else:
                max_retries = int(env['ir.config_parameter'].sudo().get_param('subscriptiq_billing.billing_max_retries', 3))
                ledger = LedgerModel.create({
                    'subscription_id': subscription_id,
                    'partner_id': partner_id,
                    'billing_period_start': period_start,
                    'billing_period_end': period_end,
                    'billing_frequency': frequency,
                    'billing_run_id': run.id,
                    'max_retries': max_retries,
                    'state': 'pending',
                })

            item.billing_ledger_id = ledger.id

            # STAGE 3.4: MARK LEDGER PROCESSING
            ledger.action_mark_processing()

            # STAGE 3.5: EVALUATE AND RESERVE DISCOUNT (NO STACKING — T-14)
            total_untaxed = sum(l.get('price_unit', 0.0) * l.get('quantity', 0.0) for l in lines)
            eligible_rule = DiscountService.find_eligible_rule(
                env, partner_id, lines, billing_date, total_untaxed, subscription_id
            )

            reservation = None
            if eligible_rule:
                reservation = env['subscriptiq.discount.reservation'].create({
                    'discount_rule_id': eligible_rule.id,
                    'billing_ledger_id': ledger.id,
                    'discount_type': eligible_rule.discount_type,
                    'discount_value': eligible_rule.discount_value,
                    'currency_id': eligible_rule.currency_id.id if eligible_rule.currency_id else False,
                    'state': 'reserved',
                })
                ledger.discount_reservation_id = reservation.id

            # STAGE 3.6: BUILD INVOICE LINES WITH DISCOUNT (T-13, T-16)
            currency = env['res.currency'].browse(currency_id)
            invoice_lines_data = []
            for l in lines:
                invoice_lines_data.append({
                    'product_id': l['product_id'],
                    'name': l.get('name') or 'Subscription Service',
                    'quantity': l.get('quantity', 1.0),
                    'price_unit': l.get('price_unit', 0.0),  # NEVER modified (T-13)
                    'tax_ids': [(6, 0, l.get('tax_ids', []))],
                    'discount': 0.0,
                })

            if reservation:
                if reservation.discount_type == 'percentage':
                    for l_data in invoice_lines_data:
                        l_data['discount'] = reservation.discount_value
                elif reservation.discount_type == 'fixed':
                    rule_pids = set(eligible_rule.product_ids.ids) if eligible_rule.product_ids else None
                    DiscountService.allocate_fixed_discount(
                        invoice_lines_data, reservation.discount_value, currency, rule_pids
                    )

            # STAGE 3.7: CREATE INVOICE
            journal = env['account.journal'].search([('type', '=', 'sale')], limit=1)
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': partner_id,
                'currency_id': currency_id,
                'invoice_date': billing_date,
                'x_subscription_id': subscription_id,
                'x_billing_period_start': period_start,
                'x_billing_period_end': period_end,
                'x_billing_run_id': run.id,
                'x_billing_ledger_id': ledger.id,
                'invoice_line_ids': [(0, 0, l_data) for l_data in invoice_lines_data],
            }
            if journal:
                invoice_vals['journal_id'] = journal.id
            if payload.get('fiscal_position_id'):
                invoice_vals['fiscal_position_id'] = payload['fiscal_position_id']
            if payload.get('payment_term_id'):
                invoice_vals['invoice_payment_term_id'] = payload['payment_term_id']

            invoice = env['account.move'].create(invoice_vals)
            ledger.draft_invoice_id = invoice.id

            # STAGE 3.8: POST INVOICE
            invoice.action_post()

            # STAGE 3.9: CONSUME DISCOUNT RESERVATION
            if reservation:
                reservation.action_consume()

            # STAGE 3.10: COMMIT SAVEPOINT (INVOICE COMMITTED AND POSTED)
            ledger.action_mark_ack_pending(invoice.id)
            item.invoice_id = invoice.id

            env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            savepoint_active = False

        except Exception as inv_err:
            _logger.exception("Invoice creation/posting failed for sub %s: %s", subscription_id, inv_err)
            if savepoint_active:
                env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                savepoint_active = False

            if ledger:
                ledger.action_mark_failed(str(inv_err))
            item.write({
                'state': 'failed',
                'error_message': str(inv_err),
            })
            SubscriptionAdapter.register_billing_failure(
                env, subscription_id, str(inv_err), ledger.next_retry_at if ledger else False
            )
            return

        # STAGE 3.11: ACKNOWLEDGE MEMBER 1 (OUTSIDE INVOICE SAVEPOINT — T-22, T-23)
        try:
            SubscriptionAdapter.register_billing_success(
                env, subscription_id, invoice.id, computed_next_date
            )
            ledger.action_mark_succeeded()
            item.write({'state': 'success'})
        except Exception as ack_err:
            _logger.warning(
                "Post-invoice acknowledgement failed for sub %s (invoice %s preserved): %s",
                subscription_id, invoice.id, ack_err
            )
            ledger.action_mark_ack_failed(str(ack_err))
            item.write({
                'state': 'ack_failed',
                'ack_error_message': str(ack_err),
            })

        duration_ms = int((time.time() - start_time) * 1000)
        item.processing_duration_ms = duration_ms

    @classmethod
    def retry_failed_ledgers(cls, env, batch_size=100) -> int:
        """
        Processes failed ledgers due for invoice retry.
        Called by ir_cron_billing_retry.
        Domain is strictly disjoint from acknowledgement retry.
        """
        now = fields.Datetime.now()
        domain = [
            ('state', '=', 'failed'),
            ('invoice_id', '=', False),
            ('next_retry_at', '<=', now),
            ('next_retry_at', '!=', False),
        ]
        failed_ledgers = env['subscriptiq.billing.ledger'].search(domain, limit=batch_size)
        if not failed_ledgers:
            return 0

        _logger.info("Found %d failed ledgers eligible for invoice retry.", len(failed_ledgers))
        retry_run = env['subscriptiq.billing.run'].create({
            'billing_date': fields.Date.context_today(env.user),
            'triggered_by': 'cron',
            'state': 'running',
            'run_date': fields.Datetime.now(),
            'notes': _("Automated Invoice Retry Run"),
        })

        for ledger in failed_ledgers:
            cls._process_single_subscription(
                env, retry_run, ledger.subscription_id, ledger.billing_period_start
            )

        retry_run.action_finish()
        return len(failed_ledgers)
