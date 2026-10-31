# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, _
from odoo.exceptions import UserError
from ..services.billing_engine import BillingEngine


class BillingRunManualWizard(models.TransientModel):
    """
    Allows billing managers to manually trigger a billing run for a target date
    or a specific subset of subscriptions.
    """
    _name = 'subscriptiq.billing.run.manual.wizard'
    _description = 'Manual Billing Run Wizard'

    billing_date = fields.Date(
        string='Target Billing Date',
        required=True,
        default=fields.Date.context_today,
    )
    subscription_ids = fields.Char(
        string='Subscription IDs (Optional Filter)',
        help="Comma-separated IDs. Leave empty to evaluate all due subscriptions.",
    )

    def action_execute(self):
        self.ensure_one()
        sub_ids = None
        if self.subscription_ids:
            try:
                sub_ids = [int(s.strip()) for s in self.subscription_ids.split(',') if s.strip().isdigit()]
            except Exception:
                raise UserError(_("Invalid subscription ID format. Please use comma-separated integers."))

        run = BillingEngine.execute_run(
            self.env,
            billing_date=self.billing_date,
            triggered_by='manual',
            user_id=self.env.user.id,
            subscription_ids=sub_ids,
        )

        if not run:
            raise UserError(_("Billing run could not be started. A concurrent run may be in progress."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Billing Run Result'),
            'res_model': 'subscriptiq.billing.run',
            'res_id': run.id,
            'view_mode': 'form',
            'target': 'current',
        }
