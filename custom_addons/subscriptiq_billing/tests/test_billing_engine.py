# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch
from datetime import date
from .common import BillingTestCommon, make_payload
from ..services.billing_engine import BillingEngine
from ..services.subscription_adapter import SubscriptionAdapter


class TestBillingEngine(BillingTestCommon):
    """
    End-to-end tests for the 16-stage BillingEngine pipeline.
    """

    def setUp(self):
        super().setUp()
        self.billing_date = date(2026, 11, 1)

    def test_single_subscription_success(self):
        """Standard success path with invoice generation, posting, and acknowledgement."""
        payload = make_payload(
            subscription_id=401,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': self.product_a.id, 'quantity': 1.0, 'price_unit': 100.0}],
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[401]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success') as mock_ack:

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)

            self.assertEqual(run.state, 'done')
            self.assertEqual(run.invoice_count, 1)
            self.assertEqual(run.failure_count, 0)
            mock_ack.assert_called_once()

            # Verify ledger state
            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 401)])
            self.assertTrue(ledger)
            self.assertEqual(ledger.state, 'succeeded')
            self.assertTrue(ledger.invoice_id)
            self.assertEqual(ledger.invoice_id.state, 'posted')

    def test_ack_failure_preserves_invoice(self):
        """
        Critical Rev 3 requirement (T-22, T-23):
        If register_billing_success fails, the invoice MUST NOT be rolled back.
        The ledger transitions to ack_failed.
        """
        payload = make_payload(
            subscription_id=402,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': self.product_a.id, 'quantity': 1.0, 'price_unit': 100.0}],
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[402]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success', side_effect=RuntimeError("M1 API unreachable")):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)

            # Run state should be partial because ack failed
            self.assertEqual(run.state, 'partial')
            self.assertEqual(run.invoice_count, 1)
            self.assertEqual(run.ack_failure_count, 1)

            # Check that invoice IS posted and preserved
            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 402)])
            self.assertTrue(ledger)
            self.assertEqual(ledger.state, 'ack_failed')
            self.assertTrue(ledger.invoice_id)
            self.assertEqual(ledger.invoice_id.state, 'posted')
            self.assertIn("M1 API unreachable", ledger.ack_error_message)

    def test_invoice_creation_failure_rolls_back(self):
        """If invoice creation fails, savepoint rolls back and ledger becomes failed."""
        payload = make_payload(
            subscription_id=403,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{'product_id': False, 'quantity': 1.0, 'price_unit': 100.0}],  # Invalid product_id
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[403]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)

            self.assertEqual(run.state, 'failed')
            self.assertEqual(run.invoice_count, 0)
            self.assertEqual(run.failure_count, 1)

            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 403)])
            self.assertTrue(ledger)
            self.assertEqual(ledger.state, 'failed')
            self.assertFalse(ledger.invoice_id)
