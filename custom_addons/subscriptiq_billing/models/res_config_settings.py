# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    """
    Billing settings and retry parameters for SubscriptIQ.
    """
    _inherit = 'res.config.settings'

    billing_max_retries = fields.Integer(
        string='Max Invoice Generation Retries',
        default=3,
        config_parameter='subscriptiq_billing.billing_max_retries',
        help="Maximum retry attempts for pre-posting failures.",
    )
    billing_retry_base_hours = fields.Integer(
        string='Invoice Retry Base Hours',
        default=4,
        config_parameter='subscriptiq_billing.billing_retry_base_hours',
        help="Base delay hours for quadratic/exponential backoff.",
    )
    billing_ack_max_retries = fields.Integer(
        string='Max Acknowledgement Retries',
        default=5,
        config_parameter='subscriptiq_billing.billing_ack_max_retries',
        help="Maximum retry attempts for post-posting acknowledgement.",
    )
    billing_ack_retry_base_hours = fields.Integer(
        string='Acknowledgement Retry Base Hours',
        default=2,
        config_parameter='subscriptiq_billing.billing_ack_retry_base_hours',
        help="Base delay hours for acknowledgement exponential backoff.",
    )
    billing_batch_size = fields.Integer(
        string='Billing Run Batch Commit Size',
        default=100,
        config_parameter='subscriptiq_billing.billing_batch_size',
        help="Number of subscriptions committed in a single batch during a billing run.",
    )
    billing_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Default Billing Journal',
        config_parameter='subscriptiq_billing.billing_journal_id',
        domain="[('type', '=', 'sale')]",
    )
    billing_pg_lock_key = fields.Integer(
        string='Advisory Lock Key',
        default=1001,
        config_parameter='subscriptiq_billing.billing_pg_lock_key',
        help="PostgreSQL advisory lock key used to prevent concurrent billing runs.",
    )
