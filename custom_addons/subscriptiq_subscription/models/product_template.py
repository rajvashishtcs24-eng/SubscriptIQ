# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    """Extension of product.template for SubscriptIQ subscription management.

    Reuses native Odoo product management (pricing, attributes, variants,
    categories, archiving) and adds domain-specific subscription eligibility.
    """
    _inherit = 'product.template'

    is_subscription_eligible = fields.Boolean(
        string="Subscription Eligible",
        default=False,
        index=True,
        help="Check this option if this product or service can be included in a recurring subscription plan.",
    )

    @api.model
    def _init_demo_brightloop_crm_pricing(self):
        """Helper method invoked by demo data to configure variant price_extra values."""
        crm_template = self.search([('name', '=', 'Brightloop CRM')], limit=1)
        if not crm_template:
            return

        for ptav in crm_template.attribute_line_ids.product_template_value_ids:
            val_name = ptav.product_attribute_value_id.name
            if val_name == 'Standard':
                ptav.write({'price_extra': 0.0})
            elif val_name == 'Odoo':
                ptav.write({'price_extra': 560.0})
            elif val_name == 'Premium':
                ptav.write({'price_extra': 1000.0})


class ProductProduct(models.Model):
    """Extension of product.product for SubscriptIQ variant management.

    Exposes the subscription eligibility flag at the variant level via a stored
    related field, enabling indexed search and direct selection on subscription lines.
    """
    _inherit = 'product.product'

    is_subscription_eligible = fields.Boolean(
        related='product_tmpl_id.is_subscription_eligible',
        string="Subscription Eligible",
        store=True,
        readonly=False,
        help="Indicates whether this specific variant is eligible for subscription plans (inherited from product template).",
    )
