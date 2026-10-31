# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """Extension of native sale.order with SubscriptIQ subscription plan association.

    Adds a link to a subscription plan, a computed flag indicating this is a
    subscription quotation, and an idempotent action to populate order lines
    from plan lines.

    NOTE: Native sale.order workflow methods (action_confirm, action_cancel) are
    intentionally NOT overridden here.  Subscription lifecycle management is
    Phase 4 and will be implemented separately.

    Subscription Conversion Interface (Phase 4 placeholder):
    --------------------------------------------------------
    The method _prepare_subscription_values() is documented but not implemented.
    It will return a dict suitable for creating a subscriptiq.subscription record
    from a confirmed subscription quotation.  See the Phase 4 specification for
    the expected structure of that dict.
    """

    _inherit = 'sale.order'

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------

    subscription_plan_id = fields.Many2one(
        comodel_name='subscriptiq.plan',
        string="Subscription Plan",
        domain="[('active', '=', True)]",
        index=True,
        tracking=True,
        help=(
            "Subscription plan linked to this quotation. "
            "Selecting a plan allows populating order lines automatically "
            "from the plan's pre-configured product lines."
        ),
    )

    is_subscription_quotation = fields.Boolean(
        string="Subscription Quotation",
        compute='_compute_is_subscription_quotation',
        store=True,
        index=True,
        help="Automatically set to True when a subscription plan is selected.",
    )

    subscription_id = fields.Many2one(
        comodel_name='subscriptiq.subscription',
        string="Subscription",
        readonly=True,
        copy=False,
        index=True,
        help="The subscription created from this quotation.",
    )

    # -------------------------------------------------------------------------
    # Computations
    # -------------------------------------------------------------------------

    @api.depends('subscription_plan_id')
    def _compute_is_subscription_quotation(self):
        for order in self:
            order.is_subscription_quotation = bool(order.subscription_plan_id)

    # -------------------------------------------------------------------------
    # Business Methods
    # -------------------------------------------------------------------------

    def action_populate_lines_from_plan(self):
        """Populate sale.order.line records from the linked subscription plan.

        Behaviour:
        * Validates that a subscription plan is linked and active.
        * Validates plan availability dates (if defined).
        * For each plan line, checks whether an order line for the same
          product.product already exists.  If it does, the existing line is
          skipped (idempotent).
        * New lines are created with the plan line's quantity and price_unit
          as a pricing snapshot — independent of future catalogue edits.

        Returns:
            dict: A client-side notification action confirming the result.

        Raises:
            UserError: If no plan is linked, the plan is inactive, or the plan
                       is outside its availability window.
        """
        self.ensure_one()

        # --- Guard: plan must be linked ---
        if not self.subscription_plan_id:
            raise UserError(
                "Please select a Subscription Plan before populating lines."
            )

        plan = self.subscription_plan_id

        # --- Guard: plan must be active ---
        if not plan.active:
            raise UserError(
                f"Subscription plan '{plan.name}' is archived and cannot be used "
                "to populate quotation lines."
            )

        # --- Guard: plan availability window ---
        today = fields.Date.today()
        if plan.available_from and today < plan.available_from:
            raise UserError(
                f"Subscription plan '{plan.name}' is not yet available "
                f"(available from {plan.available_from})."
            )
        if plan.available_until and today > plan.available_until:
            raise UserError(
                f"Subscription plan '{plan.name}' has expired "
                f"(available until {plan.available_until})."
            )

        # --- Collect existing products already on this order ---
        existing_product_ids = set(self.order_line.mapped('product_id').ids)

        lines_to_create = []
        skipped = 0

        for plan_line in plan.line_ids:
            product = plan_line.product_id
            if product.id in existing_product_ids:
                skipped += 1
                continue

            lines_to_create.append({
                'order_id': self.id,
                'product_id': product.id,
                'name': plan_line.name or product.display_name,
                'product_uom_qty': plan_line.quantity,
                'price_unit': plan_line.price_unit,  # pricing snapshot
            })
            existing_product_ids.add(product.id)

        created_count = 0
        if lines_to_create:
            self.env['sale.order.line'].create(lines_to_create)
            created_count = len(lines_to_create)

        # --- Notification ---
        message_parts = []
        if created_count:
            message_parts.append(f"{created_count} line(s) added from plan '{plan.name}'.")
        if skipped:
            message_parts.append(f"{skipped} duplicate product(s) skipped.")
        if not created_count and not skipped:
            message_parts.append(f"Plan '{plan.name}' has no lines configured.")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Plan Lines Populated',
                'message': ' '.join(message_parts),
                'sticky': False,
                'type': 'success' if created_count else 'warning',
            },
        }

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------

    @api.constrains('subscription_plan_id')
    def _check_plan_active(self):
        """Prevent saving a quotation linked to an archived plan."""
        for order in self:
            if order.subscription_plan_id and not order.subscription_plan_id.active:
                raise ValidationError(
                    f"Subscription plan '{order.subscription_plan_id.name}' is archived. "
                    "Only active plans can be linked to a quotation."
                )

    # -------------------------------------------------------------------------
    # Phase 4: Quotation → Subscription Conversion
    # -------------------------------------------------------------------------

    def action_prepare_subscription(self):
        """Create a subscription in 'quotation' state from this subscription quotation.

        Workflow:
            1. Validate: must be a subscription quotation with an active plan.
            2. Validate: order must be in draft or sent state.
            3. Guard: prevent creating a duplicate subscription.
            4. Create subscription (state=quotation) with snapshotted pricing.
            5. Link the subscription back to this order via subscription_id.

        Returns:
            dict: client action to open the newly created subscription.

        Raises:
            UserError: on any validation failure.
        """
        self.ensure_one()

        if not self.is_subscription_quotation:
            raise UserError("This quotation is not linked to a subscription plan.")

        if not self.subscription_plan_id or not self.subscription_plan_id.active:
            raise UserError("A valid active subscription plan is required.")

        if self.state not in ('draft', 'sent'):
            raise UserError(
                f"Cannot prepare a subscription from a quotation in '{self.state}' state. "
                "The quotation must be in Draft or Sent state."
            )

        if self.subscription_id:
            raise UserError(
                f"A subscription ({self.subscription_id.name}) already exists for this quotation. "
                "Each quotation can only create one subscription."
            )

        if not self.order_line:
            raise UserError(
                "Please populate quotation lines before preparing a subscription. "
                "Use the 'Populate from Plan' button."
            )

        sub = self.env['subscriptiq.subscription']._create_from_sale_order(self)
        self.write({'subscription_id': sub.id})

        return {
            'type': 'ir.actions.act_window',
            'name': 'Subscription',
            'res_model': 'subscriptiq.subscription',
            'view_mode': 'form',
            'res_id': sub.id,
        }

    def action_confirm(self):
        """Override native sale.order confirmation to handle subscription transition.

        After native confirmation succeeds:
        * If a subscription in 'quotation' state is linked, transition it to 'confirmed'.
        * If no subscription exists but the order is a subscription quotation, create one.
        * Records lifecycle event.

        Native sale.order behaviour is fully preserved.
        """
        result = super().action_confirm()
        for order in self:
            if not order.is_subscription_quotation:
                continue
            sub = order.subscription_id
            if not sub:
                # Safely create subscription if prepare was skipped
                try:
                    sub = self.env['subscriptiq.subscription']._create_from_sale_order(order)
                    order.write({'subscription_id': sub.id})
                except Exception as e:
                    _logger.warning(
                        "Could not auto-create subscription for order %s: %s", order.name, e
                    )
                    continue
            if sub.state == 'quotation':
                prev_state = sub.state
                sub.write({'state': 'confirmed'})
                sub._log_event('confirmed', previous_state=prev_state, new_state='confirmed')
        return result

    def action_cancel(self):
        """Override native cancellation to close any linked subscription in quotation state.

        Subscriptions that are already active or closed are not affected.
        Native sale.order cancellation behaviour is fully preserved.
        """
        result = super().action_cancel()
        for order in self:
            sub = order.subscription_id
            if not sub:
                continue
            if sub.state in ('draft', 'quotation', 'confirmed'):
                try:
                    prev_state = sub.state
                    sub.write({'state': 'closed', 'next_billing_date': False})
                    sub._log_event(
                        'closed',
                        previous_state=prev_state,
                        new_state='closed',
                        reason=f"Source quotation {order.name} was cancelled.",
                    )
                except Exception as e:
                    _logger.warning(
                        "Could not close subscription %s on order cancellation: %s",
                        sub.name, e,
                    )
        return result

    # -------------------------------------------------------------------------
    # Smart Button Actions
    # -------------------------------------------------------------------------

    def action_view_subscription(self):
        """Open the linked subscription form."""
        self.ensure_one()
        if not self.subscription_id:
            return {}
        return {
            'type': 'ir.actions.act_window',
            'name': 'Subscription',
            'res_model': 'subscriptiq.subscription',
            'view_mode': 'form',
            'res_id': self.subscription_id.id,
        }

    # -------------------------------------------------------------------------
    # Subscription Conversion Interface — used by _create_from_sale_order
    # (Documented for Phase 4 completeness; implementation lives in subscription.py)
    # -------------------------------------------------------------------------


class SaleOrderTemplate(models.Model):
    """Extension of sale.order.template with SubscriptIQ subscription plan link.

    Allows quotation templates to carry a default subscription plan, which is
    then propagated to the sale.order when the template is applied via Odoo's
    native onchange mechanism (_onchange_sale_order_template_id in sale_management).
    """

    _inherit = 'sale.order.template'

    subscription_plan_id = fields.Many2one(
        comodel_name='subscriptiq.plan',
        string="Subscription Plan",
        domain="[('active', '=', True)]",
        help=(
            "Default subscription plan for quotations created from this template. "
            "When the template is applied to a quotation, this plan is copied to "
            "the quotation's Subscription Plan field."
        ),
    )
