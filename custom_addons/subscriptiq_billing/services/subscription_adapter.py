# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import logging
from typing import List, Dict, Any, Optional

_logger = logging.getLogger(__name__)


class SubscriptionAdapter:
    """
    Isolated boundary adapter for Member 1's subscriptiq.subscription ORM interface.
    Adheres to the Rev 3 integration contract without direct Python imports.
    """

    @classmethod
    def get_subscriptions_due_for_billing(cls, env, billing_date) -> List[int]:
        """
        Retrieves active subscriptions due for billing on or before billing_date.
        Calls env['subscriptiq.subscription'].get_subscriptions_due_for_billing(billing_date).
        Strictly excludes paused, closed, cancelled, or draft subscriptions.
        """
        model_name = 'subscriptiq.subscription'
        if model_name in env:
            sub_model = env[model_name]
            if hasattr(sub_model, 'get_subscriptions_due_for_billing'):
                return sub_model.get_subscriptions_due_for_billing(billing_date)
            # Default search fallback if model exists without helper method:
            # Strictly active, next_billing_date <= billing_date (never bill in advance)
            domain = [
                ('next_billing_date', '<=', billing_date),
                ('state', '=', 'active'),
            ]
            return sub_model.search(domain).ids

        _logger.warning("Model %s is not installed. Returning empty subscription list.", model_name)
        return []

    @classmethod
    def get_billing_payload(cls, env, subscription_id: int) -> Dict[str, Any]:
        """
        Retrieves complete billing payload for subscription_id.
        Calls env['subscriptiq.subscription'].get_billing_payload(subscription_id).

        CRITICAL PRICING BOUNDARY:
        Customer-agreed prices are snapshotted on subscription lines (line_ids).
        Billing NEVER calculates recurring invoices directly from mutable subscriptiq.plan.line prices.
        """
        model_name = 'subscriptiq.subscription'
        if model_name in env:
            sub_model = env[model_name]
            if hasattr(sub_model, 'get_billing_payload'):
                return sub_model.get_billing_payload(subscription_id)
            # Fallback if standard model record exists
            sub = sub_model.browse(subscription_id)
            if sub.exists():
                # Enforce lifecycle boundary: only active subscriptions can be billed
                sub_state = getattr(sub, 'state', 'active')
                if sub_state != 'active':
                    raise ValueError(
                        f"Subscription {subscription_id} is in non-billable state '{sub_state}'. "
                        "Billing cannot generate invoices for paused, closed, or draft subscriptions."
                    )

                return {
                    'subscription_id': sub.id,
                    'partner_id': sub.partner_id.id if hasattr(sub, 'partner_id') else False,
                    'currency_id': sub.currency_id.id if hasattr(sub, 'currency_id') else env.company.currency_id.id,
                    'fiscal_position_id': getattr(sub, 'fiscal_position_id', False) and sub.fiscal_position_id.id or False,
                    'payment_term_id': getattr(sub, 'payment_term_id', False) and sub.payment_term_id.id or False,
                    'billing_frequency': getattr(sub, 'billing_frequency', 'monthly'),
                    'next_billing_date': getattr(sub, 'next_billing_date', False),
                    'billing_day_anchor': getattr(sub, 'billing_day_anchor', 1),
                    'lines': [
                        {
                            # Product variant from subscription line snapshot
                            'product_id': line.product_id.id,
                            'name': line.name or line.product_id.display_name or line.product_id.name,
                            # Customer-agreed quantity and agreed unit price snapshot
                            'quantity': line.quantity,
                            'price_unit': line.price_unit,  # Immutable customer agreement snapshot
                            'tax_ids': line.tax_ids.ids if hasattr(line, 'tax_ids') else [],
                            'uom_id': getattr(line, 'uom_id', False) and line.uom_id.id or False,
                        }
                        for line in getattr(sub, 'line_ids', [])
                    ],
                }

        raise ValueError(f"Subscription {subscription_id} payload could not be loaded: model {model_name} missing.")

    @classmethod
    def register_billing_success(
        cls,
        env,
        subscription_id: int,
        invoice_id: int,
        next_billing_date,
    ) -> None:
        """
        Notifies Member 1 of successful invoice posting outside the invoice savepoint.
        Idempotent operation (T-22, T-23).
        """
        model_name = 'subscriptiq.subscription'
        if model_name in env:
            sub_model = env[model_name]
            if hasattr(sub_model, 'register_billing_success'):
                sub_model.register_billing_success(subscription_id, invoice_id, next_billing_date)
                return
            # Fallback field update if model exists
            sub = sub_model.browse(subscription_id)
            if sub.exists():
                vals = {}
                if hasattr(sub, 'next_billing_date'):
                    vals['next_billing_date'] = next_billing_date
                if hasattr(sub, 'last_invoice_id'):
                    vals['last_invoice_id'] = invoice_id
                if vals:
                    sub.write(vals)
                return

        _logger.info(
            "Acknowledged billing success for subscription %s (invoice: %s, next_date: %s) via adapter fallback.",
            subscription_id, invoice_id, next_billing_date
        )

    @classmethod
    def register_billing_failure(
        cls,
        env,
        subscription_id: int,
        error_message: str,
        retry_at,
    ) -> None:
        """
        Best-effort notification to Member 1 when billing fails pre-invoice.
        """
        model_name = 'subscriptiq.subscription'
        try:
            if model_name in env:
                sub_model = env[model_name]
                if hasattr(sub_model, 'register_billing_failure'):
                    sub_model.register_billing_failure(subscription_id, error_message, retry_at)
        except Exception as exc:
            _logger.warning(
                "Best-effort register_billing_failure failed for sub %s: %s",
                subscription_id, exc
            )
