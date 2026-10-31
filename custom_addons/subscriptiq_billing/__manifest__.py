# -*- coding: utf-8 -*-
{
    'name': 'SubscriptIQ Billing & Finance Engine',
    'version': '19.0.1.0.0',
    'summary': 'Recurring Billing, Discount Allocation, Invoicing and Acknowledgement Recovery',
    'description': """
Brightloop Subscription Management System — Member 2 Addon
==========================================================
* 16-Stage recurring billing pipeline
* Six-state idempotent BillingLedger with PostgreSQL partial unique constraints
* Savepoint-isolated invoice creation and posting with external acknowledgement recovery
* Proportional fixed-discount allocation formula preserving unit prices
* Non-stacking discount rules and reservation lifecycle
* Native Odoo account.move integration (out_invoice and out_refund reversal)
* Three scheduled actions with mutually disjoint domain sets:
  - ir_cron_billing_engine (primary billing)
  - ir_cron_billing_retry (pre-posting invoice retry)
  - ir_cron_ack_retry (post-commit acknowledgement retry)
    """,
    'category': 'Accounting/Billing',
    'author': 'SubscriptIQ Team — Member 2',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'product',
        'mail',
        'base_setup',
        'brightloop_base',
    ],
    'data': [
        'security/subscriptiq_billing_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rule.xml',
        'data/ir_sequence_data.xml',
        'data/ir_cron_billing_engine.xml',
        'data/ir_cron_billing_retry.xml',
        'data/ir_cron_ack_retry.xml',
        'views/discount_rule_views.xml',
        'views/discount_reservation_views.xml',
        'views/billing_ledger_views.xml',
        'views/billing_run_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_actions.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
