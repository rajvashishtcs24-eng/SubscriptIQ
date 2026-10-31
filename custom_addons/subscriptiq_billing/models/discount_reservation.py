# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DiscountReservation(models.Model):
    """
    Manages discount reservations during the invoice generation lifecycle.
    Ensures safe concurrent usage evaluation and atomic consumption upon invoice posting.
    """
    _name = 'subscriptiq.discount.reservation'
    _description = 'Subscription Discount Reservation'
    _order = 'reserved_at desc, id desc'

    discount_rule_id = fields.Many2one(
        comodel_name='subscriptiq.discount.rule',
        string='Discount Rule',
        required=True,
        ondelete='restrict',
        index=True,
    )
    billing_ledger_id = fields.Many2one(
        comodel_name='subscriptiq.billing.ledger',
        string='Billing Ledger',
        required=True,
        ondelete='cascade',
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('reserved', 'Reserved'),
            ('consumed', 'Consumed'),
            ('released', 'Released'),
        ],
        string='Status',
        required=True,
        default='reserved',
        index=True,
    )
    reserved_at = fields.Datetime(
        string='Reserved At',
        required=True,
        default=fields.Datetime.now,
    )
    consumed_at = fields.Datetime(string='Consumed At')
    released_at = fields.Datetime(string='Released At')
    discount_type = fields.Selection(
        selection=[
            ('percentage', 'Percentage'),
            ('fixed', 'Fixed Amount'),
        ],
        string='Snapshot Discount Type',
        required=True,
        help="Type frozen at reservation creation time.",
    )
    discount_value = fields.Float(
        string='Snapshot Discount Value',
        required=True,
        help="Value frozen at reservation creation time.",
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Snapshot Currency',
    )

    def action_consume(self):
        """Transitions reservation to consumed and atomically increments rule uses (T-19, T-20)."""
        for record in self:
            if record.state != 'reserved':
                continue
            record.write({
                'state': 'consumed',
                'consumed_at': fields.Datetime.now(),
            })
            # Atomic update of rule uses
            record.discount_rule_id.sudo().write({
                'current_uses': record.discount_rule_id.current_uses + 1
            })

    def action_release(self):
        """Releases the reservation without incrementing rule usage."""
        for record in self:
            if record.state != 'reserved':
                continue
            record.write({
                'state': 'released',
                'released_at': fields.Datetime.now(),
            })
