# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SubscriptiqPlan(models.Model):
    """Subscription Plan definition for SubscriptIQ.

    Represents recurring pricing templates, bundling subscription-eligible
    product variants, recurrence frequency, and lifecycle management policies.
    """
    _name = 'subscriptiq.plan'
    _description = 'Subscription Plan'
    _order = 'name, id'

    # Identification
    name = fields.Char(
        string="Plan Name",
        required=True,
        index=True,
        copy=True,
        help="Display name of the subscription plan.",
    )
    description = fields.Text(
        string="Description",
        help="Detailed customer-facing or internal description of plan benefits.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        index=True,
        help="If unchecked, hides the plan without deleting it.",
    )

    # Multi-Company & Currency
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    # Lines & Pricing
    line_ids = fields.One2many(
        'subscriptiq.plan.line',
        'plan_id',
        string="Plan Lines",
        copy=True,
    )
    price = fields.Monetary(
        string="Plan Price",
        currency_field='currency_id',
        compute='_compute_price',
        store=True,
        readonly=True,
        help="Total recurring untaxed price computed automatically from plan lines.",
    )

    # Billing Configuration
    billing_frequency = fields.Selection(
        selection=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('yearly', 'Yearly'),
        ],
        string="Billing Frequency",
        required=True,
        default='monthly',
        index=True,
        help="Recurrence cadence for subscription invoicing.",
    )

    # Minimum Quantity
    minimum_quantity = fields.Float(
        string="Minimum Quantity",
        required=True,
        default=1.0,
        help="Minimum subscription quantity, such as seats, licenses, or units.",
    )

    # Availability Dates
    available_from = fields.Date(
        string="Available From",
        help="Start date from which this plan can be quoted or purchased.",
    )
    available_until = fields.Date(
        string="Available Until",
        help="End date after which this plan is retired from new subscription sales.",
    )

    # Renewal Configuration
    renewal_enabled = fields.Boolean(
        string="Renewal Enabled",
        default=True,
        help="Indicates whether this subscription plan permits contract renewal.",
    )
    renewal_type = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('automatic', 'Automatic'),
        ],
        string="Renewal Type",
        default='manual',
        help="Automatic renewal triggers automated recurring contract extension; "
             "manual requires user confirmation.",
    )

    # Policies
    auto_close = fields.Boolean(
        string="Auto-Close on Expiry",
        default=False,
        help="If enabled, automatically transitions expired subscriptions to closed state.",
    )
    allow_early_close = fields.Boolean(
        string="Allow Early Close",
        default=True,
        help="Allow customers or administrators to terminate the subscription prior to commitment end.",
    )
    allow_pause = fields.Boolean(
        string="Allow Pause",
        default=False,
        help="Allow temporary suspension of subscription billing and service delivery.",
    )

    # Computations & Dependencies
    @api.depends('line_ids.price_subtotal', 'currency_id')
    def _compute_price(self):
        for plan in self:
            total = sum(plan.line_ids.mapped('price_subtotal'))
            plan.price = plan.currency_id.round(total) if plan.currency_id else total

    # Onchanges
    @api.onchange('renewal_enabled')
    def _onchange_renewal_enabled(self):
        if not self.renewal_enabled:
            self.renewal_type = 'manual'

    # Validations & Business Constraints
    @api.constrains('minimum_quantity')
    def _check_minimum_quantity(self):
        for plan in self:
            if plan.minimum_quantity <= 0:
                raise ValidationError("The minimum quantity must be strictly greater than zero.")

    @api.constrains('available_from', 'available_until')
    def _check_availability_dates(self):
        for plan in self:
            if plan.available_from and plan.available_until and plan.available_until < plan.available_from:
                raise ValidationError("The availability end date cannot precede the start date.")

    @api.constrains('renewal_enabled', 'renewal_type')
    def _check_renewal_configuration(self):
        for plan in self:
            if not plan.renewal_enabled and plan.renewal_type == 'automatic':
                raise ValidationError("Automatic renewal cannot be selected when renewal is disabled.")

    @api.model
    def _init_demo_plans(self):
        """Helper invoked by demo data to populate realistic demo subscription plans."""
        crm_template = self.env['product.template'].search([('name', '=', 'Brightloop CRM')], limit=1)
        if not crm_template or not crm_template.product_variant_ids:
            return

        variants = crm_template.product_variant_ids
        std_variant = variants.filtered(
            lambda v: 'Standard' in v.product_template_attribute_value_ids.mapped('product_attribute_value_id.name')
        ) or variants[0]
        odoo_variant = variants.filtered(
            lambda v: 'Odoo' in v.product_template_attribute_value_ids.mapped('product_attribute_value_id.name')
        ) or variants[0]
        prem_variant = variants.filtered(
            lambda v: 'Premium' in v.product_template_attribute_value_ids.mapped('product_attribute_value_id.name')
        ) or variants[0]

        # 1. Basic Monthly Plan
        basic_plan = self.search([('name', '=', 'Brightloop CRM - Basic Monthly')], limit=1)
        if basic_plan and not basic_plan.line_ids:
            self.env['subscriptiq.plan.line'].create({
                'plan_id': basic_plan.id,
                'product_id': std_variant.id,
                'quantity': 1.0,
                'price_unit': std_variant.lst_price,
            })

        # 2. Professional Monthly Plan
        pro_plan = self.search([('name', '=', 'Brightloop CRM - Professional Monthly')], limit=1)
        if pro_plan and not pro_plan.line_ids:
            self.env['subscriptiq.plan.line'].create({
                'plan_id': pro_plan.id,
                'product_id': odoo_variant.id,
                'quantity': 5.0,
                'price_unit': odoo_variant.lst_price,
            })

        # 3. Enterprise Yearly Plan
        ent_plan = self.search([('name', '=', 'Brightloop CRM - Enterprise Yearly')], limit=1)
        if ent_plan and not ent_plan.line_ids:
            # Discounted annual rate per seat: ₹54,000 / year (vs 12 x 6,000 = 72,000)
            self.env['subscriptiq.plan.line'].create({
                'plan_id': ent_plan.id,
                'product_id': prem_variant.id,
                'quantity': 10.0,
                'price_unit': 54000.0,
            })


class SubscriptiqPlanLine(models.Model):
    """Line item configuration for SubscriptIQ Subscription Plans.

    Binds a specific subscription-eligible product variant and quantity to
    a plan with plan-specific unit pricing.
    """
    _name = 'subscriptiq.plan.line'
    _description = 'Subscription Plan Line'
    _order = 'sequence, id'

    plan_id = fields.Many2one(
        'subscriptiq.plan',
        string="Subscription Plan",
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product Variant",
        required=True,
        domain="[('is_subscription_eligible', '=', True)]",
        index=True,
    )
    name = fields.Char(
        string="Description",
        compute='_compute_name',
        store=True,
        readonly=False,
    )
    quantity = fields.Float(
        string="Quantity",
        required=True,
        default=1.0,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='plan_id.currency_id',
        store=True,
        readonly=True,
    )
    price_unit = fields.Monetary(
        string="Unit Price",
        currency_field='currency_id',
        required=True,
        default=0.0,
        help="Plan-specific unit price. Defaults to variant selling price but can be overridden.",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        currency_field='currency_id',
        compute='_compute_price_subtotal',
        store=True,
        readonly=True,
    )

    # Computations
    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            if line.product_id and not line.name:
                line.name = line.product_id.display_name

    @api.depends('quantity', 'price_unit', 'currency_id')
    def _compute_price_subtotal(self):
        for line in self:
            subtotal = line.quantity * line.price_unit
            line.price_subtotal = line.currency_id.round(subtotal) if line.currency_id else subtotal

    # Onchanges
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            if not self.name:
                self.name = self.product_id.display_name
            # Default unit price from the variant's actual current selling price
            # (which includes template base price + attribute value price_extra surcharges).
            self.price_unit = self.product_id.lst_price

    # ORM Overrides
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'product_id' in vals:
                product = self.env['product.product'].browse(vals['product_id'])
                if 'price_unit' not in vals:
                    vals['price_unit'] = product.lst_price
                if 'name' not in vals:
                    vals['name'] = product.display_name
        return super().create(vals_list)

    # Business Constraints
    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Plan line quantity must be strictly greater than zero.")

    @api.constrains('price_unit')
    def _check_price_unit(self):
        for line in self:
            if line.price_unit < 0:
                raise ValidationError("Plan line unit price cannot be negative.")

    @api.constrains('product_id')
    def _check_product_eligibility(self):
        for line in self:
            if line.product_id and not line.product_id.is_subscription_eligible:
                raise ValidationError(
                    f"Product '{line.product_id.display_name}' is not subscription eligible. "
                    "Only products marked as 'Subscription Eligible' can be added to a plan."
                )

    @api.constrains('plan_id', 'product_id')
    def _check_unique_product(self):
        for line in self:
            duplicate = self.search([
                ('id', '!=', line.id),
                ('plan_id', '=', line.plan_id.id),
                ('product_id', '=', line.product_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    f"Product variant '{line.product_id.display_name}' is already included in this plan. "
                    "Each product variant can only appear once per subscription plan."
                )
