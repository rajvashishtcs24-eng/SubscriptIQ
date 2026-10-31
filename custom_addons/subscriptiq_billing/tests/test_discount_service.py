# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
from .common import BillingTestCommon
from ..services.discount_service import DiscountService


class TestDiscountService(BillingTestCommon):
    """
    Tests rule selection, priority ordering, and eligibility criteria in DiscountService.
    """

    def setUp(self):
        super().setUp()
        self.Rule = self.env['subscriptiq.discount.rule']

    def test_no_rules_returns_none(self):
        rule = DiscountService.find_eligible_rule(
            self.env, self.partner.id, [{'product_id': self.product_a.id, 'quantity': 1, 'price_unit': 100}], date(2026, 11, 1)
        )
        self.assertIsNone(rule)

    def test_percentage_rule_eligible(self):
        r = self.Rule.create({
            'name': '10% Discount',
            'discount_type': 'percentage',
            'discount_value': 10.0,
            'priority': 10,
        })
        selected = DiscountService.find_eligible_rule(
            self.env, self.partner.id, [{'product_id': self.product_a.id, 'quantity': 1, 'price_unit': 100}], date(2026, 11, 1)
        )
        self.assertEqual(selected.id, r.id)

    def test_highest_priority_selected(self):
        r_low = self.Rule.create({
            'name': 'Low Priority (5%)',
            'discount_type': 'percentage',
            'discount_value': 5.0,
            'priority': 20,
        })
        r_high = self.Rule.create({
            'name': 'High Priority (15%)',
            'discount_type': 'percentage',
            'discount_value': 15.0,
            'priority': 5,
        })
        selected = DiscountService.find_eligible_rule(
            self.env, self.partner.id, [{'product_id': self.product_a.id, 'quantity': 1, 'price_unit': 100}], date(2026, 11, 1)
        )
        self.assertEqual(selected.id, r_high.id)

    def test_max_uses_reached(self):
        r = self.Rule.create({
            'name': 'One-time promo',
            'discount_type': 'percentage',
            'discount_value': 10.0,
            'max_uses': 1,
            'current_uses': 1,
        })
        selected = DiscountService.find_eligible_rule(
            self.env, self.partner.id, [{'product_id': self.product_a.id, 'quantity': 1, 'price_unit': 100}], date(2026, 11, 1)
        )
        self.assertIsNone(selected)

    def test_date_validity(self):
        r_expired = self.Rule.create({
            'name': 'Past Promo',
            'discount_type': 'percentage',
            'discount_value': 10.0,
            'date_end': date(2026, 10, 31),
        })
        selected = DiscountService.find_eligible_rule(
            self.env, self.partner.id, [{'product_id': self.product_a.id, 'quantity': 1, 'price_unit': 100}], date(2026, 11, 1)
        )
        self.assertIsNone(selected)
