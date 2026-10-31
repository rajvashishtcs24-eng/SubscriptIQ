# -*- coding: utf-8 -*-
{
    'name': 'SubscriptIQ Portal & Experience',
    'version': '19.0.1.0.0',
    'summary': 'Customer portal, security constraints, staff operations, and analytics engine.',
    'category': 'Sales/Subscription',
    'author': 'Brightloop Team Member 3',
    'depends': [
        'base',
        'portal',
        'mail',
        'account',
        'brightloop_base',
        'subscriptiq_subscription',
        'subscriptiq_billing',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security_rules.xml',
        'views/staff_management_views.xml',
        'views/audit_log_views.xml',
        'views/portal_templates.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'subscriptiq_portal/static/src/components/finance_dashboard/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
