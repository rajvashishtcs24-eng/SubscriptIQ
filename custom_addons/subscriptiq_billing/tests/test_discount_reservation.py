# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
from .common import BillingTestCommon


class TestDiscountReservation(BillingTestCommon):
    """
    Tests discount reservation state lifecycle: reserved -> consumed | released.
    """

    def setUp(self):
        super().setUp()
        self.Rule = self.env['subscriptiq.discount.rule']
        self.Reservation = self.env['subscriptiq.discount.reservation']
        self.Ledger = self.env['subscriptiq.billing.ledger']

        self.rule = self.Rule.create({
            'name': '10% Launch Special',
            'discount_type': 'percentage',
            'discount_value': 10.0,
            'max_uses': 5,
        })
        self.ledger = self.Ledger.create({
            'subscription_id': 101,
            'partner_id': self.partner.id,
            'billing_period_start': date(2026, 11, 1),
            'billing_period_end': date(2026, 11, 30),
            'state': 'processing',
        })

    def test_reservation_snapshots_values(self):
        res = self.Reservation.create({
            'discount_rule_id': self.rule.id,
            'billing_ledger_id': self.ledger.id,
            'discount_type': self.rule.discount_type,
            'discount_value': self.rule.discount_value,
            'state': 'reserved',
        })
        self.assertEqual(res.discount_value, 10.0)
        self.assertEqual(res.state, 'reserved')

        # Rule modification does not alter snapshot
        self.rule.write({'discount_value': 20.0})
        self.assertEqual(res.discount_value, 10.0)

    def test_reservation_consumed_increments_uses(self):
        res = self.Reservation.create({
            'discount_rule_id': self.rule.id,
            'billing_ledger_id': self.ledger.id,
            'discount_type': self.rule.discount_type,
            'discount_value': self.rule.discount_value,
            'state': 'reserved',
        })
        self.assertEqual(self.rule.current_uses, 0)
        res.action_consume()
        self.assertEqual(res.state, 'consumed')
        self.assertEqual(self.rule.current_uses, 1)

    def test_reservation_released_does_not_increment_uses(self):
        res = self.Reservation.create({
            'discount_rule_id': self.rule.id,
            'billing_ledger_id': self.ledger.id,
            'discount_type': self.rule.discount_type,
            'discount_value': self.rule.discount_value,
            'state': 'reserved',
        })
        res.action_release()
        self.assertEqual(res.state, 'released')
        self.assertEqual(self.rule.current_uses, 0)
