# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date
from psycopg2 import IntegrityError
from odoo.tools import mute_logger
from .common import BillingTestCommon


class TestBillingLedger(BillingTestCommon):
    """
    Tests the six-state machine, idempotency, and retry metadata of BillingLedger.
    """

    def setUp(self):
        super().setUp()
        self.Ledger = self.env['subscriptiq.billing.ledger']
        self.period_start = date(2026, 11, 1)
        self.period_end = date(2026, 11, 30)

    def test_ledger_created_on_first_attempt(self):
        ledger = self.Ledger.create({
            'subscription_id': 201,
            'partner_id': self.partner.id,
            'billing_period_start': self.period_start,
            'billing_period_end': self.period_end,
            'state': 'pending',
        })
        self.assertEqual(ledger.state, 'pending')
        self.assertEqual(ledger.name, f"SUB-201/{self.period_start}")

    def test_ledger_uniqueness_constraint(self):
        """Duplicate entry for same sub + period must raise IntegrityError."""
        self.Ledger.create({
            'subscription_id': 202,
            'partner_id': self.partner.id,
            'billing_period_start': self.period_start,
            'billing_period_end': self.period_end,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.Ledger.create({
                'subscription_id': 202,
                'partner_id': self.partner.id,
                'billing_period_start': self.period_start,
                'billing_period_end': self.period_end,
            })

    def test_ledger_state_transitions(self):
        ledger = self.Ledger.create({
            'subscription_id': 203,
            'partner_id': self.partner.id,
            'billing_period_start': self.period_start,
            'billing_period_end': self.period_end,
            'state': 'pending',
        })
        # pending -> in_progress
        ledger.action_mark_in_progress()
        self.assertEqual(ledger.state, 'in_progress')
        self.assertTrue(ledger.first_attempted_at)

        # in_progress -> ack_pending
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.period_start,
        })
        ledger.action_mark_ack_pending(move.id)
        self.assertEqual(ledger.state, 'ack_pending')
        self.assertEqual(ledger.invoice_id.id, move.id)
        self.assertTrue(ledger.succeeded_at)

        # ack_pending -> succeeded
        ledger.action_mark_succeeded()
        self.assertEqual(ledger.state, 'succeeded')
        self.assertTrue(ledger.acknowledged_at)

    def test_ledger_invoice_failure_backoff(self):
        ledger = self.Ledger.create({
            'subscription_id': 204,
            'partner_id': self.partner.id,
            'billing_period_start': self.period_start,
            'billing_period_end': self.period_end,
            'state': 'in_progress',
        })
        ledger.action_mark_failed("Test DB failure")
        self.assertEqual(ledger.state, 'failed')
        self.assertEqual(ledger.retry_count, 1)
        self.assertTrue(ledger.next_retry_at)
        self.assertEqual(ledger.last_error_message, "Test DB failure")

    def test_ledger_ack_failure_state(self):
        ledger = self.Ledger.create({
            'subscription_id': 205,
            'partner_id': self.partner.id,
            'billing_period_start': self.period_start,
            'billing_period_end': self.period_end,
            'state': 'ack_pending',
        })
        ledger.action_mark_ack_failed("Member 1 network timeout")
        self.assertEqual(ledger.state, 'ack_failed')
        self.assertEqual(ledger.ack_retry_count, 1)
        self.assertTrue(ledger.ack_retry_at)
        self.assertEqual(ledger.ack_error_message, "Member 1 network timeout")
