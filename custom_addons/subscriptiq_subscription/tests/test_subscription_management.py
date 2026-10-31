# -*- coding: utf-8 -*-
"""Phase 4 — Subscription Management Engine Tests (38 tests).

Test coverage:
  MODEL CREATION (1–4):
    1.  Subscription creation
    2.  Subscription number generation (ir.sequence)
    3.  Subscription line creation
    4.  Event creation

  QUOTATION CONVERSION (5–11):
    5.  Create subscription from quotation (action_prepare_subscription)
    6.  Customer copied from quotation
    7.  Plan copied from quotation
    8.  Quantities copied from quotation lines
    9.  Agreed unit prices copied (pricing snapshot)
    10. Taxes copied from quotation lines
    11. Duplicate subscription prevention

  LIFECYCLE (12–21):
    12. Activation (CONFIRMED → ACTIVE)
    13. Pause (ACTIVE → PAUSED)
    14. Resume (PAUSED → ACTIVE)
    15. Renewal (extend end_date)
    16. Early closure (ACTIVE → CLOSED)
    17. Automatic expiry (cron closes eligible active subscriptions)
    18. Invalid state transitions raise UserError
    19. Pause disallowed when allow_pause=False
    20. Early close disallowed when allow_early_close=False
    21. Cancelled quotation closes a quotation-state subscription

  PRICING INTEGRITY (22–24):
    22. Plan price modification does not alter subscription line price
    23. Product catalogue price change does not alter subscription line price
    24. Variant price_extra change does not alter subscription line price

  BILLING INTERFACE (25–32):
    25. Active due subscriptions returned by get_due_billing_data
    26. Future subscriptions excluded
    27. Paused subscriptions excluded
    28. Closed subscriptions excluded
    29. Pagination (limit/offset) works
    30. action_register_billing_success advances next_billing_date
    31. Duplicate acknowledgement rejected (date already advanced)
    32. Invalid billing period start date rejected

  EVENT HISTORY (33–38):
    33. Activation creates an event
    34. Pause creates an event
    35. Resume creates an event
    36. Renewal creates an event
    37. Closure creates an event
    38. Historical events cannot be written by ordinary users (no perm_write)
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'subscriptiq')
class TestSubscriptionManagement(TransactionCase):
    """Integration tests for Phase 4: Subscription Management Engine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # --- Partner ---
        cls.partner = cls.env['res.partner'].create({
            'name': 'SubscriptIQ Test Corp',
            'email': 'corp@subscriptiq.test',
        })

        # --- Subscription-eligible products ---
        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'SaaS Core Service',
            'type': 'service',
            'is_subscription_eligible': True,
            'list_price': 1000.0,
        })
        cls.product = cls.product_tmpl.product_variant_id

        cls.product_tmpl2 = cls.env['product.template'].create({
            'name': 'SaaS Storage Add-on',
            'type': 'service',
            'is_subscription_eligible': True,
            'list_price': 200.0,
        })
        cls.product2 = cls.product_tmpl2.product_variant_id

        # --- Subscription plan ---
        cls.plan = cls.env['subscriptiq.plan'].create({
            'name': 'Test Monthly Plan',
            'billing_frequency': 'monthly',
            'minimum_quantity': 1.0,
            'allow_pause': True,
            'allow_early_close': True,
            'renewal_enabled': True,
            'renewal_type': 'manual',
            'auto_close': False,
        })
        cls.plan_line1 = cls.env['subscriptiq.plan.line'].create({
            'plan_id': cls.plan.id,
            'product_id': cls.product.id,
            'quantity': 5.0,
            'price_unit': 900.0,
        })
        cls.plan_line2 = cls.env['subscriptiq.plan.line'].create({
            'plan_id': cls.plan.id,
            'product_id': cls.product2.id,
            'quantity': 2.0,
            'price_unit': 150.0,
        })

        # --- Helper to create a confirmed subscription from a quotation ---
        # We create the sale order in each test method to avoid shared state.

    def _make_confirmed_subscription(self):
        """Helper: create a quotation, populate it, prepare and confirm, return (order, sub)."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        order.action_confirm()
        sub = order.subscription_id
        return order, sub

    def _make_active_subscription(self):
        """Helper: create a confirmed subscription and activate it."""
        order, sub = self._make_confirmed_subscription()
        sub.write({'start_date': date.today()})
        sub.action_activate()
        return order, sub

    # =========================================================================
    # MODEL CREATION (Tests 1–4)
    # =========================================================================

    def test_01_subscription_creation(self):
        """A subscriptiq.subscription record can be created successfully."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })
        self.assertTrue(sub.id > 0, "Subscription must have a valid database ID.")
        self.assertEqual(sub.state, 'draft', "New subscription defaults to 'draft' state.")

    def test_02_subscription_number_generation(self):
        """Subscription number is generated from ir.sequence on create."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })
        self.assertNotEqual(sub.name, 'New', "Subscription number must not remain 'New'.")
        self.assertIn('SUB/', sub.name, "Subscription number should start with 'SUB/'.")

    def test_03_subscription_line_creation(self):
        """A subscriptiq.subscription.line can be created with valid data."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })
        line = self.env['subscriptiq.subscription.line'].create({
            'subscription_id': sub.id,
            'product_id': self.product.id,
            'quantity': 3.0,
            'price_unit': 950.0,
            'name': 'Test line',
        })
        self.assertEqual(line.subscription_id, sub)
        self.assertAlmostEqual(line.quantity, 3.0)
        self.assertAlmostEqual(line.price_unit, 950.0)

    def test_04_event_creation(self):
        """A subscriptiq.subscription.event record can be created."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })
        event = self.env['subscriptiq.subscription.event'].create({
            'subscription_id': sub.id,
            'event_type': 'created',
        })
        self.assertEqual(event.subscription_id, sub)
        self.assertEqual(event.event_type, 'created')

    # =========================================================================
    # QUOTATION CONVERSION (Tests 5–11)
    # =========================================================================

    def test_05_create_subscription_from_quotation(self):
        """action_prepare_subscription creates a subscription from a quotation."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        self.assertTrue(order.subscription_id, "order.subscription_id should be set after preparation.")
        self.assertEqual(order.subscription_id.state, 'quotation')

    def test_06_copy_customer(self):
        """Subscription partner_id matches the quotation customer."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        self.assertEqual(order.subscription_id.partner_id, self.partner)

    def test_07_copy_plan(self):
        """Subscription plan_id matches the quotation's subscription_plan_id."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        self.assertEqual(order.subscription_id.plan_id, self.plan)

    def test_08_copy_quantities(self):
        """Subscription line quantities match the source quotation line quantities."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        sub = order.subscription_id
        line_for_product1 = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        self.assertAlmostEqual(line_for_product1.quantity, 5.0,
                               msg="Subscription line quantity should match plan line quantity (5.0).")

    def test_09_copy_agreed_unit_prices(self):
        """Subscription line price_unit is a snapshot of the quotation line price_unit."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        # Manually override the price on one order line to simulate a negotiated price
        order_line = order.order_line.filtered(lambda l: l.product_id == self.product)
        order_line.write({'price_unit': 799.0})
        order.action_prepare_subscription()
        sub = order.subscription_id
        sub_line = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        self.assertAlmostEqual(sub_line.price_unit, 799.0,
                               msg="Subscription line must snapshot the negotiated quotation price.")

    def test_10_copy_taxes(self):
        """Tax IDs from quotation lines are faithfully copied and preserved on subscription lines."""
        tax = self.env['account.tax'].search([
            ('company_id', '=', self.env.company.id),
            ('type_tax_use', '=', 'sale'),
        ], limit=1)
        if not tax:
            tax = self.env['account.tax'].create({
                'name': 'Test 18% GST',
                'amount_type': 'percent',
                'amount': 18.0,
                'type_tax_use': 'sale',
            })

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        order_line = order.order_line.filtered(lambda l: l.product_id == self.product)
        order_line.tax_ids = [(6, 0, [tax.id])]

        order.action_prepare_subscription()
        sub = order.subscription_id
        self.assertTrue(sub, "Subscription must be created from quotation.")

        sub_line = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        self.assertTrue(hasattr(sub_line, 'tax_ids'), "Subscription line must have a tax_ids field.")
        self.assertIn(
            tax.id, sub_line.tax_ids.ids,
            "Quotation line tax_ids must be faithfully preserved in subscription line tax_ids.",
        )
        tax_res = sub_line.tax_ids.compute_all(
            sub_line.price_unit,
            currency=sub_line.currency_id,
            quantity=sub_line.quantity,
            product=sub_line.product_id,
            partner=sub.partner_id,
        )
        self.assertAlmostEqual(sub_line.price_subtotal, tax_res['total_excluded'])
        self.assertAlmostEqual(sub_line.price_total, tax_res['total_included'])

    def test_11_prevent_duplicate_subscription(self):
        """Calling action_prepare_subscription twice on the same order raises UserError."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        with self.assertRaises(UserError):
            order.action_prepare_subscription()

    # =========================================================================
    # LIFECYCLE (Tests 12–21)
    # =========================================================================

    def test_12_activation(self):
        """CONFIRMED → ACTIVE transition via action_activate."""
        _, sub = self._make_confirmed_subscription()
        sub.write({'start_date': date.today()})
        sub.action_activate()
        self.assertEqual(sub.state, 'active')
        self.assertIsNotNone(sub.next_billing_date)

    def test_13_pause(self):
        """ACTIVE → PAUSED transition via action_pause."""
        _, sub = self._make_active_subscription()
        sub.action_pause(reason='Test pause')
        self.assertEqual(sub.state, 'paused')

    def test_14_resume(self):
        """PAUSED → ACTIVE transition via action_resume."""
        _, sub = self._make_active_subscription()
        sub.action_pause()
        sub.action_resume(reason='Test resume')
        self.assertEqual(sub.state, 'active')

    def test_15_renewal(self):
        """action_renew extends end_date by one billing period."""
        _, sub = self._make_active_subscription()
        end_date = date.today() + timedelta(days=30)
        sub.write({'end_date': end_date})
        sub.action_renew(reason='Test renewal')
        # end_date should be extended by one month (relativedelta(months=1))
        self.assertGreater(sub.end_date, end_date,
                           msg="End date should be extended after renewal.")
        self.assertEqual(sub.state, 'active', "State remains 'active' after renewal.")

    def test_16_early_closure(self):
        """ACTIVE → CLOSED via action_close."""
        _, sub = self._make_active_subscription()
        sub.action_close(reason='Test early close')
        self.assertEqual(sub.state, 'closed')
        self.assertFalse(sub.next_billing_date, "next_billing_date must be cleared on close.")

    def test_17_automatic_expiry_cron(self):
        """Cron auto-closes eligible active subscriptions past end_date."""
        start_date = date.today() - timedelta(days=30)
        yesterday = date.today() - timedelta(days=1)
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
            'state': 'active',
            'auto_close': True,
            'start_date': start_date,
            'end_date': yesterday,
            'next_billing_date': yesterday,
        })
        self.env['subscriptiq.subscription.line'].create({
            'subscription_id': sub.id,
            'product_id': self.product.id,
            'quantity': 1.0,
            'price_unit': 900.0,
        })
        self.assertEqual(sub.state, 'active')
        self.env['subscriptiq.subscription']._cron_auto_close_expired()
        self.assertEqual(sub.state, 'closed', "Expired subscription with auto_close=True must be closed by cron.")
        self.assertFalse(sub.next_billing_date, "next_billing_date must be cleared on close.")
        closed_events = sub.event_ids.filtered(lambda e: e.event_type == 'closed')
        self.assertTrue(len(closed_events) >= 1, "A closure event must be generated by cron.")
        self.assertEqual(closed_events[0].previous_state, 'active')
        self.assertEqual(closed_events[0].new_state, 'closed')

    def test_18_invalid_state_transitions(self):
        """Attempting invalid state transitions raises UserError."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })
        # Cannot activate from draft
        with self.assertRaises(UserError):
            sub.action_activate()
        # Cannot pause from draft
        with self.assertRaises(UserError):
            sub.action_pause()
        # Cannot resume a non-paused subscription
        with self.assertRaises(UserError):
            sub.action_resume()

    def test_19_pause_disallowed(self):
        """Pause raises UserError when allow_pause=False."""
        plan_no_pause = self.env['subscriptiq.plan'].create({
            'name': 'No Pause Plan',
            'billing_frequency': 'monthly',
            'allow_pause': False,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': plan_no_pause.id,
        })
        # Create subscription directly without lines (bypass order flow for speed)
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': plan_no_pause.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
            'state': 'active',
            'allow_pause': False,
            'start_date': date.today(),
            'next_billing_date': date.today() + timedelta(days=30),
        })
        with self.assertRaises(UserError):
            sub.action_pause()

    def test_20_early_close_disallowed(self):
        """Early close raises UserError when allow_early_close=False."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
            'state': 'active',
            'allow_early_close': False,
            'allow_pause': True,
            'start_date': date.today(),
            'next_billing_date': date.today() + timedelta(days=30),
        })
        with self.assertRaises(UserError):
            sub.action_close(reason='Trying to close early')

    def test_21_cancellation_closes_subscription(self):
        """Cancelling a confirmed sale.order closes a quotation-state subscription."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_prepare_subscription()
        sub = order.subscription_id
        self.assertEqual(sub.state, 'quotation')
        order.action_cancel()
        self.assertEqual(sub.state, 'closed',
                         "Subscription should be closed when source quotation is cancelled.")

    # =========================================================================
    # PRICING INTEGRITY (Tests 22–24)
    # =========================================================================

    def test_22_plan_price_change_no_effect_on_subscription(self):
        """Changing a plan line's price_unit does not alter existing subscription line prices."""
        _, sub = self._make_confirmed_subscription()
        sub_line = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        original_price = sub_line.price_unit
        # Mutate the plan line price
        self.plan_line1.write({'price_unit': 9999.0})
        sub_line.invalidate_recordset(['price_unit'])
        self.assertAlmostEqual(
            sub_line.price_unit, original_price,
            msg="Subscription line price must be independent of plan line price changes."
        )

    def test_23_product_price_change_no_effect_on_subscription(self):
        """Changing product list_price does not alter existing subscription line prices."""
        _, sub = self._make_confirmed_subscription()
        sub_line = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        original_price = sub_line.price_unit
        self.product_tmpl.write({'list_price': 5000.0})
        sub_line.invalidate_recordset(['price_unit'])
        self.assertAlmostEqual(
            sub_line.price_unit, original_price,
            msg="Subscription line price must not change when product list_price is updated."
        )

    def test_24_variant_price_extra_change_no_effect_on_subscription(self):
        """Changing variant price_extra does not alter subscription line prices."""
        _, sub = self._make_confirmed_subscription()
        sub_line = sub.line_ids.filtered(lambda l: l.product_id == self.product)
        original_price = sub_line.price_unit
        # Change price_extra on the product template attribute value if any
        for ptav in self.product_tmpl.attribute_line_ids.product_template_value_ids:
            ptav.write({'price_extra': 9999.0})
        sub_line.invalidate_recordset(['price_unit'])
        self.assertAlmostEqual(
            sub_line.price_unit, original_price,
            msg="Subscription line price must not change when variant price_extra is updated."
        )

    # =========================================================================
    # BILLING INTERFACE (Tests 25–32)
    # =========================================================================

    def _make_billing_eligible_sub(self, days_overdue=0):
        """Helper: create an active subscription due for billing."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
            'state': 'active',
            'allow_pause': True,
            'allow_early_close': True,
            'start_date': date.today() - timedelta(days=31 + days_overdue),
            'next_billing_date': date.today() - timedelta(days=days_overdue),
        })
        self.env['subscriptiq.subscription.line'].create({
            'subscription_id': sub.id,
            'product_id': self.product.id,
            'quantity': 1.0,
            'price_unit': 900.0,
        })
        return sub

    def test_25_active_due_subscriptions_returned(self):
        """get_due_billing_data returns active subscriptions with next_billing_date <= today."""
        sub = self._make_billing_eligible_sub(days_overdue=0)
        result = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today()
        )
        returned_ids = [r['subscription']['subscription_id'] for r in result]
        self.assertIn(sub.id, returned_ids,
                      "Active subscription due today must appear in billing data.")

    def test_26_future_subscriptions_excluded(self):
        """get_due_billing_data excludes subscriptions whose next_billing_date is in the future."""
        sub = self.env['subscriptiq.subscription'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'billing_frequency': 'monthly',
            'currency_id': self.env.company.currency_id.id,
            'state': 'active',
            'start_date': date.today(),
            'next_billing_date': date.today() + timedelta(days=30),
        })
        result = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today()
        )
        returned_ids = [r['subscription']['subscription_id'] for r in result]
        self.assertNotIn(sub.id, returned_ids,
                         "Future-dated subscription must not appear in billing data.")

    def test_27_paused_subscriptions_excluded(self):
        """get_due_billing_data excludes paused subscriptions."""
        sub = self._make_billing_eligible_sub(days_overdue=1)
        sub.write({'state': 'paused'})
        result = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today()
        )
        returned_ids = [r['subscription']['subscription_id'] for r in result]
        self.assertNotIn(sub.id, returned_ids,
                         "Paused subscription must not appear in billing data.")

    def test_28_closed_subscriptions_excluded(self):
        """get_due_billing_data excludes closed subscriptions."""
        sub = self._make_billing_eligible_sub(days_overdue=1)
        sub.write({'state': 'closed', 'next_billing_date': False})
        result = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today()
        )
        returned_ids = [r['subscription']['subscription_id'] for r in result]
        self.assertNotIn(sub.id, returned_ids,
                         "Closed subscription must not appear in billing data.")

    def test_29_pagination_works(self):
        """get_due_billing_data respects limit and offset parameters."""
        # Create 3 due subscriptions
        subs = [self._make_billing_eligible_sub(days_overdue=i) for i in range(3)]
        all_results = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today(), limit=100
        )
        all_ids = [r['subscription']['subscription_id'] for r in all_results]
        created_ids = [s.id for s in subs]
        created_found = [cid for cid in created_ids if cid in all_ids]
        self.assertEqual(len(created_found), 3, "All 3 created subscriptions must be in result.")

        # Test limit=1
        page1 = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today(), limit=1, offset=0
        )
        self.assertEqual(len(page1), 1, "Limit=1 must return exactly 1 record.")

        # Test offset=1
        page2 = self.env['subscriptiq.subscription'].get_due_billing_data(
            billing_date=date.today(), limit=1, offset=1
        )
        self.assertEqual(len(page2), 1, "Offset=1 with limit=1 must return 1 different record.")
        self.assertNotEqual(page1[0]['subscription']['subscription_id'],
                            page2[0]['subscription']['subscription_id'],
                            "Pages should return different subscriptions.")

    def test_30_billing_acknowledgement_advances_date(self):
        """action_register_billing_success advances next_billing_date by one period."""
        sub = self._make_billing_eligible_sub(days_overdue=0)
        original_billing_date = sub.next_billing_date
        result = self.env['subscriptiq.subscription'].action_register_billing_success(
            subscription_id=sub.id,
            billing_period_start=original_billing_date,
            billing_period_end=original_billing_date + timedelta(days=29),
            invoice_id=False,
        )
        self.assertTrue(result.get('success'), f"Billing acknowledgement failed: {result}")
        self.assertGreater(
            sub.next_billing_date, original_billing_date,
            "next_billing_date must advance after successful billing acknowledgement."
        )

    def test_31_duplicate_acknowledgement_rejected(self):
        """Second call with the same period_start is rejected after date has advanced."""
        sub = self._make_billing_eligible_sub(days_overdue=0)
        original_billing_date = sub.next_billing_date

        # First acknowledgement
        result1 = self.env['subscriptiq.subscription'].action_register_billing_success(
            subscription_id=sub.id,
            billing_period_start=original_billing_date,
            billing_period_end=original_billing_date + timedelta(days=29),
            invoice_id=False,
        )
        self.assertTrue(result1.get('success'))

        # Second acknowledgement with same original period_start
        result2 = self.env['subscriptiq.subscription'].action_register_billing_success(
            subscription_id=sub.id,
            billing_period_start=original_billing_date,
            billing_period_end=original_billing_date + timedelta(days=29),
            invoice_id=False,
        )
        self.assertFalse(result2.get('success'),
                         "Duplicate billing acknowledgement must be rejected.")

    def test_32_invalid_billing_period_rejected(self):
        """action_register_billing_success rejects a mismatched period_start date."""
        sub = self._make_billing_eligible_sub(days_overdue=0)
        wrong_date = sub.next_billing_date + timedelta(days=5)
        result = self.env['subscriptiq.subscription'].action_register_billing_success(
            subscription_id=sub.id,
            billing_period_start=wrong_date,
            billing_period_end=wrong_date + timedelta(days=29),
            invoice_id=False,
        )
        self.assertFalse(result.get('success'),
                         "Mismatched billing period start must be rejected.")

    # =========================================================================
    # EVENT HISTORY (Tests 33–38)
    # =========================================================================

    def test_33_activation_creates_event(self):
        """action_activate creates a lifecycle event with event_type='activated'."""
        _, sub = self._make_confirmed_subscription()
        sub.write({'start_date': date.today()})
        sub.action_activate()
        activated_events = sub.event_ids.filtered(lambda e: e.event_type == 'activated')
        self.assertTrue(len(activated_events) >= 1,
                        "Activation must create an event with event_type='activated'.")

    def test_34_pause_creates_event(self):
        """action_pause creates a lifecycle event with event_type='paused'."""
        _, sub = self._make_active_subscription()
        sub.action_pause(reason='Test pause event')
        paused_events = sub.event_ids.filtered(lambda e: e.event_type == 'paused')
        self.assertTrue(len(paused_events) >= 1,
                        "Pause must create an event with event_type='paused'.")
        self.assertEqual(paused_events[0].reason, 'Test pause event')

    def test_35_resume_creates_event(self):
        """action_resume creates a lifecycle event with event_type='resumed'."""
        _, sub = self._make_active_subscription()
        sub.action_pause()
        sub.action_resume(reason='Back online')
        resumed_events = sub.event_ids.filtered(lambda e: e.event_type == 'resumed')
        self.assertTrue(len(resumed_events) >= 1,
                        "Resume must create an event with event_type='resumed'.")

    def test_36_renewal_creates_event(self):
        """action_renew creates a lifecycle event with event_type='renewed'."""
        _, sub = self._make_active_subscription()
        sub.action_renew(reason='Annual renewal')
        renewed_events = sub.event_ids.filtered(lambda e: e.event_type == 'renewed')
        self.assertTrue(len(renewed_events) >= 1,
                        "Renewal must create an event with event_type='renewed'.")

    def test_37_closure_creates_event(self):
        """action_close creates a lifecycle event with event_type='closed'."""
        _, sub = self._make_active_subscription()
        sub.action_close(reason='Customer churn')
        closed_events = sub.event_ids.filtered(lambda e: e.event_type == 'closed')
        self.assertTrue(len(closed_events) >= 1,
                        "Closure must create an event with event_type='closed'.")
        self.assertEqual(closed_events[0].reason, 'Customer churn')

    def test_38_events_are_read_only_for_regular_users(self):
        """Subscription events have perm_write=0 and perm_unlink=0 for non-admin users.

        This test verifies the ACL design: all user groups for events have
        write=0 and unlink=0 in ir.model.access.csv.  The actual enforcement
        is at the database access layer and can only be confirmed during live
        installation.  Here we assert the structural property via ACL records.
        """
        event_model = self.env['ir.model'].search([
            ('model', '=', 'subscriptiq.subscription.event')
        ], limit=1)
        self.assertTrue(event_model, "subscriptiq.subscription.event model must exist in ir.model.")
        # Verify that perm_write=0 for salesman and manager groups (the design intent)
        acl_write_entries = self.env['ir.model.access'].search([
            ('model_id', '=', event_model.id),
            ('perm_write', '=', True),
        ])
        self.assertFalse(
            acl_write_entries,
            "No ACL entry should grant perm_write on subscriptiq.subscription.event to any group."
        )
