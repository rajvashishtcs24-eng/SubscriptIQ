# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class DiscountRule(models.Model):
    """
    Manages discount rules, eligibility criteria, and usage limits.
    Owned exclusively by Member 2.
    """
    _name = 'subscriptiq.discount.rule'
    _description = 'Subscription Discount Rule'
    _order = 'priority asc, id asc'

    name = fields.Char(string='Rule Name', required=True)
    code = fields.Char(string='Promo Code', copy=False, help="Unique promotional code.")
    description = fields.Text(string='Internal Notes')
    discount_type = fields.Selection(
        selection=[
            ('percentage', 'Percentage (%)'),
            ('fixed', 'Fixed Monetary Amount'),
        ],
        string='Discount Type',
        required=True,
        default='percentage',
    )
    discount_value = fields.Float(
        string='Discount Value',
        required=True,
        help="Percentage (0-100) or fixed currency amount.",
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        help="Required when discount_type is fixed.",
    )
    priority = fields.Integer(
        string='Priority',
        required=True,
        default=10,
        help="Lower numbers indicate higher priority.",
    )
    date_start = fields.Date(string='Start Date (Inclusive)')
    date_end = fields.Date(string='End Date (Inclusive)')
    max_uses = fields.Integer(
        string='Maximum Uses',
        default=0,
        help="0 denotes unlimited uses.",
    )
    current_uses = fields.Integer(
        string='Current Uses',
        default=0,
        readonly=True,
        help="Incremented atomically upon successful invoice posting.",
    )
    min_qty = fields.Float(
        string='Minimum Quantity',
        default=0.0,
        help="Minimum total line quantity required for eligibility.",
    )
    min_amount_untaxed = fields.Monetary(
        string='Minimum Untaxed Amount',
        currency_field='min_amount_currency_id',
        default=0.0,
    )
    min_amount_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Min Amount Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    product_ids = fields.Many2many(
        comodel_name='product.product',
        relation='subscriptiq_discount_rule_product_rel',
        column1='discount_rule_id',
        column2='product_id',
        string='Restricted Products',
        help="Leave empty to apply to all products.",
    )
    subscription_id_filter = fields.Char(
        string='Restricted Subscription IDs',
        help="Comma-separated subscription IDs to restrict eligibility to.",
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )

    _sql_constraints = [
        (
            'uq_discount_code',
            'UNIQUE (code)',
            'The promo code must be unique.'
        ),
        (
            'chk_discount_value_positive',
            'CHECK (discount_value > 0)',
            'Discount value must be greater than zero.'
        ),
        (
            'chk_percentage_max',
            "CHECK (discount_type != 'percentage' OR discount_value <= 100)",
            'Percentage discount cannot exceed 100%.'
        ),
        (
            'chk_date_order',
            'CHECK (date_start IS NULL OR date_end IS NULL OR date_end >= date_start)',
            'Start date must be on or before end date.'
        ),
        (
            'chk_max_uses_nonneg',
            'CHECK (max_uses >= 0)',
            'Maximum uses cannot be negative.'
        ),
    ]

    @api.constrains('discount_type', 'currency_id')
    def _check_fixed_currency(self):
        for record in self:
            if record.discount_type == 'fixed' and not record.currency_id:
                raise ValidationError(_("Currency is required for fixed monetary discount rules."))
