# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import unittest
from ..services.discount_service import DiscountService


class MockCurrency:
    """Mock currency implementing round() with 2 decimal precision."""
    def round(self, amount):
        return round(amount, 2)


class TestDiscountAllocation(unittest.TestCase):
    """
    Unit tests for the 11-step Rev 3 proportional fixed-discount allocation algorithm.
    """

    def setUp(self):
        self.currency = MockCurrency()

    def test_single_eligible_line_full_discount(self):
        """20 EUR fixed discount on 1 line of 100 EUR -> 20% discount."""
        lines = [{'product_id': 1, 'quantity': 1.0, 'price_unit': 100.0}]
        res = DiscountService.allocate_fixed_discount(lines, 20.0, self.currency)
        self.assertAlmostEqual(res[0]['discount'], 20.0, places=2)
        self.assertEqual(res[0]['price_unit'], 100.0)  # Price unit unmodified

    def test_two_equal_lines_split_evenly(self):
        """20 EUR discount on two lines each 100 EUR -> 10% each (10 EUR each)."""
        lines = [
            {'product_id': 1, 'quantity': 1.0, 'price_unit': 100.0},
            {'product_id': 2, 'quantity': 1.0, 'price_unit': 100.0},
        ]
        res = DiscountService.allocate_fixed_discount(lines, 20.0, self.currency)
        self.assertAlmostEqual(res[0]['discount'], 10.0, places=2)
        self.assertAlmostEqual(res[1]['discount'], 10.0, places=2)

    def test_two_unequal_lines_proportional(self):
        """30 EUR discount, line A subtotal 60, line B subtotal 40 -> 30% each."""
        lines = [
            {'product_id': 1, 'quantity': 1.0, 'price_unit': 60.0},
            {'product_id': 2, 'quantity': 1.0, 'price_unit': 40.0},
        ]
        res = DiscountService.allocate_fixed_discount(lines, 30.0, self.currency)
        self.assertAlmostEqual(res[0]['discount'], 30.0, places=2)
        self.assertAlmostEqual(res[1]['discount'], 30.0, places=2)

    def test_rounding_remainder_allocated_to_first_eligible_line(self):
        """10 EUR discount across 3 equal lines of 33.33 EUR each."""
        lines = [
            {'product_id': 1, 'quantity': 1.0, 'price_unit': 33.33},
            {'product_id': 2, 'quantity': 1.0, 'price_unit': 33.33},
            {'product_id': 3, 'quantity': 1.0, 'price_unit': 33.33},
        ]
        res = DiscountService.allocate_fixed_discount(lines, 10.0, self.currency)
        # S_total = 99.99, raw_alloc = 10 * (33.33 / 99.99) = 3.33333 -> round 3.33
        # allocated_total = 9.99 -> remainder = 0.01 -> added to line 0 (3.34)
        alloc_0 = (res[0]['discount'] / 100.0) * lines[0]['price_unit']
        alloc_1 = (res[1]['discount'] / 100.0) * lines[1]['price_unit']
        alloc_2 = (res[2]['discount'] / 100.0) * lines[2]['price_unit']
        self.assertAlmostEqual(alloc_0 + alloc_1 + alloc_2, 10.0, places=2)
        self.assertGreater(res[0]['discount'], res[1]['discount'])

    def test_zero_total_eligible_releases_reservation(self):
        """Zero subtotal lines must result in zero discount applied."""
        lines = [{'product_id': 1, 'quantity': 0.0, 'price_unit': 100.0}]
        res = DiscountService.allocate_fixed_discount(lines, 15.0, self.currency)
        self.assertEqual(res[0]['discount'], 0.0)

    def test_ineligible_lines_excluded_from_split(self):
        """Rule restricted to product 1: product 2 must remain at 0% discount."""
        lines = [
            {'product_id': 1, 'quantity': 1.0, 'price_unit': 100.0},
            {'product_id': 2, 'quantity': 1.0, 'price_unit': 50.0},
        ]
        res = DiscountService.allocate_fixed_discount(lines, 20.0, self.currency, rule_product_ids={1})
        self.assertAlmostEqual(res[0]['discount'], 20.0, places=2)
        self.assertEqual(res[1]['discount'], 0.0)

    def test_zero_value_line_excluded(self):
        """Zero value lines are excluded from denominator and receive 0% discount."""
        lines = [
            {'product_id': 1, 'quantity': 1.0, 'price_unit': 0.0},
            {'product_id': 2, 'quantity': 1.0, 'price_unit': 100.0},
        ]
        res = DiscountService.allocate_fixed_discount(lines, 20.0, self.currency)
        self.assertEqual(res[0]['discount'], 0.0)
        self.assertAlmostEqual(res[1]['discount'], 20.0, places=2)

    def test_discount_exceeds_line_subtotal(self):
        """200 EUR fixed discount on 100 EUR line is clamped to 100% discount."""
        lines = [{'product_id': 1, 'quantity': 1.0, 'price_unit': 100.0}]
        res = DiscountService.allocate_fixed_discount(lines, 200.0, self.currency)
        self.assertEqual(res[0]['discount'], 100.0)
