# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
from .common import BillingTestCommon


class TestAccountIntegration(BillingTestCommon):
    """
    Verifies that billing correctly leverages native Odoo 19 accounting models and workflows.
    """

    def setUp(self):
        super().setUp()
        self.invoice_date = date(2026, 11, 1)

    def test_invoice_creation_and_posting(self):
        """Creates and posts an invoice verifying custom subscription fields and native posting."""
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.invoice_date,
            'x_subscription_id': 701,
            'x_billing_period_start': self.invoice_date,
            'x_billing_period_end': date(2026, 11, 30),
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product_a.id,
                    'name': 'Subscription Tier Alpha',
                    'quantity': 1.0,
                    'price_unit': 150.0,
                    'discount': 10.0,
                })
            ],
        })

        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.x_subscription_id, 701)

        # Post invoice
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.payment_state, 'not_paid')
        self.assertEqual(move.amount_untaxed, 135.0)  # 150 - 10%
        self.assertEqual(move.amount_residual, move.amount_total)

    def test_credit_note_reversal_workflow(self):
        """Reversing an invoice creates an out_refund move preserving original invoice."""
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.invoice_date,
            'x_subscription_id': 702,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product_a.id,
                    'quantity': 1.0,
                    'price_unit': 100.0,
                })
            ],
        })
        move.action_post()

        reverse_move = move._reverse_moves()
        self.assertEqual(reverse_move.move_type, 'out_refund')
        self.assertEqual(move.state, 'posted')
