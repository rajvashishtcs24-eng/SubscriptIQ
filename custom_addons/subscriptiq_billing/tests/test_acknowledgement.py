# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch
from datetime import date
from .common import BillingTestCommon
from ..services.acknowledgement_service import AcknowledgementService
from ..services.subscription_adapter import SubscriptionAdapter


class TestAcknowledgement(BillingTestCommon):
    """
    Tests AcknowledgementService and ir_cron_ack_retry behavior.
    """

    def setUp(self):
        super().setUp()
        self.Ledger = self.env['subscriptiq.billing.ledger']
        self.move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date(2026, 11, 1),
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product_a.id,
                    'quantity': 1.0,
                    'price_unit': 100.0,
                })
            ],
        })
        self.move.action_post()

    def test_ack_retry_succeeds_sets_succeeded(self):
        """Ack retry picks up ack_failed ledger and marks it succeeded upon success."""
        ledger = self.Ledger.create({
            'subscription_id': 501,
            'partner_id': self.partner.id,
            'billing_period_start': date(2026, 11, 1),
            'billing_period_end': date(2026, 11, 30),
            'state': 'ack_failed',
            'invoice_id': self.move.id,
            'ack_retry_count': 1,
        })

        with patch.object(SubscriptionAdapter, 'register_billing_success') as mock_ack:
            count = AcknowledgementService.retry_acknowledgement(self.env, ledger_ids=[ledger.id])
            self.assertEqual(count, 1)
            mock_ack.assert_called_once()
            self.assertEqual(ledger.state, 'succeeded')
            self.assertTrue(ledger.acknowledged_at)
            # Verify invoice is unchanged
            self.assertEqual(ledger.invoice_id.id, self.move.id)

    def test_ack_retry_failure_increments_count(self):
        """Ack retry increments ack_retry_count and updates ack_error_message on failure."""
        ledger = self.Ledger.create({
            'subscription_id': 502,
            'partner_id': self.partner.id,
            'billing_period_start': date(2026, 11, 1),
            'billing_period_end': date(2026, 11, 30),
            'state': 'ack_failed',
            'invoice_id': self.move.id,
            'ack_retry_count': 1,
        })

        with patch.object(SubscriptionAdapter, 'register_billing_success', side_effect=RuntimeError("Still offline")):
            count = AcknowledgementService.retry_acknowledgement(self.env, ledger_ids=[ledger.id])
            self.assertEqual(count, 0)
            self.assertEqual(ledger.state, 'ack_failed')
            self.assertEqual(ledger.ack_retry_count, 2)
            self.assertIn("Still offline", ledger.ack_error_message)

    def test_ack_retry_does_not_create_new_invoice(self):
        """Ensures ack retry never creates a duplicate account.move."""
        initial_invoice_count = self.env['account.move'].search_count([])
        ledger = self.Ledger.create({
            'subscription_id': 503,
            'partner_id': self.partner.id,
            'billing_period_start': date(2026, 11, 1),
            'billing_period_end': date(2026, 11, 30),
            'state': 'ack_pending',
            'invoice_id': self.move.id,
        })

        with patch.object(SubscriptionAdapter, 'register_billing_success'):
            AcknowledgementService.retry_acknowledgement(self.env, ledger_ids=[ledger.id])
            final_invoice_count = self.env['account.move'].search_count([])
            self.assertEqual(initial_invoice_count, final_invoice_count)
