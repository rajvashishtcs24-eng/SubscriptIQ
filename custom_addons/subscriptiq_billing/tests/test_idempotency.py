# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch
from datetime import date
from .common import BillingTestCommon, make_payload
from ..services.billing_engine import BillingEngine
from ..services.subscription_adapter import SubscriptionAdapter


class TestIdempotency(BillingTestCommon):
    """
    Tests end-to-end duplicate invoice prevention, idempotency safeguards, and reversal behavior.
    """

    def setUp(self):
        super().setUp()
        self.billing_date = date(2026, 11, 1)

    def test_no_duplicate_same_period(self):
        """Re-running billing for an already succeeded subscription period must skip without creating an invoice."""
        payload = make_payload(
            subscription_id=601,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': self.product_a.id, 'quantity': 1.0, 'price_unit': 100.0}],
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[601]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success'):

            # First run: creates invoice
            run1 = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            self.assertEqual(run1.invoice_count, 1)

            # Second run: must skip
            run2 = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            self.assertEqual(run2.invoice_count, 0)
            self.assertEqual(run2.skipped_count, 1)

            item = run2.item_ids.filtered(lambda i: i.subscription_id == 601)
            self.assertEqual(item.skip_reason, 'already_billed')

    def test_ack_pending_skips_invoice_creation(self):
        """Ledger in ack_pending state must not create a duplicate invoice."""
        payload = make_payload(
            subscription_id=602,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': self.product_a.id, 'quantity': 1.0, 'price_unit': 100.0}],
        )

        # Pre-seed ledger in ack_pending
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.billing_date,
        })
        self.env['subscriptiq.billing.ledger'].create({
            'subscription_id': 602,
            'partner_id': self.partner.id,
            'billing_period_start': self.billing_date,
            'billing_period_end': date(2026, 11, 30),
            'state': 'ack_pending',
            'invoice_id': move.id,
        })

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[602]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            self.assertEqual(run.invoice_count, 0)
            self.assertEqual(run.skipped_count, 1)

    def test_reversal_does_not_make_period_billable(self):
        """
        Reversing a posted invoice via _reverse_moves creates a credit note
        but leaves the billing ledger in succeeded, preventing automatic rebilling (T-24).
        """
        payload = make_payload(
            subscription_id=603,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': self.product_a.id, 'quantity': 1.0, 'price_unit': 100.0}],
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[603]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success'):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 603)])
            self.assertEqual(ledger.state, 'succeeded')

            # Reverse the invoice
            invoice = ledger.invoice_id
            reversal = invoice._reverse_moves()
            self.assertTrue(reversal)
            self.assertEqual(reversal.move_type, 'out_refund')

            # Ledger remains succeeded
            self.assertEqual(ledger.state, 'succeeded')
