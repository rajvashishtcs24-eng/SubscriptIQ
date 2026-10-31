# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch
from datetime import date
from .common import BillingTestCommon, make_payload
from ..services.billing_engine import BillingEngine
from ..services.subscription_adapter import SubscriptionAdapter


class TestMember1Interface(BillingTestCommon):
    """
    Tests error propagation, payload validation, and boundary adapter behavior with Member 1.
    """

    def setUp(self):
        super().setUp()
        self.billing_date = date(2026, 11, 1)

    def test_payload_missing_partner_fails(self):
        """Payload missing partner_id fails payload validation and marks item failed."""
        payload = make_payload(subscription_id=801, partner_id=False)

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[801]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            item = run.item_ids.filtered(lambda i: i.subscription_id == 801)
            self.assertEqual(item.state, 'skipped')
            self.assertEqual(item.skip_reason, 'payload_error')

    def test_payload_empty_lines_fails(self):
        """Payload with empty lines fails validation."""
        payload = make_payload(subscription_id=802, lines=[])

        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[802]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', return_value=payload):

            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            item = run.item_ids.filtered(lambda i: i.subscription_id == 802)
            self.assertEqual(item.state, 'skipped')
            self.assertEqual(item.skip_reason, 'payload_error')

    def test_register_failure_does_not_crash_billing(self):
        """Best-effort register_billing_failure notification failure does not interrupt pipeline."""
        with patch.object(SubscriptionAdapter, 'get_subscriptions_due_for_billing', return_value=[803]), \
             patch.object(SubscriptionAdapter, 'get_billing_payload', side_effect=ValueError("Payload corrupt")), \
             patch.object(SubscriptionAdapter, 'register_billing_failure', side_effect=Exception("Notification network drop")):

            # Should not raise exception
            run = BillingEngine.execute_run(self.env, billing_date=self.billing_date)
            self.assertEqual(run.state, 'done')  # Corrupt payload was skipped gracefully
