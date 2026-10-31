from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError

class TestSubscriptionSecurityArchitecture(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Users = self.env['res.users']
        self.group_staff = self.env.ref('subscription_platform.group_subscription_staff')
        self.group_admin = self.env.ref('subscription_platform.group_subscription_admin')

        self.user_staff = self.Users.create({
            'name': 'Operations Staff',
            'login': 'staff_test@example.com',
            'email': 'staff_test@example.com',
            'groups_id': [(6, 0, [self.group_staff.id])],
            'password': 'StaffPassword#2026'
        })

    def test_01_password_policy_enforcement(self):
        with self.assertRaises(ValidationError):
            self.Users.create({
                'name': 'Weak Password User',
                'login': 'weak@example.com',
                'email': 'weak@example.com',
                'password': 'short'
            })

    def test_02_staff_privilege_escalation_blocked(self):
        with self.assertRaises(UserError):
            self.user_staff.with_user(self.user_staff).write({
                'groups_id': [(4, self.group_admin.id)]
            })