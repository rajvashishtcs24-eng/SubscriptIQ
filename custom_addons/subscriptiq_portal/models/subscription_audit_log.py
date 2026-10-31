import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SubscriptionAuditLog(models.Model):
    _name = 'subscription.audit.log'
    _description = 'Subscription Business Audit Log'
    _order = 'create_date desc'
    _rec_name = 'action'

    user_id = fields.Many2one('res.users', string="Actor", required=True, readonly=True, index=True)
    action = fields.Char(string="Business Action", required=True, readonly=True, index=True)
    res_model = fields.Char(string="Target Model", required=True, readonly=True, index=True)
    res_id = fields.Integer(string="Record ID", required=True, readonly=True, index=True)
    record_name = fields.Char(string="Record Reference", readonly=True)
    metadata_json = fields.Text(string="Contextual Delta / Payload", readonly=True)
    create_date = fields.Datetime(string="Timestamp", readonly=True, index=True)

    def write(self, vals):
        raise UserError(_("Security Violation: Audit logs are immutable and cannot be modified."))

    def unlink(self):
        raise UserError(_("Security Violation: Audit logs cannot be deleted."))

    @api.model
    def log_event(self, action, target_record, metadata=None):
        return self.sudo().create({
            'user_id': self.env.user.id,
            'action': action,
            'res_model': target_record._name,
            'res_id': target_record.id,
            'record_name': target_record.display_name,
            'metadata_json': json.dumps(metadata or {}, default=str),
        })