# -*- coding: utf-8 -*-
"""Phase 3 — Quotation Management Tests.

Tests cover:
  1.  Quotation creation (sale.order with partner)
  2.  Customer assignment validation
  3.  Plan association (subscription_plan_id)
  4.  Plan products copied into quotation lines via action_populate_lines_from_plan
  5.  Quantity transfer from plan lines
  6.  Price snapshot transfer (plan line price_unit → order line price_unit)
  7.  Native tax_ids field preserved on order lines
  8.  Quotation validity date (native validity_date)
  9.  Inactive plan rejected on save (constrains)
  10. Populating from inactive plan raises UserError
  11. Populating from plan outside availability window raises UserError
  12. Quotation confirmation via native action_confirm()
  13. Quotation cancellation via native action_cancel()
  14. Quotation template creation (sale.order.template with subscription_plan_id)
  15. Template subscription_plan_id field stores and retrieves correctly
  16. Idempotent line population (calling action_populate_lines_from_plan twice
      does not create duplicate lines)
  17. Pricing integrity: mutating plan line price_unit after population does NOT
      alter existing order line price_unit (snapshot pattern)
"""
from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'subscriptiq')
class TestQuotationManagement(TransactionCase):
    """Integration tests for Phase 3: Quotation Management."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # --- Partner ---
        cls.partner = cls.env['res.partner'].create({
            'name': 'Brightloop Test Customer',
            'email': 'customer@brightloop.test',
        })

        # --- Subscription-eligible product template ---
        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'Test SaaS Service',
            'type': 'service',
            'is_subscription_eligible': True,
            'list_price': 1000.0,
        })
        cls.product_variant = cls.product_tmpl.product_variant_id

        # --- Second eligible product ---
        cls.product_tmpl2 = cls.env['product.template'].create({
            'name': 'Test SaaS Add-on',
            'type': 'service',
            'is_subscription_eligible': True,
            'list_price': 200.0,
        })
        cls.product_variant2 = cls.product_tmpl2.product_variant_id

        # --- Active subscription plan with two lines ---
        cls.plan = cls.env['subscriptiq.plan'].create({
            'name': 'Test Monthly Plan',
            'billing_frequency': 'monthly',
            'minimum_quantity': 1.0,
        })
        cls.plan_line1 = cls.env['subscriptiq.plan.line'].create({
            'plan_id': cls.plan.id,
            'product_id': cls.product_variant.id,
            'quantity': 3.0,
            'price_unit': 950.0,
        })
        cls.plan_line2 = cls.env['subscriptiq.plan.line'].create({
            'plan_id': cls.plan.id,
            'product_id': cls.product_variant2.id,
            'quantity': 1.0,
            'price_unit': 180.0,
        })

    # =========================================================================
    # Test 1 — Quotation creation
    # =========================================================================
    def test_01_quotation_creation(self):
        """A sale.order can be created and defaults to 'draft' state."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        self.assertTrue(order.id > 0, "sale.order should have a valid database id after creation.")
        self.assertEqual(order.state, 'draft', "New quotation should start in 'draft' state.")

    # =========================================================================
    # Test 2 — Customer assignment validation
    # =========================================================================
    def test_02_customer_assignment(self):
        """Quotation customer (partner_id) is stored and readable."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        self.assertEqual(
            order.partner_id, self.partner,
            "partner_id on sale.order should match the partner used at creation.",
        )

    # =========================================================================
    # Test 3 — Plan association
    # =========================================================================
    def test_03_plan_association(self):
        """subscription_plan_id field persists correctly on sale.order."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        self.assertEqual(
            order.subscription_plan_id, self.plan,
            "subscription_plan_id should reference the linked subscriptiq.plan.",
        )

    # =========================================================================
    # Test 4 — Plan products copied into order lines
    # =========================================================================
    def test_04_populate_lines_from_plan(self):
        """action_populate_lines_from_plan creates order lines for each plan line."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        populated_product_ids = order.order_line.mapped('product_id').ids
        self.assertIn(
            self.product_variant.id, populated_product_ids,
            "First plan product should appear in order lines after population.",
        )
        self.assertIn(
            self.product_variant2.id, populated_product_ids,
            "Second plan product should appear in order lines after population.",
        )
        self.assertEqual(
            len(order.order_line), 2,
            "Exactly two order lines should be created (one per plan line).",
        )

    # =========================================================================
    # Test 5 — Quantity transfer from plan lines
    # =========================================================================
    def test_05_quantity_transfer(self):
        """product_uom_qty on order lines matches the plan line quantities."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        line1 = order.order_line.filtered(
            lambda l: l.product_id == self.product_variant
        )
        line2 = order.order_line.filtered(
            lambda l: l.product_id == self.product_variant2
        )
        self.assertAlmostEqual(
            line1.product_uom_qty, 3.0,
            msg="Order line 1 quantity should match plan_line1.quantity (3.0).",
        )
        self.assertAlmostEqual(
            line2.product_uom_qty, 1.0,
            msg="Order line 2 quantity should match plan_line2.quantity (1.0).",
        )

    # =========================================================================
    # Test 6 — Price snapshot transfer
    # =========================================================================
    def test_06_price_snapshot_transfer(self):
        """price_unit on order lines matches plan line price_unit (snapshot)."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        line1 = order.order_line.filtered(
            lambda l: l.product_id == self.product_variant
        )
        self.assertAlmostEqual(
            line1.price_unit, 950.0,
            msg="Order line price_unit should reflect the plan line snapshot price (950.0).",
        )

    # =========================================================================
    # Test 7 — Native tax_ids field preserved on order lines
    # =========================================================================
    def test_07_tax_id_preserved(self):
        """tax_ids on order lines is set by native Odoo logic and taxes are preserved."""
        tax = self.env['account.tax'].search([
            ('company_id', '=', self.env.company.id),
            ('type_tax_use', '=', 'sale'),
        ], limit=1)
        if not tax:
            tax = self.env['account.tax'].create({
                'name': 'Test 10% Sale Tax',
                'amount_type': 'percent',
                'amount': 10.0,
                'type_tax_use': 'sale',
            })

        self.product_tmpl.taxes_id = [(6, 0, [tax.id])]

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        self.assertTrue(order.order_line, "Order lines must be created.")
        for line in order.order_line:
            self.assertTrue(
                hasattr(line, 'tax_ids'),
                "sale.order.line must carry the native Odoo 19 tax_ids field.",
            )

        target_line = order.order_line.filtered(lambda l: l.product_id == self.product_variant)
        self.assertTrue(target_line, "Order line for product variant must exist.")
        self.assertIn(
            tax.id, target_line.tax_ids.ids,
            "Product customer taxes must be preserved in order line tax_ids after plan population.",
        )

    # =========================================================================
    # Test 8 — Quotation validity date
    # =========================================================================
    def test_08_validity_date(self):
        """validity_date (native field) can be set on a subscription quotation."""
        future_date = date.today() + timedelta(days=30)
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
            'validity_date': future_date,
        })
        self.assertEqual(
            order.validity_date, future_date,
            "validity_date should be stored and returned correctly.",
        )

    # =========================================================================
    # Test 9 — Inactive plan rejected on constrains
    # =========================================================================
    def test_09_inactive_plan_rejected(self):
        """Saving a quotation linked to an archived plan raises ValidationError."""
        inactive_plan = self.env['subscriptiq.plan'].create({
            'name': 'Archived Plan',
            'billing_frequency': 'monthly',
            'active': False,
        })
        with self.assertRaises(ValidationError):
            self.env['sale.order'].create({
                'partner_id': self.partner.id,
                'subscription_plan_id': inactive_plan.id,
            })

    # =========================================================================
    # Test 10 — Populating from inactive plan raises UserError
    # =========================================================================
    def test_10_populate_from_inactive_plan_raises(self):
        """action_populate_lines_from_plan raises UserError if plan becomes inactive."""
        # Use SQL to bypass the constrains so we can test the method guard.
        plan = self.env['subscriptiq.plan'].create({
            'name': 'Soon Archived Plan',
            'billing_frequency': 'monthly',
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': plan.id,
        })
        # Archive via write (bypasses constrains on order since the field is
        # already set; the constraint only fires on the order, not on the plan).
        plan.write({'active': False})
        with self.assertRaises(UserError):
            order.action_populate_lines_from_plan()

    # =========================================================================
    # Test 11 — Populating outside availability window raises UserError
    # =========================================================================
    def test_11_populate_outside_availability_raises(self):
        """action_populate_lines_from_plan raises UserError if plan has expired."""
        expired_plan = self.env['subscriptiq.plan'].create({
            'name': 'Expired Plan',
            'billing_frequency': 'monthly',
            'available_from': date(2020, 1, 1),
            'available_until': date(2020, 12, 31),
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': expired_plan.id,
        })
        with self.assertRaises(UserError):
            order.action_populate_lines_from_plan()

    # =========================================================================
    # Test 12 — Quotation confirmation
    # =========================================================================
    def test_12_quotation_confirmation(self):
        """action_confirm() transitions a subscription quotation to 'sale' state."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        order.action_confirm()
        self.assertEqual(
            order.state, 'sale',
            "Confirming a subscription quotation should transition it to 'sale' state.",
        )

    # =========================================================================
    # Test 13 — Quotation cancellation
    # =========================================================================
    def test_13_quotation_cancellation(self):
        """action_cancel() transitions a draft subscription quotation to 'cancel'."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_cancel()
        self.assertEqual(
            order.state, 'cancel',
            "Cancelling a draft subscription quotation should set state to 'cancel'.",
        )

    # =========================================================================
    # Test 14 — Quotation template creation
    # =========================================================================
    def test_14_quotation_template_creation(self):
        """sale.order.template can be created with a subscription_plan_id."""
        template = self.env['sale.order.template'].create({
            'name': 'Monthly SaaS Template',
            'subscription_plan_id': self.plan.id,
        })
        self.assertTrue(
            template.id > 0,
            "sale.order.template should be created successfully with subscription_plan_id.",
        )

    # =========================================================================
    # Test 15 — Template subscription_plan_id field stores correctly
    # =========================================================================
    def test_15_template_plan_field(self):
        """subscription_plan_id on sale.order.template returns the linked plan."""
        template = self.env['sale.order.template'].create({
            'name': 'Yearly SaaS Template',
            'subscription_plan_id': self.plan.id,
        })
        self.assertEqual(
            template.subscription_plan_id, self.plan,
            "subscription_plan_id on sale.order.template should reference the linked plan.",
        )

    # =========================================================================
    # Test 16 — Idempotent line population
    # =========================================================================
    def test_16_idempotent_population(self):
        """Calling action_populate_lines_from_plan twice does not create duplicates."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()
        initial_line_count = len(order.order_line)

        order.action_populate_lines_from_plan()  # second call — must be idempotent
        self.assertEqual(
            len(order.order_line), initial_line_count,
            "Calling action_populate_lines_from_plan a second time must not add duplicate lines.",
        )

    # =========================================================================
    # Test 17 — Pricing integrity after plan modification
    # =========================================================================
    def test_17_pricing_integrity_after_plan_change(self):
        """Changing plan line price_unit after population does not alter order line price."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'subscription_plan_id': self.plan.id,
        })
        order.action_populate_lines_from_plan()

        order_line = order.order_line.filtered(
            lambda l: l.product_id == self.product_variant
        )
        original_price = order_line.price_unit  # should be 950.0

        # Mutate the plan line price after population
        self.plan_line1.write({'price_unit': 1500.0})

        order_line.invalidate_recordset(['price_unit'])
        self.assertAlmostEqual(
            order_line.price_unit, original_price,
            msg=(
                "Mutating plan line price_unit after line population must NOT "
                "retroactively change the order line price_unit (snapshot pattern)."
            ),
        )
