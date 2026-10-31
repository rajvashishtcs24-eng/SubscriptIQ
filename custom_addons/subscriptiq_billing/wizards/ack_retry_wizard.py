# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, _
from ..services.acknowledgement_service import AcknowledgementService


class AckRetryWizard(models.TransientModel):
    """
    Wizard for manual acknowledgement recovery on stuck or failed ack ledgers.
    """
    _name = 'subscriptiq.ack.retry.wizard'
    _description = 'Manual Acknowledgement Retry Wizard'

    ledger_ids = fields.Many2many(
        comodel_name='subscriptiq.billing.ledger',
        string='Target Ledgers',
        domain="[('state', 'in', ('ack_pending', 'ack_failed'))]",
    )

    def action_retry(self):
        self.ensure_one()
        selected_ids = self.ledger_ids.ids if self.ledger_ids else None
        success_count = AcknowledgementService.retry_acknowledgement(self.env, ledger_ids=selected_ids)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Acknowledgement Retry Completed'),
                'message': _('Successfully acknowledged %d subscription ledgers.') % success_count,
                'type': 'success',
                'sticky': False,
            }
        }
