# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError


class TestSubscriptionSecurityArchitecture(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Users = self.env['res.users']
        self.group_staff = self.env.ref('brightloop_base.group_subscriptiq_staff')
        self.group_admin = self.env.ref('brightloop_base.group_subscriptiq_admin')

        self.user_staff = self.Users.create({
            'name': 'Operations Staff',
            'login': 'staff_test@example.com',
            'email': 'staff_test@example.com',
            'groups_id': [(6, 0, [self.group_staff.id])],
            'password': 'StaffPassword#2026'
        })

    def test_01_password_policy_enforcement(self):
        """Weak password fails validation regex constraint."""
        with self.assertRaises(ValidationError):
            self.Users.create({
                'name': 'Weak Password User',
                'login': 'weak@example.com',
                'email': 'weak@example.com',
                'password': 'short'
            })

    def test_02_staff_privilege_escalation_blocked(self):
        """Staff user cannot elevate their own role to Admin."""
        with self.assertRaises(UserError):
            self.user_staff.with_user(self.user_staff).write({
                'groups_id': [(4, self.group_admin.id)]
            })

    def test_03_audit_log_immutability(self):
        """Audit logs cannot be modified or deleted."""
        audit_log = self.env['subscription.audit.log'].sudo().create({
            'user_id': self.env.user.id,
            'action': 'TEST_ACTION',
            'res_model': 'res.users',
            'res_id': self.user_staff.id,
        })
        with self.assertRaises(UserError):
            audit_log.write({'action': 'TAMPERED'})
        with self.assertRaises(UserError):
            audit_log.unlink()

    def test_04_finance_dashboard_kpis(self):
        """Finance dashboard returns KPI metric structure without crashing."""
        dashboard = self.env['subscription.finance.dashboard'].sudo()
        kpis = dashboard.get_financial_kpis()
        self.assertIsInstance(kpis, dict)
        self.assertIn('active_subscriptions', kpis)
        self.assertIn('total_subscriptions', kpis)
        self.assertIn('revenue_collected', kpis)
        self.assertIn('invoiced_amount', kpis)
