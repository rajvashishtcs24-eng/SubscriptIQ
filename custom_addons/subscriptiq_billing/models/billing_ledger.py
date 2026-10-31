# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class BillingLedger(models.Model):
    """
    Central idempotency anchor and state machine for subscription billing.
    Enforces exactly-once billing per (subscription_id, billing_period_start, billing_period_end).
    """
    _name = 'subscriptiq.billing.ledger'
    _description = 'Subscription Billing Ledger'
    _order = 'billing_period_start desc, id desc'

    name = fields.Char(
        string='Ledger Reference',
        compute='_compute_name',
        store=True,
        index=True,
    )
    subscription_id = fields.Integer(
        string='Subscription ID',
        required=True,
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        required=True,
        index=True,
    )
    billing_period_start = fields.Date(
        string='Period Start (Inclusive)',
        required=True,
        index=True,
    )
    billing_period_end = fields.Date(
        string='Period End (Inclusive)',
        required=True,
        index=True,
    )
    billing_frequency = fields.Selection(
        selection=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('yearly', 'Yearly'),
        ],
        string='Billing Frequency',
        required=True,
        default='monthly',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('failed', 'Failed'),
            ('ack_pending', 'Acknowledgement Pending'),
            ('ack_failed', 'Acknowledgement Failed'),
            ('succeeded', 'Succeeded'),
        ],
        string='Ledger State',
        required=True,
        default='pending',
        index=True,
        help="Six-state machine: pending -> in_progress -> ack_pending -> succeeded (or failed / ack_failed).",
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Posted Invoice',
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    draft_invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Draft Working Invoice',
        readonly=True,
        ondelete='set null',
    )
    discount_reservation_id = fields.Many2one(
        comodel_name='subscriptiq.discount.reservation',
        string='Active Discount Reservation',
        readonly=True,
        ondelete='set null',
    )
    retry_count = fields.Integer(
        string='Invoice Retry Attempts',
        default=0,
        required=True,
    )
    max_retries = fields.Integer(
        string='Max Invoice Retries',
        default=3,
        required=True,
    )
    next_retry_at = fields.Datetime(
        string='Earliest Next Invoice Retry',
        index=True,
    )
    last_error_message = fields.Text(string='Last Invoice Error')
    first_attempted_at = fields.Datetime(string='First Attempt Timestamp')
    succeeded_at = fields.Datetime(string='Invoice Succeeded Timestamp')
    billing_run_id = fields.Many2one(
        comodel_name='subscriptiq.billing.run',
        string='Originating Billing Run',
        ondelete='set null',
    )
    ack_retry_count = fields.Integer(
        string='Ack Retry Attempts',
        default=0,
        required=True,
    )
    ack_max_retries = fields.Integer(
        string='Max Ack Retries',
        default=5,
        required=True,
    )
    ack_retry_at = fields.Datetime(
        string='Earliest Next Ack Retry',
        index=True,
    )
    ack_error_message = fields.Text(string='Last Ack Error')
    acknowledged_at = fields.Datetime(string='Member 1 Acknowledged Timestamp')

    _sql_constraints = [
        (
            'uq_ledger_sub_period',
            'UNIQUE (subscription_id, billing_period_start, billing_period_end)',
            'A billing ledger entry already exists for this subscription and billing period.'
        ),
    ]

    @api.depends('subscription_id', 'billing_period_start')
    def _compute_name(self):
        for record in self:
            if record.subscription_id and record.billing_period_start:
                record.name = f"SUB-{record.subscription_id}/{record.billing_period_start}"
            else:
                record.name = _("Draft Ledger")

    def action_mark_in_progress(self):
        """Sets ledger to in_progress before invoice processing."""
        for record in self:
            if record.state in ('succeeded', 'ack_pending'):
                raise UserError(_("Cannot process an already invoiced ledger entry."))
            vals = {'state': 'in_progress'}
            if not record.first_attempted_at:
                vals['first_attempted_at'] = fields.Datetime.now()
            record.write(vals)

    def action_mark_ack_pending(self, invoice_id):
        """Called upon successful invoice posting commit inside savepoint."""
        self.write({
            'state': 'ack_pending',
            'invoice_id': invoice_id,
            'draft_invoice_id': False,
            'succeeded_at': fields.Datetime.now(),
        })

    def action_mark_succeeded(self):
        """Called when Member 1 acknowledges billing success."""
        self.write({
            'state': 'succeeded',
            'acknowledged_at': fields.Datetime.now(),
            'ack_error_message': False,
        })

    def action_mark_failed(self, error_message: str):
        """Called when invoice generation or posting fails prior to commit."""
        params = self.env['ir.config_parameter'].sudo()
        base_hours = int(params.get_param('subscriptiq_billing.billing_retry_base_hours', 4))
        for record in self:
            new_retry_count = record.retry_count + 1
            # Exponential backoff formula: base_hours * (retry_count ** 2)
            delay_hours = base_hours * (new_retry_count ** 2)
            next_retry = fields.Datetime.now() + timedelta(hours=delay_hours)

            record.write({
                'state': 'failed',
                'retry_count': new_retry_count,
                'next_retry_at': next_retry if new_retry_count < record.max_retries else False,
                'last_error_message': error_message,
                'draft_invoice_id': False,
            })

    def action_mark_ack_failed(self, error_message: str):
        """Called when post-invoice acknowledgement fails (invoice is preserved)."""
        from ..services.acknowledgement_service import AcknowledgementService
        for record in self:
            new_ack_retries = record.ack_retry_count + 1
            next_retry = AcknowledgementService.compute_next_ack_retry(self.env, new_ack_retries)
            record.write({
                'state': 'ack_failed',
                'ack_retry_count': new_ack_retries,
                'ack_retry_at': next_retry if new_ack_retries < record.ack_max_retries else False,
                'ack_error_message': error_message,
            })

    def action_cancel_draft_invoice(self):
        """
        Handles draft invoice cancellation by an administrator (T-21).
        Releases any active discount reservation and returns ledger to failed state
        without incrementing system failure retry count.
        """
        for record in self:
            if record.state != 'in_progress' and not record.draft_invoice_id:
                continue

            if record.discount_reservation_id:
                record.discount_reservation_id.action_release()

            if record.draft_invoice_id and record.draft_invoice_id.state == 'draft':
                record.draft_invoice_id.button_cancel()

            record.write({
                'state': 'failed',
                'draft_invoice_id': False,
                'last_error_message': _("Draft invoice was cancelled by administrator."),
                'next_retry_at': fields.Datetime.now() + timedelta(minutes=15),
            })

    @api.model
    def _cron_retry_acknowledgement(self):
        """Cron entry point for retrying Member 1 acknowledgement on posted invoices."""
        from ..services.acknowledgement_service import AcknowledgementService
        return AcknowledgementService.retry_acknowledgement(self.env)
