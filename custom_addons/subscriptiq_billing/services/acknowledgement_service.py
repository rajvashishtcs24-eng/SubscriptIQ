# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import logging
from datetime import timedelta
from odoo import fields
from .period_service import PeriodService
from .subscription_adapter import SubscriptionAdapter

_logger = logging.getLogger(__name__)


class AcknowledgementService:
    """
    Dedicated recovery service for post-invoice acknowledgement failures.
    Operates strictly outside the invoice transaction savepoint (T-22, T-23).
    Ensures committed invoices are never rolled back and retries with exponential backoff.
    """

    @classmethod
    def compute_next_ack_retry(cls, env, current_retry_count: int):
        """Calculates exponential backoff delay based on res.config.settings."""
        params = env['ir.config_parameter'].sudo()
        base_hours = int(params.get_param('subscriptiq_billing.billing_ack_retry_base_hours', 2))
        delay_hours = base_hours * (2 ** max(0, current_retry_count - 1))
        return fields.Datetime.now() + timedelta(hours=delay_hours)

    @classmethod
    def retry_acknowledgement(cls, env, ledger_ids=None, batch_size=100) -> int:
        """
        Executes acknowledgement retry for ledgers in ack_pending or ack_failed state.
        Called by ir_cron_ack_retry or the manual wizard.

        Returns:
            int: Number of successfully acknowledged ledgers.
        """
        domain = [
            ('state', 'in', ['ack_pending', 'ack_failed']),
            ('invoice_id', '!=', False),
            '|',
            ('ack_retry_at', '<=', fields.Datetime.now()),
            ('ack_retry_at', '=', False),
        ]
        if ledger_ids:
            domain.append(('id', 'in', ledger_ids))

        ledgers = env['subscriptiq.billing.ledger'].search(domain, limit=batch_size)
        if not ledgers:
            return 0

        _logger.info("Found %d ledgers due for acknowledgement retry.", len(ledgers))
        success_count = 0

        for ledger in ledgers:
            # Recompute next billing date from ledger data
            try:
                _, _, computed_next_date = PeriodService.compute_period(
                    ledger.billing_frequency,
                    ledger.billing_period_start,
                    ledger.billing_period_start.day,
                )
            except Exception:
                computed_next_date = ledger.billing_period_end + timedelta(days=1)

            try:
                _logger.info(
                    "Retrying acknowledgement for ledger %s (sub: %s, invoice: %s)",
                    ledger.id, ledger.subscription_id, ledger.invoice_id.id
                )
                SubscriptionAdapter.register_billing_success(
                    env,
                    ledger.subscription_id,
                    ledger.invoice_id.id,
                    computed_next_date,
                )
                ledger.write({
                    'state': 'succeeded',
                    'acknowledged_at': fields.Datetime.now(),
                    'ack_error_message': False,
                })
                success_count += 1
                _logger.info("Acknowledgement retry succeeded for ledger %s.", ledger.id)

            except Exception as exc:
                new_retry_count = ledger.ack_retry_count + 1
                next_retry = cls.compute_next_ack_retry(env, new_retry_count)
                _logger.warning(
                    "Acknowledgement retry failed for ledger %s (attempt %d/%d): %s",
                    ledger.id, new_retry_count, ledger.ack_max_retries, exc
                )
                ledger.write({
                    'state': 'ack_failed',
                    'ack_retry_count': new_retry_count,
                    'ack_retry_at': next_retry if new_retry_count < ledger.ack_max_retries else False,
                    'ack_error_message': str(exc),
                })

        return success_count
