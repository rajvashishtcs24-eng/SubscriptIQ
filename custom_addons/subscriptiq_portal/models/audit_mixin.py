from odoo import models

class SubscriptionAuditMixin(models.AbstractModel):
    _name = 'subscription.audit.mixin'
    _description = 'Subscription Domain Audit Interceptor'

    def write(self, vals):
        before_state = {rec.id: {field: rec[field] for field in vals.keys() if field in rec} for rec in self}
        res = super(SubscriptionAuditMixin, self).write(vals)
        for rec in self:
            delta = {
                field: {'old': before_state[rec.id].get(field), 'new': vals[field]}
                for field in vals.keys() if before_state[rec.id].get(field) != vals[field]
            }
            if delta:
                self.env['subscription.audit.log'].log_event(
                    action=f"{self._name}.updated",
                    target_record=rec,
                    metadata={'delta': delta}
                )
        return res

    def unlink(self):
        for rec in self:
            self.env['subscription.audit.log'].log_event(
                action=f"{self._name}.deleted",
                target_record=rec,
                metadata={'deleted_record_name': rec.display_name}
            )
        return super(SubscriptionAuditMixin, self).unlink()