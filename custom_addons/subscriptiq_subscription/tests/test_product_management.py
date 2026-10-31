# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'subscriptiq')
class TestProductManagement(TransactionCase):
    """Test suite for SubscriptIQ Phase 1: Product Management & Variants.

    Tests native product model extensions, variant creation, attribute pricing,
    and subscription eligibility logic in Odoo 19.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ProductTemplate = cls.env['product.template']
        cls.ProductProduct = cls.env['product.product']
        cls.ProductAttribute = cls.env['product.attribute']
        cls.ProductAttributeValue = cls.env['product.attribute.value']

        # Setup Demonstration Attribute: Brand
        cls.brand_attribute = cls.ProductAttribute.create({
            'name': 'Brand',
            'create_variant': 'always',
        })
        cls.val_standard = cls.ProductAttributeValue.create({
            'name': 'Standard',
            'attribute_id': cls.brand_attribute.id,
            'sequence': 1,
        })
        cls.val_odoo = cls.ProductAttributeValue.create({
            'name': 'Odoo',
            'attribute_id': cls.brand_attribute.id,
            'sequence': 2,
        })
        cls.val_premium = cls.ProductAttributeValue.create({
            'name': 'Premium',
            'attribute_id': cls.brand_attribute.id,
            'sequence': 3,
        })

    def test_01_product_creation(self):
        """1. Verify product creation on product.template and automatic default variant generation."""
        product_tmpl = self.ProductTemplate.create({
            'name': 'SubscriptIQ Cloud Analytics',
            'type': 'service',
            'list_price': 1500.0,
            'standard_price': 600.0,
            'is_subscription_eligible': True,
        })
        self.assertTrue(product_tmpl.id, "Product template should be successfully created with a database ID.")
        self.assertEqual(len(product_tmpl.product_variant_ids), 1, "Template without attributes should generate exactly one default variant.")
        self.assertEqual(product_tmpl.product_variant_ids[0].name, 'SubscriptIQ Cloud Analytics')

    def test_02_required_product_information(self):
        """2. Verify required product information, default field values, and model integrity."""
        product_tmpl = self.ProductTemplate.create({
            'name': 'SubscriptIQ Base Service',
            'type': 'service',
        })
        self.assertEqual(product_tmpl.name, 'SubscriptIQ Base Service')
        self.assertEqual(product_tmpl.type, 'service')
        self.assertTrue(product_tmpl.active, "New product should be active by default.")
        self.assertFalse(product_tmpl.is_subscription_eligible, "is_subscription_eligible should default to False.")

    def test_03_sales_price_and_cost_price(self):
        """3. Verify sales price (list_price) and cost price (standard_price) assignment and variant reflection."""
        product_tmpl = self.ProductTemplate.create({
            'name': 'SubscriptIQ Dedicated Hosting',
            'type': 'service',
            'list_price': 8500.0,
            'standard_price': 4200.0,
        })
        self.assertEqual(product_tmpl.list_price, 8500.0, "Template sales price should equal 8500.0.")
        self.assertEqual(product_tmpl.standard_price, 4200.0, "Template cost price should equal 4200.0.")

        variant = product_tmpl.product_variant_ids[0]
        self.assertEqual(variant.lst_price, 8500.0, "Variant lst_price should match template list_price.")
        self.assertEqual(variant.standard_price, 4200.0, "Variant standard_price should match template cost price.")

    def test_04_product_archiving(self):
        """4. Verify product archiving (active=False) and reactivation."""
        product_tmpl = self.ProductTemplate.create({
            'name': 'Deprecated Subscription Plan',
            'type': 'service',
            'active': True,
        })
        self.assertTrue(product_tmpl.active, "Product template should initially be active.")

        # Archive
        product_tmpl.write({'active': False})
        self.assertFalse(product_tmpl.active, "Product template should now be archived (active=False).")

        # Reactivate
        product_tmpl.write({'active': True})
        self.assertTrue(product_tmpl.active, "Product template should be successfully reactivated.")

    def test_05_product_attribute_creation(self):
        """5. Verify product attribute and attribute values creation."""
        self.assertTrue(self.brand_attribute.id, "Attribute should exist in database.")
        self.assertEqual(self.brand_attribute.name, 'Brand')
        self.assertEqual(len(self.brand_attribute.value_ids), 3, "Attribute should have 3 configured values.")
        value_names = self.brand_attribute.value_ids.mapped('name')
        self.assertIn('Standard', value_names)
        self.assertIn('Odoo', value_names)
        self.assertIn('Premium', value_names)

    def test_06_variant_generation(self):
        """6. Verify automatic product variant generation when attributes are configured on product template."""
        crm_template = self.ProductTemplate.create({
            'name': 'Brightloop CRM',
            'type': 'service',
            'list_price': 5000.0,
            'standard_price': 2000.0,
            'is_subscription_eligible': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.brand_attribute.id,
                    'value_ids': [(6, 0, [
                        self.val_standard.id,
                        self.val_odoo.id,
                        self.val_premium.id,
                    ])],
                }),
            ],
        })
        self.assertEqual(len(crm_template.product_variant_ids), 3, "Template should automatically generate 3 product.product variants.")

        generated_attribute_values = crm_template.product_variant_ids.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id.name'
        )
        self.assertIn('Standard', generated_attribute_values)
        self.assertIn('Odoo', generated_attribute_values)
        self.assertIn('Premium', generated_attribute_values)

    def test_07_variant_additional_pricing(self):
        """7. Verify native Odoo variant attribute price_extra calculation.

        Demonstration Product: Brightloop CRM
        Base Price: ₹5,000
        Attribute: Brand
        Values:
          - Standard: additional price ₹0   -> Final price: ₹5,000
          - Odoo:     additional price ₹560 -> Final price: ₹5,560
          - Premium:  additional price ₹1000-> Final price: ₹6,000
        """
        crm_template = self.ProductTemplate.create({
            'name': 'Brightloop CRM',
            'type': 'service',
            'list_price': 5000.0,
            'standard_price': 2000.0,
            'is_subscription_eligible': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.brand_attribute.id,
                    'value_ids': [(6, 0, [
                        self.val_standard.id,
                        self.val_odoo.id,
                        self.val_premium.id,
                    ])],
                }),
            ],
        })

        # Set price_extra on product.template.attribute.value
        ptavs = crm_template.attribute_line_ids.product_template_value_ids

        ptav_standard = ptavs.filtered(lambda p: p.product_attribute_value_id == self.val_standard)
        ptav_odoo = ptavs.filtered(lambda p: p.product_attribute_value_id == self.val_odoo)
        ptav_premium = ptavs.filtered(lambda p: p.product_attribute_value_id == self.val_premium)

        ptav_standard.write({'price_extra': 0.0})
        ptav_odoo.write({'price_extra': 560.0})
        ptav_premium.write({'price_extra': 1000.0})

        # Retrieve each variant and verify lst_price
        variant_std = crm_template.product_variant_ids.filtered(
            lambda v: self.val_standard in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        variant_odoo = crm_template.product_variant_ids.filtered(
            lambda v: self.val_odoo in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        variant_prem = crm_template.product_variant_ids.filtered(
            lambda v: self.val_premium in v.product_template_attribute_value_ids.product_attribute_value_id
        )

        self.assertEqual(len(variant_std), 1, "Should find exactly 1 Standard variant.")
        self.assertEqual(len(variant_odoo), 1, "Should find exactly 1 Odoo variant.")
        self.assertEqual(len(variant_prem), 1, "Should find exactly 1 Premium variant.")

        # Assert calculated variant prices
        self.assertEqual(variant_std.lst_price, 5000.0, "Standard variant price should be 5000 + 0 = 5000.")
        self.assertEqual(variant_odoo.lst_price, 5560.0, "Odoo variant price should be 5000 + 560 = 5560.")
        self.assertEqual(variant_prem.lst_price, 6000.0, "Premium variant price should be 5000 + 1000 = 6000.")

    def test_08_subscription_eligibility(self):
        """8. Verify subscription eligibility flag and domain filtering."""
        eligible_tmpl = self.ProductTemplate.create({
            'name': 'Subscription Eligible SaaS Product',
            'type': 'service',
            'is_subscription_eligible': True,
        })
        ineligible_tmpl = self.ProductTemplate.create({
            'name': 'One-off Consulting Retainer',
            'type': 'service',
            'is_subscription_eligible': False,
        })

        self.assertTrue(eligible_tmpl.is_subscription_eligible)
        self.assertFalse(ineligible_tmpl.is_subscription_eligible)

        # Verify search filter by subscription eligibility
        results = self.ProductTemplate.search([
            ('id', 'in', [eligible_tmpl.id, ineligible_tmpl.id]),
            ('is_subscription_eligible', '=', True),
        ])
        self.assertEqual(len(results), 1)
        self.assertIn(eligible_tmpl, results)
        self.assertNotIn(ineligible_tmpl, results)

        # Verify variant inherits is_subscription_eligible
        self.assertTrue(eligible_tmpl.product_variant_ids[0].is_subscription_eligible)
        self.assertFalse(ineligible_tmpl.product_variant_ids[0].is_subscription_eligible)
