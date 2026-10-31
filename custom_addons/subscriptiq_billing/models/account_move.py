# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """
    Extends native account.move to track subscription billing periods, runs, and ledger idempotency.
    All native accounting mechanics (posting, taxes, payments, reversals) are preserved.
    """
    _inherit = 'account.move'

    x_subscription_id = fields.Integer(
        string='Subscription ID',
        index=True,
        readonly=True,
        copy=False,
    )
    x_billing_period_start = fields.Date(
        string='Billing Period Start',
        index=True,
        readonly=True,
        copy=False,
    )
    x_billing_period_end = fields.Date(
        string='Billing Period End',
        index=True,
        readonly=True,
        copy=False,
    )
    x_billing_run_id = fields.Many2one(
        comodel_name='subscriptiq.billing.run',
        string='Originating Billing Run',
        index=True,
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    x_billing_ledger_id = fields.Many2one(
        comodel_name='subscriptiq.billing.ledger',
        string='Originating Billing Ledger',
        index=True,
        readonly=True,
        copy=False,
        ondelete='set null',
    )

    def _reverse_moves(self, default_values_list=None, cancel=False):
        """
        Overrides _reverse_moves to enforce the approved Rev 3 posted-invoice reversal policy (T-24, T-25):
        - Creates out_refund credit notes.
        - Preserves historical records.
        - Keeps original BillingLedger in 'succeeded' state.
        - Does NOT make the billing period rebillable.
        - Does NOT decrement discount_rule.current_uses.
        """
        reverse_moves = super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

        for orig_move, rev_move in zip(self, reverse_moves):
            if orig_move.x_subscription_id:
                _logger.info(
                    "Reversal credit note %s created for subscription invoice %s (sub: %s, period: %s to %s). "
                    "Original billing ledger remains succeeded (T-24, T-25).",
                    rev_move.name, orig_move.name, orig_move.x_subscription_id,
                    orig_move.x_billing_period_start, orig_move.x_billing_period_end
                )

        return reverse_moves


class AccountMoveLine(models.Model):
    """
    Ensures account.move.line correctly cooperates with line-level discounts.
    """
    _inherit = 'account.move.line'
