# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
from .common import BillingTestCommon


class TestBillingRun(BillingTestCommon):
    """
    Tests BillingRun state machine, sequence numbering, and computed metrics.
    """

    def setUp(self):
        super().setUp()
        self.BillingRun = self.env['subscriptiq.billing.run']
        self.BillingRunItem = self.env['subscriptiq.billing.run.item']

    def test_sequence_generation(self):
        run = self.BillingRun.create({
            'billing_date': date(2026, 11, 1),
            'state': 'draft',
        })
        self.assertTrue(run.name.startswith('BRUN/'))

    def test_run_metrics_computation(self):
        run = self.BillingRun.create({
            'billing_date': date(2026, 11, 1),
            'state': 'running',
        })

        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date(2026, 11, 1),
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product_a.id,
                    'quantity': 2.0,
                    'price_unit': 100.0,
                })
            ],
        })
        move.action_post()

        # Item 1: Success with invoice
        self.BillingRunItem.create({
            'billing_run_id': run.id,
            'subscription_id': 301,
            'partner_id': self.partner.id,
            'state': 'success',
            'invoice_id': move.id,
        })
        # Item 2: Failed item
        self.BillingRunItem.create({
            'billing_run_id': run.id,
            'subscription_id': 302,
            'partner_id': self.partner.id,
            'state': 'failed',
            'error_message': 'Payment terms missing',
        })
        # Item 3: Ack Failed item
        self.BillingRunItem.create({
            'billing_run_id': run.id,
            'subscription_id': 303,
            'partner_id': self.partner.id,
            'state': 'ack_failed',
            'invoice_id': move.id,
        })

        run.action_finish()
        self.assertEqual(run.subscription_count, 3)
        self.assertEqual(run.invoice_count, 2)
        self.assertEqual(run.failure_count, 1)
        self.assertEqual(run.ack_failure_count, 1)
        self.assertEqual(run.state, 'partial')
        self.assertGreater(run.total_billed, 0.0)
