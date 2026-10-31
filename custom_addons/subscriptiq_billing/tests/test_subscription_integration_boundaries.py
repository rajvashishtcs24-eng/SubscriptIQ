# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch, MagicMock
from datetime import date
from .common import BillingTestCommon, make_payload
from ..services.billing_engine import BillingEngine
from ..services.subscription_adapter import SubscriptionAdapter


class TestSubscriptionIntegrationBoundaries(BillingTestCommon):
    """
    Validates integration boundaries between Member 1's subscription domain and Member 2's billing engine:
    - Immutable price snapshots vs mutable plan pricing.
    - Product variant representation.
    - Lifecycle state eligibility (active vs paused/closed).
    - Schedule enforcement (next_billing_date).
    """

    def setUp(self):
        super().setUp()
        self.billing_date = date(2026, 11, 1)

    def test_plan_price_modification_does_not_affect_existing_subscription_snapshot(self):
        """
        CRITICAL PRICING BOUNDARY:
        Subsequent changes to plan pricing must never alter an existing customer's agreed price snapshot.
        """
        # Customer purchased plan when price was 100.0
        agreed_price_snapshot = 100.0
        updated_plan_price = 150.0

        mock_sub = MagicMock()
        mock_sub.id = 901
        mock_sub.state = 'active'
        mock_sub.partner_id = self.partner
        mock_sub.currency_id = self.currency
        mock_sub.billing_frequency = 'monthly'
        mock_sub.next_billing_date = self.billing_date
        mock_sub.billing_day_anchor = 1

        # Subscription line carries customer-agreed snapshot
        mock_line = MagicMock()
        mock_line.configure_mock(name='Cloud Plan Pro (Agreed)')
        mock_line.product_id = self.product_a
        mock_line.quantity = 2.0
        mock_line.price_unit = agreed_price_snapshot
        mock_line.tax_ids = self.env['account.tax']
        mock_line.uom_id = False
        mock_sub.line_ids = [mock_line]

        mock_env = {
            'subscriptiq.subscription': MagicMock(
                browse=MagicMock(return_value=mock_sub),
                # No custom helper method so browse fallback runs
            )
        }
        del mock_env['subscriptiq.subscription'].get_billing_payload

        # Fetch payload via adapter
        payload = SubscriptionAdapter.get_billing_payload(mock_env, 901)
        self.assertEqual(len(payload['lines']), 1)
        # Billed price must be agreed snapshot (100.0), NOT new plan price (150.0)
        self.assertEqual(payload['lines'][0]['price_unit'], agreed_price_snapshot)
        self.assertNotEqual(payload['lines'][0]['price_unit'], updated_plan_price)

    def test_billing_uses_subscription_line_snapshot_for_invoice(self):
        """
        Ensures the generated account.move.line reflects the subscription line snapshot price.
        """
        customer_agreed_price = 85.0
        payload = make_payload(
            subscription_id=902,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[{
                'product_id': self.product_a.id,
                'name': 'Cloud SaaS Tier (Customer Agreed)',
                'quantity': 1.0,
                'price_unit': customer_agreed_price,
            }]
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[902]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success'):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 902)])
            self.assertTrue(ledger.invoice_id)
            invoice = ledger.invoice_id
            self.assertEqual(len(invoice.invoice_line_ids), 1)
            self.assertEqual(invoice.invoice_line_ids[0].price_unit, customer_agreed_price)
            self.assertEqual(invoice.amount_untaxed, 85.0)

    def test_product_variants_correctly_represented_in_invoice_lines(self):
        """
        Ensures variant-specific product IDs and variant names are placed onto invoice lines.
        """
        payload = make_payload(
            subscription_id=903,
            partner_id=self.partner.id,
            currency_id=self.currency.id,
            lines=[
                {
                    'product_id': self.product_a.id,
                    'name': 'Brightloop CRM — Standard Variant',
                    'quantity': 1.0,
                    'price_unit': 120.0,
                },
                {
                    'product_id': self.product_b.id,
                    'name': 'Brightloop CRM — Premium Storage Variant',
                    'quantity': 3.0,
                    'price_unit': 40.0,
                }
            ]
        )

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[903]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload), \
             patch.object(SubscriptionAdapter, 'register_billing_success'):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            ledger = self.env['subscriptiq.billing.ledger'].search([('subscription_id', '=', 903)])
            invoice = ledger.invoice_id

            lines = invoice.invoice_line_ids
            self.assertEqual(len(lines), 2)
            pids = {l.product_id.id for l in lines}
            self.assertIn(self.product_a.id, pids)
            self.assertIn(self.product_b.id, pids)
            self.assertEqual(invoice.amount_untaxed, 120.0 + (3 * 40.0))

    def test_billing_does_not_process_subscriptions_before_next_billing_date(self):
        """
        Subscriptions with next_billing_date > target_billing_date must be excluded.
        """
        mock_sub_model = MagicMock()
        mock_sub_model.search.return_value = MagicMock(ids=[])
        del mock_sub_model.get_subscriptions_due_for_billing

        mock_env = {'subscriptiq.subscription': mock_sub_model}

        due = SubscriptionAdapter.get_subscriptions_due_for_billing(mock_env, self.billing_date)
        self.assertEqual(due, [])

        # Check domain passed to search
        call_args = mock_sub_model.search.call_args[0][0]
        self.assertIn(('next_billing_date', '<=', self.billing_date), call_args)
        self.assertIn(('state', '=', 'active'), call_args)

    def test_paused_and_closed_subscriptions_excluded_from_billing(self):
        """
        Subscriptions that are paused, closed, or draft must never be invoiced.
        """
        mock_sub_paused = MagicMock(id=904, state='paused')
        mock_env_paused = {
            'subscriptiq.subscription': MagicMock(browse=MagicMock(return_value=mock_sub_paused))
        }
        del mock_env_paused['subscriptiq.subscription'].get_billing_payload

        with self.assertRaises(ValueError) as ctx:
            SubscriptionAdapter.get_billing_payload(mock_env_paused, 904)
        self.assertIn("non-billable state 'paused'", str(ctx.exception))

        mock_sub_closed = MagicMock(id=905, state='closed')
        mock_env_closed = {
            'subscriptiq.subscription': MagicMock(browse=MagicMock(return_value=mock_sub_closed))
        }
        del mock_env_closed['subscriptiq.subscription'].get_billing_payload

        with self.assertRaises(ValueError) as ctx:
            SubscriptionAdapter.get_billing_payload(mock_env_closed, 905)
        self.assertIn("non-billable state 'closed'", str(ctx.exception))
