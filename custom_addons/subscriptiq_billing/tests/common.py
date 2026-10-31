# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
try:
    from odoo.tests.common import TransactionCase
except ImportError:
    import unittest
    TransactionCase = unittest.TestCase


class MockSubscriptionService:
    """
    Mock of Member 1's subscriptiq.subscription ORM interface for isolated testing.
    """
    def __init__(self):
        self.subscriptions_to_return = []
        self.payloads = {}
        self.fail_payload_for = set()
        self.fail_register_success_for = set()
        self.register_failure_raises = False

        self.success_calls = []
        self.failure_calls = []

    def get_subscriptions_due_for_billing(self, billing_date):
        return list(self.subscriptions_to_return)

    def get_billing_payload(self, subscription_id):
        if subscription_id in self.fail_payload_for:
            raise ValueError(f"Mock error retrieving payload for subscription {subscription_id}")
        return self.payloads.get(subscription_id, make_payload(subscription_id=subscription_id))

    def register_billing_success(self, subscription_id, invoice_id, next_billing_date):
        if subscription_id in self.fail_register_success_for:
            raise RuntimeError(f"Mock failure in register_billing_success for sub {subscription_id}")
        self.success_calls.append((subscription_id, invoice_id, next_billing_date))

    def register_billing_failure(self, subscription_id, error_message, retry_at):
        if self.register_failure_raises:
            raise RuntimeError("Mock failure in register_billing_failure")
        self.failure_calls.append((subscription_id, error_message, retry_at))


def make_payload(
    subscription_id: int = 1,
    partner_id: int = 10,
    currency_id: int = 1,
    frequency: str = 'monthly',
    next_billing_date: date = None,
    day_anchor: int = 1,
    lines: list = None,
) -> dict:
    """Constructs a standard, valid billing payload."""
    if not next_billing_date:
        next_billing_date = date(2026, 11, 1)

    if lines is None:
        lines = [
            {
                'product_id': 101,
                'name': 'Cloud SaaS Pro',
                'quantity': 1.0,
                'price_unit': 100.0,
                'tax_ids': [],
                'uom_id': 1,
            }
        ]

    return {
        'subscription_id': subscription_id,
        'partner_id': partner_id,
        'currency_id': currency_id,
        'fiscal_position_id': False,
        'payment_term_id': False,
        'next_billing_date': next_billing_date,
        'billing_frequency': frequency,
        'billing_day_anchor': day_anchor,
        'lines': lines,
    }


class BillingTestCommon(TransactionCase):
    """
    Base test class for Odoo transaction tests.
    Sets up common test records: company, partner, products, and default config.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if hasattr(cls, 'env'):
            cls.company = cls.env.company
            cls.currency = cls.company.currency_id
            cls.partner = cls.env['res.partner'].create({
                'name': 'Test Subscriber Inc',
                'email': 'subscriber@example.com',
            })
            cls.product_a = cls.env['product.product'].create({
                'name': 'Standard Subscription Tier',
                'type': 'service',
                'list_price': 100.0,
            })
            cls.product_b = cls.env['product.product'].create({
                'name': 'Add-on Storage Pack',
                'type': 'service',
                'list_price': 50.0,
            })
            cls.mock_sub_service = MockSubscriptionService()
