# -*- coding: utf-8 -*-
"""Phase 4 — Subscription Management Engine.

Models:
    subscriptiq.subscription      - Main subscription record.
    subscriptiq.subscription.line - Pricing-snapshot line items.
    subscriptiq.subscription.event - Immutable lifecycle event history.
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selection constants (shared between subscription and event models)
# ---------------------------------------------------------------------------
BILLING_FREQUENCY_SELECTION = [
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    ('yearly', 'Yearly'),
]

STATE_SELECTION = [
    ('draft', 'Draft'),
    ('quotation', 'Quotation'),
    ('confirmed', 'Confirmed'),
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('closed', 'Closed'),
]

EVENT_TYPE_SELECTION = [
    ('created', 'Created'),
    ('quotation_created', 'Quotation Created'),
    ('confirmed', 'Confirmed'),
    ('activated', 'Activated'),
    ('paused', 'Paused'),
    ('resumed', 'Resumed'),
    ('renewed', 'Renewed'),
    ('closed', 'Closed'),
    ('billing_succeeded', 'Billing Succeeded'),
]

RENEWAL_TYPE_SELECTION = [
    ('manual', 'Manual'),
    ('automatic', 'Automatic'),
]


class SubscriptiqSubscription(models.Model):
    """Main subscription record for SubscriptIQ.

    Represents a customer's active recurring commitment derived from a
    confirmed subscription quotation (sale.order).  Lifecycle state
    transitions are governed exclusively by validated business methods;
    users cannot change `state` directly through field editing.

    Pricing and policy fields are snapshots taken at subscription creation
    time and remain independent of subsequent plan or product edits.
    """
    _name = 'subscriptiq.subscription'
    _description = 'Subscription'
    _order = 'name desc'
    _rec_name = 'name'

    # -------------------------------------------------------------------------
    # A. Identification
    # -------------------------------------------------------------------------

    name = fields.Char(
        string="Subscription Number",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default='New',
        help="Auto-generated subscription reference number.",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        required=True,
        index=True,
    )
    plan_id = fields.Many2one(
        'subscriptiq.plan',
        string="Subscription Plan",
        required=True,
        index=True,
        help="The plan template from which this subscription was derived.",
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string="Source Quotation",
        readonly=True,
        index=True,
        ondelete='restrict',
        help="The confirmed sales quotation that originated this subscription.",
    )
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # -------------------------------------------------------------------------
    # B. Date Fields
    # -------------------------------------------------------------------------

    start_date = fields.Date(
        string="Start Date",
        help="Date when the subscription becomes active.",
    )
    end_date = fields.Date(
        string="End Date",
        help="Date when the subscription expires. Leave empty for open-ended subscriptions.",
    )
    next_billing_date = fields.Date(
        string="Next Billing Date",
        index=True,
        help="Date on which the next billing cycle is due. Advances only after billing acknowledgement.",
    )

    # -------------------------------------------------------------------------
    # C. Billing Configuration (snapshot from plan at creation)
    # -------------------------------------------------------------------------

    billing_frequency = fields.Selection(
        selection=BILLING_FREQUENCY_SELECTION,
        string="Billing Frequency",
        required=True,
        default='monthly',
        index=True,
        help="Snapshot of the billing cadence agreed at subscription creation.",
    )
    payment_term_id = fields.Many2one(
        'account.payment.term',
        string="Payment Terms",
        help="Payment terms that apply to invoices generated for this subscription.",
    )

    # -------------------------------------------------------------------------
    # D. Renewal Configuration (snapshot)
    # -------------------------------------------------------------------------

    renewal_enabled = fields.Boolean(
        string="Renewal Enabled",
        default=True,
        help="Snapshot: whether renewal was permitted at subscription creation.",
    )
    renewal_type = fields.Selection(
        selection=RENEWAL_TYPE_SELECTION,
        string="Renewal Type",
        default='manual',
        help="Snapshot: manual or automatic renewal as agreed at creation.",
    )
    auto_close = fields.Boolean(
        string="Auto-Close on Expiry",
        default=False,
        help="Snapshot: if True, the scheduler closes this subscription when end_date passes.",
    )

    # -------------------------------------------------------------------------
    # E. Lifecycle Policies (snapshot)
    # -------------------------------------------------------------------------

    allow_early_close = fields.Boolean(
        string="Allow Early Close",
        default=True,
        help="Snapshot: whether early termination was permitted at subscription creation.",
    )
    allow_pause = fields.Boolean(
        string="Allow Pause",
        default=False,
        help="Snapshot: whether temporary suspension was permitted at subscription creation.",
    )

    # -------------------------------------------------------------------------
    # F. State / Status
    # -------------------------------------------------------------------------

    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Status",
        default='draft',
        required=True,
        readonly=True,
        index=True,
        copy=False,
        help="Subscription lifecycle state. Change through action buttons only.",
    )

    # -------------------------------------------------------------------------
    # G. Computed / Aggregates
    # -------------------------------------------------------------------------

    line_ids = fields.One2many(
        'subscriptiq.subscription.line',
        'subscription_id',
        string="Subscription Lines",
        copy=True,
    )
    event_ids = fields.One2many(
        'subscriptiq.subscription.event',
        'subscription_id',
        string="Event History",
    )
    event_count = fields.Integer(
        string="Events",
        compute='_compute_event_count',
    )
    amount_total = fields.Monetary(
        string="Total Amount",
        currency_field='currency_id',
        compute='_compute_amount_total',
        store=True,
        help="Sum of all subscription line subtotals.",
    )

    # -------------------------------------------------------------------------
    # Computations
    # -------------------------------------------------------------------------

    @api.depends('event_ids')
    def _compute_event_count(self):
        for sub in self:
            sub.event_count = len(sub.event_ids)

    @api.depends('line_ids.price_subtotal', 'currency_id')
    def _compute_amount_total(self):
        for sub in self:
            total = sum(sub.line_ids.mapped('price_subtotal'))
            sub.amount_total = (
                sub.currency_id.round(total) if sub.currency_id else total
            )

    # -------------------------------------------------------------------------
    # ORM Overrides
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = Seq.next_by_code('subscriptiq.subscription') or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Business Constraints
    # -------------------------------------------------------------------------

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for sub in self:
            if sub.start_date and sub.end_date and sub.end_date < sub.start_date:
                raise ValidationError(
                    "The subscription end date cannot precede the start date."
                )

    @api.constrains('start_date', 'next_billing_date')
    def _check_billing_date(self):
        for sub in self:
            if sub.start_date and sub.next_billing_date and sub.next_billing_date < sub.start_date:
                raise ValidationError(
                    "The next billing date cannot precede the subscription start date."
                )

    # -------------------------------------------------------------------------
    # Private Helpers — Billing Period Calculations
    # -------------------------------------------------------------------------

    def _get_billing_delta(self):
        """Return a relativedelta matching the subscription's billing_frequency."""
        self.ensure_one()
        freq = self.billing_frequency
        if freq == 'daily':
            return relativedelta(days=1)
        elif freq == 'weekly':
            return relativedelta(weeks=1)
        elif freq == 'monthly':
            return relativedelta(months=1)
        elif freq == 'yearly':
            return relativedelta(years=1)
        return relativedelta(months=1)

    def _compute_billing_period(self):
        """Return (period_start, period_end) for the current billing cycle.

        period_start = next_billing_date
        period_end   = next_period_start − 1 day  (capped at end_date)

        Returns:
            tuple[date, date] | (None, None)
        """
        self.ensure_one()
        if not self.next_billing_date:
            return (None, None)
        period_start = self.next_billing_date
        next_period_start = period_start + self._get_billing_delta()
        period_end = next_period_start - timedelta(days=1)
        # Cap at subscription end date when finite
        if self.end_date and period_end > self.end_date:
            period_end = self.end_date
        return (period_start, period_end)

    def _advance_billing_date(self):
        """Advance next_billing_date by one billing period.

        Must only be called after a successful billing acknowledgement.
        Stops advancing when the new date would exceed end_date.
        """
        self.ensure_one()
        if not self.next_billing_date:
            return
        new_billing_date = self.next_billing_date + self._get_billing_delta()
        # Do not advance past end date
        if self.end_date and new_billing_date > self.end_date:
            new_billing_date = self.end_date
        self.write({'next_billing_date': new_billing_date})

    # -------------------------------------------------------------------------
    # Private Helper — Event Creation
    # -------------------------------------------------------------------------

    def _log_event(self, event_type, previous_state=None, new_state=None, reason=None, metadata=None):
        """Create an immutable lifecycle event record for this subscription."""
        self.ensure_one()
        vals = {
            'subscription_id': self.id,
            'event_type': event_type,
            'previous_state': previous_state,
            'new_state': new_state,
            'event_date': fields.Datetime.now(),
            'user_id': self.env.uid,
            'reason': reason,
        }
        if metadata is not None:
            vals['metadata'] = metadata
        return self.env['subscriptiq.subscription.event'].create(vals)

    # -------------------------------------------------------------------------
    # 5A. Quotation → Subscription Conversion (called from sale.order)
    # -------------------------------------------------------------------------

    @api.model
    def _create_from_sale_order(self, order):
        """Create a subscription in 'quotation' state from a sale.order.

        Called by sale.order.action_prepare_subscription().

        Args:
            order: sale.order recordset (ensure_one already called by caller)

        Returns:
            subscriptiq.subscription record
        """
        plan = order.subscription_plan_id

        # Snapshot plan policies
        vals = {
            'partner_id': order.partner_id.id,
            'plan_id': plan.id,
            'sale_order_id': order.id,
            'company_id': (order.company_id or self.env.company).id,
            'currency_id': order.currency_id.id,
            'state': 'quotation',
            # Billing snapshot
            'billing_frequency': plan.billing_frequency,
            'payment_term_id': order.payment_term_id.id if order.payment_term_id else False,
            # Renewal snapshot
            'renewal_enabled': plan.renewal_enabled,
            'renewal_type': plan.renewal_type or 'manual',
            'auto_close': plan.auto_close,
            # Policy snapshot
            'allow_early_close': plan.allow_early_close,
            'allow_pause': plan.allow_pause,
        }

        # Build line vals from sale.order.lines (pricing snapshot)
        line_vals = []
        for sol in order.order_line:
            product = sol.product_id
            if not product:
                continue
            tax_records = sol.tax_ids if hasattr(sol, 'tax_ids') else getattr(sol, 'tax_id', self.env['account.tax'])
            line_vals.append((0, 0, {
                'product_id': product.id,
                'name': sol.name or product.display_name,
                'quantity': sol.product_uom_qty,
                'price_unit': sol.price_unit,
                'discount': getattr(sol, 'discount', 0.0) or 0.0,
                'tax_ids': [(6, 0, tax_records.ids)],
            }))
        if line_vals:
            vals['line_ids'] = line_vals

        sub = self.create(vals)
        sub._log_event('quotation_created', previous_state=None, new_state='quotation')
        return sub

    # -------------------------------------------------------------------------
    # 6A. ACTIVATE — CONFIRMED → ACTIVE
    # -------------------------------------------------------------------------

    def action_activate(self):
        """Transition a confirmed subscription to active state.

        Initialises start_date (if unset) and next_billing_date.
        Records an activation event.

        Raises:
            UserError: If state is not 'confirmed', or required data is missing.
        """
        for sub in self:
            if sub.state != 'confirmed':
                raise UserError(
                    f"Cannot activate subscription '{sub.name}': "
                    f"only confirmed subscriptions can be activated (current state: {sub.state})."
                )
            if not sub.line_ids:
                raise UserError(
                    f"Cannot activate subscription '{sub.name}': it has no subscription lines."
                )
            if not sub.partner_id or not sub.plan_id:
                raise UserError(
                    f"Cannot activate subscription '{sub.name}': customer and plan are required."
                )
            today = fields.Date.today()
            start = sub.start_date or today
            next_billing = start + sub._get_billing_delta()
            prev_state = sub.state
            sub.write({
                'state': 'active',
                'start_date': start,
                'next_billing_date': next_billing,
            })
            sub._log_event('activated', previous_state=prev_state, new_state='active')

    # -------------------------------------------------------------------------
    # 6B. PAUSE — ACTIVE → PAUSED
    # -------------------------------------------------------------------------

    def action_pause(self, reason=None):
        """Pause an active subscription.

        Args:
            reason (str|None): Optional reason for pausing.

        Raises:
            UserError: If state is not 'active' or plan disallows pausing.
        """
        for sub in self:
            if sub.state != 'active':
                raise UserError(
                    f"Cannot pause subscription '{sub.name}': only active subscriptions can be paused."
                )
            if not sub.allow_pause:
                raise UserError(
                    f"Cannot pause subscription '{sub.name}': the subscription plan does not allow pausing."
                )
            prev_state = sub.state
            sub.write({'state': 'paused'})
            sub._log_event('paused', previous_state=prev_state, new_state='paused', reason=reason)

    # -------------------------------------------------------------------------
    # 6C. RESUME — PAUSED → ACTIVE
    # -------------------------------------------------------------------------

    def action_resume(self, reason=None):
        """Resume a paused subscription.

        Billing policy on resume:
            Past-due periods do NOT become immediately due.
            next_billing_date is advanced to the later of its current value
            and today, preserving the original billing cadence alignment
            as closely as possible.  The first post-resume billing date is
            therefore today's date if the stored date has passed.

        Args:
            reason (str|None): Optional reason for resuming.

        Raises:
            UserError: If state is not 'paused'.
        """
        for sub in self:
            if sub.state != 'paused':
                raise UserError(
                    f"Cannot resume subscription '{sub.name}': only paused subscriptions can be resumed."
                )
            today = fields.Date.today()
            # Adjust next_billing_date if it has slipped into the past during pause
            next_billing = sub.next_billing_date
            if next_billing and next_billing < today:
                next_billing = today
            prev_state = sub.state
            sub.write({
                'state': 'active',
                'next_billing_date': next_billing,
            })
            sub._log_event('resumed', previous_state=prev_state, new_state='active', reason=reason)

    # -------------------------------------------------------------------------
    # 6D. RENEW — extend end_date while staying ACTIVE
    # -------------------------------------------------------------------------

    def action_renew(self, reason=None):
        """Renew the subscription by extending its end date by one billing period.

        A renewal event is recorded and the state remains 'active'.
        Existing subscription line prices are NOT changed.

        Args:
            reason (str|None): Optional reason for renewal.

        Raises:
            UserError: If renewal is not enabled, or state is invalid.
        """
        for sub in self:
            if sub.state not in ('active', 'confirmed'):
                raise UserError(
                    f"Cannot renew subscription '{sub.name}': must be active or confirmed."
                )
            if not sub.renewal_enabled:
                raise UserError(
                    f"Cannot renew subscription '{sub.name}': renewal is disabled on this subscription."
                )
            # Extend end_date
            if sub.end_date:
                new_end = sub.end_date + sub._get_billing_delta()
            else:
                # Open-ended: record event but no date change needed
                new_end = sub.end_date
            sub.write({'end_date': new_end})
            sub._log_event('renewed', previous_state=sub.state, new_state=sub.state, reason=reason)

    # -------------------------------------------------------------------------
    # 6E. EARLY CLOSE
    # -------------------------------------------------------------------------

    def action_close(self, reason=None):
        """Close the subscription, ending it before natural expiry.

        Args:
            reason (str|None): Mandatory reason for early closure.

        Raises:
            UserError: If allow_early_close is False, or state is invalid.
        """
        for sub in self:
            if sub.state not in ('active', 'paused', 'confirmed'):
                raise UserError(
                    f"Cannot close subscription '{sub.name}': current state '{sub.state}' does not allow closure."
                )
            if sub.state == 'active' and not sub.allow_early_close:
                raise UserError(
                    f"Cannot close subscription '{sub.name}': the subscription plan does not allow early closure."
                )
            prev_state = sub.state
            sub.write({'state': 'closed', 'next_billing_date': False})
            sub._log_event('closed', previous_state=prev_state, new_state='closed', reason=reason)

    # -------------------------------------------------------------------------
    # 6F. AUTOMATIC EXPIRY (called by scheduler)
    # -------------------------------------------------------------------------

    @api.model
    def _cron_auto_close_expired(self):
        """Scheduled action: close expired subscriptions that have auto_close=True.

        Only closes subscriptions where:
        * state = 'active'
        * auto_close = True
        * end_date is set and <= today
        """
        today = fields.Date.today()
        expired = self.search([
            ('state', '=', 'active'),
            ('auto_close', '=', True),
            ('end_date', '!=', False),
            ('end_date', '<=', today),
        ])
        for sub in expired:
            try:
                prev_state = sub.state
                sub.write({'state': 'closed', 'next_billing_date': False})
                sub._log_event(
                    'closed',
                    previous_state=prev_state,
                    new_state='closed',
                    reason='Automatic closure: subscription end date passed.',
                )
                _logger.info("Auto-closed subscription %s (end_date: %s)", sub.name, sub.end_date)
            except Exception as e:
                _logger.error("Failed to auto-close subscription %s: %s", sub.name, e)

    # -------------------------------------------------------------------------
    # 8. Member 2 Billing Integration Interface
    # -------------------------------------------------------------------------

    @api.model
    def get_due_billing_data(self, billing_date=None, limit=100, offset=0):
        """Public billing interface for Member 2 (subscriptiq_billing module).

        Returns a list of structured dicts for subscriptions due for billing.

        Args:
            billing_date (date|None): Target billing date. Defaults to today.
            limit (int): Maximum records per page (default 100).
            offset (int): Pagination offset.

        Returns:
            list[dict]: Each dict contains 'subscription', 'billing', and 'lines' keys.

        Subscription dict:
            subscription_id, subscription_number, customer_id, status,
            plan_id, company_id

        Billing dict:
            billing_frequency, billing_period_start, billing_period_end,
            next_billing_date, currency_id, payment_term_id

        Lines list (each):
            product_id, product_name, description, quantity, agreed_unit_price,
            discount, tax_ids
        """
        if billing_date is None:
            billing_date = fields.Date.today()

        domain = [
            ('state', '=', 'active'),
            ('next_billing_date', '!=', False),
            ('next_billing_date', '<=', billing_date),
            ('start_date', '!=', False),
            ('start_date', '<=', billing_date),
        ]
        # Exclude past end_date subscriptions
        subscriptions = self.search(
            domain,
            limit=limit,
            offset=offset,
            order='next_billing_date asc, id asc',
        )
        # Filter out those that have passed end_date (can't do in domain cleanly with OR-null)
        subscriptions = subscriptions.filtered(
            lambda s: not s.end_date or s.end_date >= billing_date
        )

        result = []
        for sub in subscriptions:
            period_start, period_end = sub._compute_billing_period()
            sub_data = {
                'subscription': {
                    'subscription_id': sub.id,
                    'subscription_number': sub.name,
                    'customer_id': sub.partner_id.id,
                    'status': sub.state,
                    'plan_id': sub.plan_id.id,
                    'company_id': sub.company_id.id,
                },
                'billing': {
                    'billing_frequency': sub.billing_frequency,
                    'billing_period_start': period_start,
                    'billing_period_end': period_end,
                    'next_billing_date': sub.next_billing_date,
                    'currency_id': sub.currency_id.id,
                    'payment_term_id': sub.payment_term_id.id if sub.payment_term_id else False,
                },
                'lines': [
                    {
                        'product_id': line.product_id.id,
                        'product_name': line.product_id.name,
                        'description': line.name,
                        'quantity': line.quantity,
                        'agreed_unit_price': line.price_unit,
                        'discount': line.discount,
                        'tax_ids': line.tax_ids.ids,
                    }
                    for line in sub.line_ids
                ],
            }
            result.append(sub_data)
        return result

    @api.model
    def action_register_billing_success(
        self, subscription_id, billing_period_start, billing_period_end, invoice_id
    ):
        """Acknowledge successful billing and advance next_billing_date.

        This is the second Member 2 integration method.  It must be called
        after an invoice has been successfully created and posted.

        Thread-safe concurrency protection:
        Acquires a PostgreSQL row-level lock using SELECT FOR UPDATE on the
        subscription record, invalidates the ORM cache, and validates that
        the requested billing period matches next_billing_date before advancing.
        Duplicate acknowledgements are safely rejected.

        Args:
            subscription_id (int): Database id of subscriptiq.subscription.
            billing_period_start (date|str): Start of the billed period.
            billing_period_end (date|str): End of the billed period.
            invoice_id (int): Database id of the posted account.move invoice.

        Returns:
            dict: {'success': True, 'next_billing_date': <date>}
                  or {'success': False, 'error': <str>}
        """
        # 1. Acquire database-level row lock to serialize concurrent acknowledgements
        self.env.cr.execute(
            "SELECT id FROM subscriptiq_subscription WHERE id = %s FOR UPDATE",
            [subscription_id],
        )
        if not self.env.cr.rowcount:
            return {'success': False, 'error': 'Subscription not found.'}

        sub = self.browse(subscription_id)
        # 2. Invalidate ORM cache to re-read fresh committed values after lock acquisition
        sub.invalidate_recordset(['state', 'next_billing_date', 'partner_id'])

        # 3. Validate state
        if sub.state != 'active':
            return {
                'success': False,
                'error': f"Subscription '{sub.name}' is not active (state: {sub.state}).",
            }

        # Normalize date types if passed as strings
        if isinstance(billing_period_start, str):
            billing_period_start = fields.Date.from_string(billing_period_start)
        if isinstance(billing_period_end, str):
            billing_period_end = fields.Date.from_string(billing_period_end)

        # 4. Validate that the billing period start matches the current next_billing_date
        # If another worker already advanced next_billing_date, this check safely rejects the duplicate.
        if not sub.next_billing_date or billing_period_start != sub.next_billing_date:
            return {
                'success': False,
                'error': (
                    f"Billing period start {billing_period_start} does not match "
                    f"subscription next_billing_date {sub.next_billing_date} "
                    "(duplicate acknowledgement rejected)."
                ),
            }

        # 5. Validate invoice customer consistency (if invoice_id is provided)
        if invoice_id:
            invoice = self.env['account.move'].browse(invoice_id)
            if invoice.exists() and invoice.partner_id != sub.partner_id:
                return {
                    'success': False,
                    'error': (
                        f"Invoice partner '{invoice.partner_id.name}' does not match "
                        f"subscription customer '{sub.partner_id.name}'."
                    ),
                }

        # 6. Advance next_billing_date exactly once
        old_billing_date = sub.next_billing_date
        sub._advance_billing_date()

        # 7. Record billing success event in the same transaction
        sub._log_event(
            'billing_succeeded',
            previous_state=sub.state,
            new_state=sub.state,
            metadata={
                'invoice_id': invoice_id,
                'period_start': str(billing_period_start),
                'period_end': str(billing_period_end),
                'old_billing_date': str(old_billing_date),
                'new_billing_date': str(sub.next_billing_date),
            },
        )
        return {'success': True, 'next_billing_date': sub.next_billing_date}

    # -------------------------------------------------------------------------
    # 8B. Member 2 Billing Integration — Adapter-Compatible Aliases
    #
    # Member 2's SubscriptionAdapter (subscriptiq_billing) discovers methods
    # via hasattr() using these exact names. These thin aliases bridge the
    # contract without duplicating business logic.
    # -------------------------------------------------------------------------

    @api.model
    def get_subscriptions_due_for_billing(self, billing_date=None):
        """Adapter alias: returns flat list of subscription IDs due for billing.

        Called by subscriptiq_billing.SubscriptionAdapter.get_subscriptions_due_for_billing().

        Args:
            billing_date (date|None): Target billing date. Defaults to today.

        Returns:
            list[int]: Database IDs of active subscriptions due for billing.
        """
        if billing_date is None:
            billing_date = fields.Date.today()
        domain = [
            ('state', '=', 'active'),
            ('next_billing_date', '!=', False),
            ('next_billing_date', '<=', billing_date),
            ('start_date', '!=', False),
            ('start_date', '<=', billing_date),
        ]
        subs = self.search(domain, order='next_billing_date asc, id asc')
        subs = subs.filtered(lambda s: not s.end_date or s.end_date >= billing_date)
        return subs.ids

    @api.model
    def get_billing_payload(self, subscription_id):
        """Adapter alias: returns structured billing payload for one subscription.

        Called by subscriptiq_billing.SubscriptionAdapter.get_billing_payload().

        Args:
            subscription_id (int): Database ID of subscriptiq.subscription.

        Returns:
            dict: Payload with subscription_id, partner_id, currency_id,
                  fiscal_position_id, payment_term_id, billing_frequency,
                  next_billing_date, billing_day_anchor, lines.

        Raises:
            ValueError: If the subscription is non-billable or not found.
        """
        sub = self.browse(subscription_id)
        if not sub.exists():
            raise ValueError(f"Subscription {subscription_id} does not exist.")
        if sub.state != 'active':
            raise ValueError(
                f"Subscription {subscription_id} is in non-billable state '{sub.state}'. "
                "Billing cannot generate invoices for paused, closed, or draft subscriptions."
            )
        return {
            'subscription_id': sub.id,
            'partner_id': sub.partner_id.id,
            'currency_id': sub.currency_id.id,
            'fiscal_position_id': False,
            'payment_term_id': sub.payment_term_id.id if sub.payment_term_id else False,
            'billing_frequency': sub.billing_frequency,
            'next_billing_date': sub.next_billing_date,
            'billing_day_anchor': sub.next_billing_date.day if sub.next_billing_date else 1,
            'lines': [
                {
                    'product_id': line.product_id.id,
                    'name': line.name or line.product_id.display_name,
                    'quantity': line.quantity,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': line.tax_ids.ids,
                    'uom_id': False,
                }
                for line in sub.line_ids
            ],
        }

    @api.model
    def register_billing_success(self, subscription_id, invoice_id, next_billing_date):
        """Adapter alias: acknowledge a successful billing cycle.

        Called by subscriptiq_billing.SubscriptionAdapter.register_billing_success().
        Delegates to action_register_billing_success() for row locking + event logging.

        Args:
            subscription_id (int): Database ID of subscriptiq.subscription.
            invoice_id (int): Database ID of the posted account.move.
            next_billing_date (date): Next billing date computed by Member 2.

        Returns:
            None
        """
        from datetime import timedelta as _timedelta
        sub = self.browse(subscription_id)
        if not sub.exists():
            _logger.warning(
                "register_billing_success called for non-existent subscription %s",
                subscription_id,
            )
            return
        billing_period_start = sub.next_billing_date
        if not billing_period_start:
            _logger.warning(
                "register_billing_success: subscription %s has no next_billing_date, skipping.",
                subscription_id,
            )
            return
        # Period end = one day before M2's computed next billing date
        billing_period_end = next_billing_date - _timedelta(days=1)
        result = self.action_register_billing_success(
            subscription_id=subscription_id,
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            invoice_id=invoice_id,
        )
        if not result.get('success'):
            _logger.warning(
                "register_billing_success for sub %s returned failure: %s",
                subscription_id, result.get('error'),
            )

    # -------------------------------------------------------------------------
    # Smart Button Action
    # -------------------------------------------------------------------------

    def action_view_events(self):
        """Open the event history list for this subscription."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f"Events — {self.name}",
            'res_model': 'subscriptiq.subscription.event',
            'view_mode': 'list,form',
            'domain': [('subscription_id', '=', self.id)],
            'context': {'default_subscription_id': self.id},
        }

    def action_view_sale_order(self):
        """Navigate to the source sales order."""
        self.ensure_one()
        if not self.sale_order_id:
            return {}
        return {
            'type': 'ir.actions.act_window',
            'name': "Source Quotation",
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }


# ---------------------------------------------------------------------------
# subscriptiq.subscription.line
# ---------------------------------------------------------------------------

class SubscriptiqSubscriptionLine(models.Model):
    """Subscription line — pricing snapshot taken at subscription creation.

    Prices on these lines are immutable snapshots of the agreed quotation
    prices.  They are never recomputed from product catalogue or plan data.
    """
    _name = 'subscriptiq.subscription.line'
    _description = 'Subscription Line'
    _order = 'sequence, id'

    subscription_id = fields.Many2one(
        'subscriptiq.subscription',
        string="Subscription",
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    product_id = fields.Many2one(
        'product.product',
        string="Product Variant",
        required=True,
        domain="[('is_subscription_eligible', '=', True)]",
        index=True,
    )
    name = fields.Char(
        string="Description",
        help="Product description as agreed at quotation time.",
    )
    quantity = fields.Float(
        string="Quantity",
        required=True,
        default=1.0,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='subscription_id.currency_id',
        store=True,
        readonly=True,
    )
    price_unit = fields.Monetary(
        string="Unit Price",
        currency_field='currency_id',
        required=True,
        default=0.0,
        help="Agreed unit price — snapshot, never updated from catalogue.",
    )
    discount = fields.Float(
        string="Discount (%)",
        default=0.0,
        help="Discount percentage applied to this line.",
    )
    tax_ids = fields.Many2many(
        'account.tax',
        'subscriptiq_sub_line_tax_rel',
        'line_id',
        'tax_id',
        string="Taxes",
        help="Tax configuration snapshot from the original quotation line.",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal (excl. tax)",
        currency_field='currency_id',
        compute='_compute_price_totals',
        store=True,
        readonly=True,
    )
    price_total = fields.Monetary(
        string="Total (incl. tax)",
        currency_field='currency_id',
        compute='_compute_price_totals',
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Computations
    # -------------------------------------------------------------------------

    @api.depends(
        'quantity', 'price_unit', 'discount', 'tax_ids',
        'currency_id', 'subscription_id.partner_id',
    )
    def _compute_price_totals(self):
        for line in self:
            price = line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    price,
                    currency=line.currency_id,
                    quantity=line.quantity,
                    product=line.product_id,
                    partner=line.subscription_id.partner_id,
                )
                line.price_subtotal = taxes['total_excluded']
                line.price_total = taxes['total_included']
            else:
                subtotal = price * line.quantity
                line.price_subtotal = line.currency_id.round(subtotal) if line.currency_id else subtotal
                line.price_total = line.price_subtotal

    # -------------------------------------------------------------------------
    # Business Constraints
    # -------------------------------------------------------------------------

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Subscription line quantity must be greater than zero.")

    @api.constrains('price_unit')
    def _check_price_unit(self):
        for line in self:
            if line.price_unit < 0:
                raise ValidationError("Subscription line unit price cannot be negative.")

    @api.constrains('discount')
    def _check_discount(self):
        for line in self:
            if line.discount < 0 or line.discount > 100:
                raise ValidationError("Discount must be between 0% and 100%.")

    @api.constrains('product_id')
    def _check_product_eligibility(self):
        for line in self:
            if line.product_id and not line.product_id.is_subscription_eligible:
                raise ValidationError(
                    f"Product '{line.product_id.display_name}' is not subscription eligible."
                )


# ---------------------------------------------------------------------------
# subscriptiq.subscription.event
# ---------------------------------------------------------------------------

class SubscriptiqSubscriptionEvent(models.Model):
    """Immutable lifecycle event history for subscriptions.

    Records are created only by business methods, never by users directly.
    Write and unlink are blocked at the ACL level for all non-technical users.
    """
    _name = 'subscriptiq.subscription.event'
    _description = 'Subscription Event'
    _order = 'event_date desc, id desc'
    _rec_name = 'event_type'

    subscription_id = fields.Many2one(
        'subscriptiq.subscription',
        string="Subscription",
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    event_type = fields.Selection(
        selection=EVENT_TYPE_SELECTION,
        string="Event Type",
        required=True,
        readonly=True,
    )
    previous_state = fields.Selection(
        selection=STATE_SELECTION,
        string="Previous State",
        readonly=True,
    )
    new_state = fields.Selection(
        selection=STATE_SELECTION,
        string="New State",
        readonly=True,
    )
    event_date = fields.Datetime(
        string="Event Date",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string="Triggered By",
        default=lambda self: self.env.uid,
        readonly=True,
    )
    reason = fields.Text(
        string="Reason / Notes",
        readonly=True,
    )
    metadata = fields.Json(
        string="Metadata",
        readonly=True,
        help="Structured context data for billing or audit events.",
    )
