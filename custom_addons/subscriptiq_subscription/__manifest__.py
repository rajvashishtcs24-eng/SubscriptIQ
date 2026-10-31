# -*- coding: utf-8 -*-
{
    'name': 'SubscriptIQ Subscription',
    'version': '19.0.4.0.0',
    'category': 'Sales/Subscription',
    'summary': 'Advanced Subscription Management - Full Lifecycle Engine',
    'description': """
SubscriptIQ Subscription Management System
==========================================
Member 1 Domain: Product → Plan → Quotation → Subscription Lifecycle.

Phase 1 — Product Management:
    * product.template / product.product extended with is_subscription_eligible.
    * Variant pricing via product attributes and price_extra.

Phase 2 — Subscription Plan Management:
    * subscriptiq.plan with billing frequency, availability, and renewal policies.
    * subscriptiq.plan.line with pricing snapshot integrity.

Phase 3 — Quotation Management:
    * sale.order extended with subscription_plan_id, is_subscription_quotation.
    * action_populate_lines_from_plan (idempotent).
    * sale.order.template extended with subscription_plan_id.

Phase 4 — Subscription Management Engine:
    * subscriptiq.subscription — main subscription record with full lifecycle.
    * subscriptiq.subscription.line — pricing-snapshot line items.
    * subscriptiq.subscription.event — immutable lifecycle event history.
    * Lifecycle methods: activate, pause, resume, renew, close.
    * Quotation-to-subscription conversion via action_prepare_subscription.
    * sale.order.action_confirm override transitions subscription to confirmed.
    * sale.order.action_cancel closes quotation-state subscriptions.
    * Member 2 billing interface: get_due_billing_data / action_register_billing_success.
    * ir.sequence for SUB/YYYY/NNNNN subscription numbers.
    * ir.cron scheduler for automatic expiry (auto_close=True).
    * Odoo 19 compliant views: <list>, list,form modes, bare <group> in search.
    """,
    'author': 'Brightloop Software / Member 1',
    'website': 'https://github.com/rajvashishtcs24-eng/SubscriptIQ',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'sale_management',
        'sales_team',
        'mail',
    ],
    'data': [
        'data/subscription_data.xml',
        'security/ir.model.access.csv',
        'views/subscription_plan_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/subscription_views.xml',
        'views/product_menus.xml',
    ],
    'demo': [
        'demo/product_demo.xml',
        'demo/subscription_plan_demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
