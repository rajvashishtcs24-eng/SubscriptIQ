# -*- coding: utf-8 -*-
from datetime import date
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'subscriptiq')
class TestSubscriptionPlanManagement(TransactionCase):
    """Test suite for SubscriptIQ Phase 2: Subscription Plan Management.

    Covers plan model definition, plan lines, pricing integrity, billing frequencies,
    minimum seat constraints, lifecycle policies, and validation rules.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Plan = cls.env['subscriptiq.plan']
        cls.PlanLine = cls.env['subscriptiq.plan.line']
        cls.ProductTemplate = cls.env['product.template']
        cls.ProductProduct = cls.env['product.product']
        cls.ProductAttribute = cls.env['product.attribute']
        cls.ProductAttributeValue = cls.env['product.attribute.value']

        # Setup Eligible Subscription Product
        cls.subscription_product_tmpl = cls.ProductTemplate.create({
            'name': 'Cloud SaaS Core',
            'type': 'service',
            'list_price': 1200.0,
            'is_subscription_eligible': True,
        })
        cls.subscription_product = cls.subscription_product_tmpl.product_variant_ids[0]

        # Setup Ineligible Product
        cls.ineligible_product_tmpl = cls.ProductTemplate.create({
            'name': 'Hardware Dongle',
            'type': 'consu',
            'list_price': 500.0,
            'is_subscription_eligible': False,
        })
        cls.ineligible_product = cls.ineligible_product_tmpl.product_variant_ids[0]

        # Setup Product with Brand Variants and Surcharges (Brightloop CRM Demonstration)
        cls.brand_attr = cls.ProductAttribute.create({
            'name': 'Plan Brand Attribute',
            'create_variant': 'always',
        })
        cls.val_std = cls.ProductAttributeValue.create({
            'name': 'Standard Tier',
            'attribute_id': cls.brand_attr.id,
        })
        cls.val_odoo = cls.ProductAttributeValue.create({
            'name': 'Odoo Tier',
            'attribute_id': cls.brand_attr.id,
        })

        cls.crm_tmpl = cls.ProductTemplate.create({
            'name': 'Brightloop CRM Multi-Tier',
            'type': 'service',
            'list_price': 5000.0,
            'is_subscription_eligible': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': cls.brand_attr.id,
                    'value_ids': [(6, 0, [cls.val_std.id, cls.val_odoo.id])],
                }),
            ],
        })

        # Set price_extra for Odoo Tier (+₹560)
        ptav_odoo = cls.crm_tmpl.attribute_line_ids.product_template_value_ids.filtered(
            lambda p: p.product_attribute_value_id == cls.val_odoo
        )
        ptav_odoo.write({'price_extra': 560.0})

        cls.variant_std = cls.crm_tmpl.product_variant_ids.filtered(
            lambda v: cls.val_std in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        cls.variant_odoo = cls.crm_tmpl.product_variant_ids.filtered(
            lambda v: cls.val_odoo in v.product_template_attribute_value_ids.product_attribute_value_id
        )

    def test_01_plan_creation(self):
        """1. Verify subscription plan creation with standard identification and defaults."""
        plan = self.Plan.create({
            'name': 'Standard Growth Plan',
            'description': 'Designed for scaling tech startups.',
            'billing_frequency': 'monthly',
            'minimum_quantity': 2.0,
        })
        self.assertTrue(plan.id, "Plan should be successfully created with a database ID.")
        self.assertEqual(plan.name, 'Standard Growth Plan')
        self.assertTrue(plan.active)
        self.assertEqual(plan.minimum_quantity, 2.0)
        self.assertEqual(plan.price, 0.0, "Plan price without lines should be 0.")

    def test_02_plan_line_creation(self):
        """2. Verify plan line creation and association with plan."""
        plan = self.Plan.create({
            'name': 'Modular Service Plan',
            'billing_frequency': 'monthly',
        })
        line = self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.subscription_product.id,
            'quantity': 3.0,
            'price_unit': 1200.0,
        })
        self.assertTrue(line.id)
        self.assertEqual(len(plan.line_ids), 1)
        self.assertEqual(line.price_subtotal, 3600.0)
        self.assertEqual(plan.price, 3600.0)

    def test_03_product_eligibility_validation(self):
        """3. Verify backend constraint preventing ineligible products from being added to plans."""
        plan = self.Plan.create({
            'name': 'Strict Eligibility Plan',
            'billing_frequency': 'monthly',
        })
        with self.assertRaises(ValidationError, msg="Adding an ineligible product must raise a ValidationError."):
            self.PlanLine.create({
                'plan_id': plan.id,
                'product_id': self.ineligible_product.id,
                'quantity': 1.0,
                'price_unit': 500.0,
            })

    def test_04_minimum_quantity_validation(self):
        """4. Verify minimum_quantity must be strictly greater than zero."""
        with self.assertRaises(ValidationError, msg="minimum_quantity of 0 must raise ValidationError."):
            self.Plan.create({
                'name': 'Zero Seat Plan',
                'minimum_quantity': 0.0,
            })

        with self.assertRaises(ValidationError, msg="Negative minimum_quantity must raise ValidationError."):
            self.Plan.create({
                'name': 'Negative Seat Plan',
                'minimum_quantity': -1.0,
            })

    def test_05_negative_pricing_validation(self):
        """5. Verify unit price on plan lines cannot be negative."""
        plan = self.Plan.create({
            'name': 'Price Guard Plan',
            'billing_frequency': 'monthly',
        })
        with self.assertRaises(ValidationError, msg="Negative price_unit must raise ValidationError."):
            self.PlanLine.create({
                'plan_id': plan.id,
                'product_id': self.subscription_product.id,
                'quantity': 1.0,
                'price_unit': -50.0,
            })

    def test_06_plan_total_calculation(self):
        """6. Verify dynamic plan total computation from multiple line subtotals."""
        # Create second eligible product
        sec_tmpl = self.ProductTemplate.create({
            'name': 'Analytics Addon',
            'type': 'service',
            'list_price': 300.0,
            'is_subscription_eligible': True,
        })
        sec_prod = sec_tmpl.product_variant_ids[0]

        plan = self.Plan.create({
            'name': 'Bundle Plan',
            'billing_frequency': 'monthly',
        })
        self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.subscription_product.id,
            'quantity': 2.0,
            'price_unit': 1000.0,  # 2 x 1000 = 2000
        })
        self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': sec_prod.id,
            'quantity': 3.0,
            'price_unit': 250.0,   # 3 x 250 = 750
        })
        self.assertEqual(plan.price, 2750.0, "Total plan price should equal sum of line subtotals (2000 + 750 = 2750).")

    def test_07_currency_handling(self):
        """7. Verify currency propagation and rounding on plan and lines."""
        company_currency = self.env.company.currency_id
        plan = self.Plan.create({
            'name': 'Currency Test Plan',
            'billing_frequency': 'monthly',
        })
        self.assertEqual(plan.currency_id, company_currency)

        line = self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.subscription_product.id,
            'quantity': 1.0,
            'price_unit': 1234.56,
        })
        self.assertEqual(line.currency_id, company_currency)
        self.assertEqual(line.price_subtotal, 1234.56)

    def test_08_daily_billing_frequency(self):
        """8. Verify daily billing frequency configuration."""
        plan = self.Plan.create({
            'name': 'Daily Cloud Resource Plan',
            'billing_frequency': 'daily',
        })
        self.assertEqual(plan.billing_frequency, 'daily')

    def test_09_weekly_billing_frequency(self):
        """9. Verify weekly billing frequency configuration."""
        plan = self.Plan.create({
            'name': 'Weekly Agile Coaching Plan',
            'billing_frequency': 'weekly',
        })
        self.assertEqual(plan.billing_frequency, 'weekly')

    def test_10_monthly_billing_frequency(self):
        """10. Verify monthly billing frequency configuration."""
        plan = self.Plan.create({
            'name': 'Monthly SaaS Subscription',
            'billing_frequency': 'monthly',
        })
        self.assertEqual(plan.billing_frequency, 'monthly')

    def test_11_yearly_billing_frequency(self):
        """11. Verify yearly billing frequency configuration."""
        plan = self.Plan.create({
            'name': 'Yearly Enterprise Agreement',
            'billing_frequency': 'yearly',
        })
        self.assertEqual(plan.billing_frequency, 'yearly')

    def test_12_invalid_date_range(self):
        """12. Verify validation error when available_until precedes available_from."""
        with self.assertRaises(ValidationError, msg="available_until < available_from must raise ValidationError."):
            self.Plan.create({
                'name': 'Invalid Time Plan',
                'available_from': date(2026, 12, 1),
                'available_until': date(2026, 11, 1),
            })

    def test_13_renewal_configuration(self):
        """13. Verify manual renewal and renewal disabled configurations."""
        plan_enabled = self.Plan.create({
            'name': 'Manual Renewal Plan',
            'renewal_enabled': True,
            'renewal_type': 'manual',
        })
        self.assertTrue(plan_enabled.renewal_enabled)
        self.assertEqual(plan_enabled.renewal_type, 'manual')

        plan_disabled = self.Plan.create({
            'name': 'No Renewal Plan',
            'renewal_enabled': False,
            'renewal_type': 'manual',
        })
        self.assertFalse(plan_disabled.renewal_enabled)

    def test_14_automatic_renewal_configuration(self):
        """14. Verify automatic renewal constraint: cannot have automatic renewal if renewal_enabled=False."""
        plan_auto = self.Plan.create({
            'name': 'Auto Renewal Plan',
            'renewal_enabled': True,
            'renewal_type': 'automatic',
        })
        self.assertEqual(plan_auto.renewal_type, 'automatic')

        with self.assertRaises(ValidationError, msg="automatic renewal with renewal_enabled=False must raise ValidationError."):
            self.Plan.create({
                'name': 'Invalid Auto Renewal Plan',
                'renewal_enabled': False,
                'renewal_type': 'automatic',
            })

    def test_15_early_close_policy(self):
        """15. Verify independent early-close policy configuration."""
        plan_allow = self.Plan.create({
            'name': 'Flexible Commitment Plan',
            'allow_early_close': True,
        })
        self.assertTrue(plan_allow.allow_early_close)

        plan_strict = self.Plan.create({
            'name': 'Locked Commitment Plan',
            'allow_early_close': False,
        })
        self.assertFalse(plan_strict.allow_early_close)

    def test_16_pause_policy(self):
        """16. Verify independent pause policy configuration."""
        plan_pausable = self.Plan.create({
            'name': 'Seasonal Pause Plan',
            'allow_pause': True,
        })
        self.assertTrue(plan_pausable.allow_pause)

        plan_no_pause = self.Plan.create({
            'name': 'Non-pausable Plan',
            'allow_pause': False,
        })
        self.assertFalse(plan_no_pause.allow_pause)

    def test_17_product_variant_pricing_inheritance(self):
        """17. Verify plan line price_unit defaults to variant selling price (including price_extra)."""
        # Standard variant: base list_price = 5000.0, price_extra = 0.0 -> lst_price = 5000.0
        # Odoo variant: base list_price = 5000.0, price_extra = 560.0 -> lst_price = 5560.0
        self.assertEqual(self.variant_std.lst_price, 5000.0)
        self.assertEqual(self.variant_odoo.lst_price, 5560.0)

        plan = self.Plan.create({'name': 'Variant Pricing Plan'})

        line_std = self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.variant_std.id,
            'quantity': 1.0,
        })
        self.assertEqual(line_std.price_unit, 5000.0, "Standard variant unit price should default to 5000.0.")

        line_odoo = self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.variant_odoo.id,
            'quantity': 1.0,
        })
        self.assertEqual(line_odoo.price_unit, 5560.0, "Odoo variant unit price should inherit attribute surcharge 5560.0.")

    def test_18_plan_pricing_independence_from_product_price_changes(self):
        """18. Verify pricing integrity: changing underlying product template price does NOT alter agreed plan line price."""
        plan = self.Plan.create({'name': 'Price Lock Agreement Plan'})
        line = self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.subscription_product.id,
            'quantity': 2.0,
            'price_unit': 1200.0,  # Snapshot set on plan line
        })
        self.assertEqual(line.price_subtotal, 2400.0)
        self.assertEqual(plan.price, 2400.0)

        # External event: Product catalog manager increases base product price to ₹2,500.0
        self.subscription_product_tmpl.write({'list_price': 2500.0})
        self.assertEqual(self.subscription_product.lst_price, 2500.0)

        # Plan line price MUST remain completely untouched and independent
        line.invalidate_recordset()
        plan.invalidate_recordset()
        self.assertEqual(line.price_unit, 1200.0, "Plan line unit price must remain unchanged after product price modification.")
        self.assertEqual(line.price_subtotal, 2400.0, "Plan line subtotal must remain unchanged.")
        self.assertEqual(plan.price, 2400.0, "Plan total price must remain stable.")

    def test_19_duplicate_product_constraint(self):
        """19. Verify constraint preventing duplicate product variants on the same plan."""
        plan = self.Plan.create({'name': 'No Duplicate Variants Plan'})
        self.PlanLine.create({
            'plan_id': plan.id,
            'product_id': self.subscription_product.id,
            'quantity': 1.0,
            'price_unit': 1200.0,
        })

        with self.assertRaises(ValidationError, msg="Duplicate product variant on same plan must raise ValidationError."):
            self.PlanLine.create({
                'plan_id': plan.id,
                'product_id': self.subscription_product.id,
                'quantity': 2.0,
                'price_unit': 1000.0,
            })
