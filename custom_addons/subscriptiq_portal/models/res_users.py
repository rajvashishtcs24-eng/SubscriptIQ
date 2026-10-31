import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

PASSWORD_REGEX = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&#^_\-+=<>~`|{}[\]:;,.])[A-Za-z\d@$!%*?&#^_\-+=<>~`|{}[\]:;,.]{9,}$'
)

class ResUsers(models.Model):
    _inherit = 'res.users'

    is_subscription_staff = fields.Boolean(
        string="Is Subscription Staff",
        compute="_compute_subscription_role",
        store=True,
        index=True
    )
    is_subscription_admin = fields.Boolean(
        string="Is Subscription Admin",
        compute="_compute_subscription_role",
        store=True,
        index=True
    )

    @api.depends('groups_id')
    def _compute_subscription_role(self):
        admin_group = self.env.ref('brightloop_base.group_subscriptiq_admin', raise_if_not_found=False)
        staff_group = self.env.ref('brightloop_base.group_subscriptiq_staff', raise_if_not_found=False)
        for user in self:
            user.is_subscription_admin = admin_group in user.groups_id if admin_group else False
            user.is_subscription_staff = staff_group in user.groups_id if staff_group else False

    @api.constrains('password')
    def _check_password_strength(self):
        for user in self:
            if not user.password:
                continue
            if not PASSWORD_REGEX.match(user.password):
                raise ValidationError(_(
                    "Password does not satisfy system security policies:\n"
                    "- Minimum 9 characters in length\n"
                    "- At least one uppercase letter (A-Z)\n"
                    "- At least one lowercase letter (a-z)\n"
                    "- At least one digit (0-9)\n"
                    "- At least one special character (!@#$%^&*()-_+=<>?)"
                ))

    @api.constrains('login', 'email')
    def _check_unique_email(self):
        for user in self:
            domain = [('id', '!=', user.id), '|', ('login', '=ilike', user.login), ('email', '=ilike', user.email)]
            if self.search_count(domain) > 0:
                raise ValidationError(_("An account with the email/login '%s' is already registered.") % user.email)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'email' in vals and not vals.get('login'):
                vals['login'] = vals['email'].strip().lower()
            elif 'login' in vals:
                vals['login'] = vals['login'].strip().lower()
            self._validate_staff_provisioning(vals)

        users = super(ResUsers, self).create(vals_list)

        # Trigger Audit Event
        audit_model = self.env.get('subscription.audit.log')
        if audit_model is not None:
            for user in users:
                audit_model.log_event(
                    action='USER_CREATED',
                    target_record=user,
                    metadata={'name': user.name, 'login': user.login}
                )
        return users

    def write(self, vals):
        self._validate_staff_provisioning(vals)
        tracked_keys = [k for k in vals.keys() if k not in ('write_date', '__last_update')]
        res = super(ResUsers, self).write(vals)

        # Trigger Audit Event
        audit_model = self.env.get('subscription.audit.log')
        if audit_model is not None and tracked_keys:
            for user in self:
                audit_model.log_event(
                    action='USER_MODIFIED',
                    target_record=user,
                    metadata={'modified_fields': tracked_keys}
                )
        return res

    def _validate_staff_provisioning(self, vals):
        if self.env.is_superuser():
            return

        admin_group = self.env.ref('brightloop_base.group_subscriptiq_admin', raise_if_not_found=False)
        staff_group = self.env.ref('brightloop_base.group_subscriptiq_staff', raise_if_not_found=False)
        monitored_groups = {g.id for g in [admin_group, staff_group] if g}

        if not monitored_groups or 'groups_id' not in vals:
            return

        assigned_groups = set()
        for item in vals['groups_id']:
            cmd = item[0]
            if cmd == 4:
                assigned_groups.add(item[1])
            elif cmd == 6:
                assigned_groups.update(item[2])
            elif cmd in (3, 5):
                removed_id = item[1] if cmd == 3 else None
                if removed_id and removed_id in monitored_groups:
                    if not self.env.user.has_group('brightloop_base.group_subscriptiq_admin'):
                        raise UserError(_("Only Subscription Administrators can alter staff permissions."))

        if assigned_groups.intersection(monitored_groups):
            if not self.env.user.has_group('brightloop_base.group_subscriptiq_admin'):
                raise UserError(_("Access Denied: You do not have permission to provision Staff or Admin roles."))