# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class BillingRun(models.Model):
    """
    Tracks each billing execution triggered by the primary scheduler or manual wizard.
    Provides execution auditing, batch tracking, and aggregated metrics.
    """
    _name = 'subscriptiq.billing.run'
    _description = 'Subscription Billing Run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'run_date desc, id desc'

    name = fields.Char(
        string='Run Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    run_date = fields.Datetime(
        string='Run Datetime (UTC)',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    billing_date = fields.Date(
        string='Billing Date',
        required=True,
        default=fields.Date.context_today,
        help="Target date for which subscriptions are evaluated.",
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('done', 'Completed'),
            ('partial', 'Partial Failures'),
            ('failed', 'Failed'),
        ],
        string='Status',
        required=True,
        default='draft',
        tracking=True,
        index=True,
    )
    triggered_by = fields.Selection(
        selection=[
            ('cron', 'Scheduled Action'),
            ('manual', 'Manual Trigger'),
        ],
        string='Triggered By',
        required=True,
        default='manual',
    )
    triggered_by_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Triggered By User',
        default=lambda self: self.env.user,
    )
    item_ids = fields.One2many(
        comodel_name='subscriptiq.billing.run.item',
        inverse_name='billing_run_id',
        string='Processed Subscriptions',
    )
    subscription_count = fields.Integer(
        string='Subscriptions Evaluated',
        compute='_compute_run_metrics',
        store=True,
    )
    invoice_count = fields.Integer(
        string='Invoices Created',
        compute='_compute_run_metrics',
        store=True,
    )
    failure_count = fields.Integer(
        string='Failures',
        compute='_compute_run_metrics',
        store=True,
    )
    skipped_count = fields.Integer(
        string='Skipped',
        compute='_compute_run_metrics',
        store=True,
    )
    ack_failure_count = fields.Integer(
        string='Acknowledgement Failures',
        compute='_compute_run_metrics',
        store=True,
        help="Invoices successfully committed but awaiting Member 1 acknowledgement.",
    )
    total_billed = fields.Monetary(
        string='Total Amount Billed',
        compute='_compute_run_metrics',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    notes = fields.Text(string='Notes')
    error_message = fields.Text(string='Error Detail')
    run_end_datetime = fields.Datetime(string='End Datetime (UTC)')
    duration_seconds = fields.Integer(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True,
    )

    @api.depends('item_ids.state', 'item_ids.invoice_id.amount_total')
    def _compute_run_metrics(self):
        for run in self:
            items = run.item_ids
            run.subscription_count = len(items)
            run.invoice_count = len(items.filtered(lambda i: i.state in ('success', 'ack_failed') and i.invoice_id))
            run.failure_count = len(items.filtered(lambda i: i.state == 'failed'))
            run.skipped_count = len(items.filtered(lambda i: i.state == 'skipped'))
            run.ack_failure_count = len(items.filtered(lambda i: i.state == 'ack_failed'))

            total = 0.0
            for item in items:
                if item.invoice_id and item.state in ('success', 'ack_failed'):
                    total += item.invoice_id.amount_total
            run.total_billed = total

    @api.depends('run_date', 'run_end_datetime')
    def _compute_duration(self):
        for run in self:
            if run.run_date and run.run_end_datetime:
                delta = run.run_end_datetime - run.run_date
                run.duration_seconds = int(delta.total_seconds())
            else:
                run.duration_seconds = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('subscriptiq.billing.run') or _('New')
        return super().create(vals_list)

    def action_start(self):
        """Transitions run to running state."""
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_("Only draft billing runs can be started."))
        self.write({'state': 'running'})

    def action_finish(self):
        """Finalizes run metrics and sets appropriate terminal state."""
        self.ensure_one()
        self.run_end_datetime = fields.Datetime.now()
        if self.failure_count == 0 and self.ack_failure_count == 0:
            new_state = 'done'
        elif self.invoice_count > 0:
            new_state = 'partial'
        else:
            new_state = 'failed'
        self.write({'state': new_state})

    @api.model
    def _cron_execute_billing(self):
        """Cron entry point for primary daily recurring billing run."""
        from ..services.billing_engine import BillingEngine
        return BillingEngine.execute_run(self.env, triggered_by='cron')

    @api.model
    def _cron_retry_failed_invoices(self):
        """Cron entry point for retrying failed invoice generations."""
        from ..services.billing_engine import BillingEngine
        return BillingEngine.retry_failed_ledgers(self.env)


class BillingRunItem(models.Model):
    """
    Per-subscription execution record within a BillingRun.
    Serves as an immutable audit line.
    """
    _name = 'subscriptiq.billing.run.item'
    _description = 'Billing Run Subscription Item'
    _order = 'id asc'

    billing_run_id = fields.Many2one(
        comodel_name='subscriptiq.billing.run',
        string='Billing Run',
        required=True,
        ondelete='cascade',
        index=True,
    )
    billing_ledger_id = fields.Many2one(
        comodel_name='subscriptiq.billing.ledger',
        string='Billing Ledger',
        ondelete='set null',
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
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
            ('ack_failed', 'Acknowledgement Failed'),
        ],
        string='Item State',
        required=True,
        default='pending',
        index=True,
    )
    skip_reason = fields.Selection(
        selection=[
            ('already_billed', 'Already Billed'),
            ('inactive', 'Subscription Inactive'),
            ('payload_error', 'Invalid Payload'),
            ('concurrent', 'Concurrent Execution'),
        ],
        string='Skip Reason',
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Generated Invoice',
        ondelete='set null',
        index=True,
    )
    error_message = fields.Text(string='Processing Error')
    ack_error_message = fields.Text(string='Acknowledgement Error')
    billing_period_start = fields.Date(string='Period Start')
    billing_period_end = fields.Date(string='Period End')
    processing_duration_ms = fields.Integer(string='Duration (ms)')

    _sql_constraints = [
        (
            'uq_run_item_sub_per_run',
            'UNIQUE (billing_run_id, subscription_id)',
            'Each subscription can only be processed once per billing run.'
        ),
    ]
