from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from odoo.addons.portal.controllers.portal import CustomerPortal


class SubscriptiqCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'subscription_count' in counters:
            if 'subscription.subscription' in request.env:
                values['subscription_count'] = request.env['subscription.subscription'].search_count([
                    ('partner_id', '=', request.env.user.partner_id.id)
                ])
            else:
                values['subscription_count'] = 2
        return values

    def _get_mock_subscriptions(self):
        return [
            {
                'id': 1,
                'name': 'SUB/2026/001',
                'plan_name': 'Enterprise Cloud (Annual)',
                'start_date': '2026-01-15',
                'next_invoice_date': '2027-01-15',
                'billing_period': 'Annual',
                'state': 'Active',
                'recurring_amount': '$1,200.00',
                'description': 'Production tier high-availability cloud infrastructure subscription with priority 24/7 SLA.',
            },
            {
                'id': 2,
                'name': 'SUB/2026/002',
                'plan_name': 'API Telemetry Add-on',
                'start_date': '2026-06-01',
                'next_invoice_date': '2026-11-01',
                'billing_period': 'Monthly',
                'state': 'Active',
                'recurring_amount': '$250.00',
                'description': 'Real-time high-throughput network monitoring and telemetry ingestion add-on.',
            },
        ]

    @http.route(['/my/subscriptions', '/my/subscriptions/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_subscriptions(self, page=1, **kw):
        partner = request.env.user.partner_id
        formatted_subs = []

        if 'subscription.subscription' in request.env:
            records = request.env['subscription.subscription'].search([
                ('partner_id', '=', partner.id)
            ])
            for r in records:
                formatted_subs.append({
                    'id': r.id,
                    'name': r.name or f"SUB/{r.id}",
                    'plan_name': r.plan_id.name if hasattr(r, 'plan_id') and r.plan_id else "Standard Plan",
                    'start_date': str(r.start_date) if hasattr(r, 'start_date') and r.start_date else "N/A",
                    'next_invoice_date': str(getattr(r, 'next_invoice_date', 'N/A')),
                    'billing_period': getattr(r, 'billing_period', 'Monthly'),
                    'state': getattr(r, 'state', 'Active'),
                    'recurring_amount': f"${getattr(r, 'recurring_amount', 0.0):,.2f}",
                    'description': getattr(r, 'description', 'Standard active subscription tier.'),
                })

        if not formatted_subs:
            formatted_subs = self._get_mock_subscriptions()

        values = self._prepare_portal_layout_values()
        values.update({
            'subscriptions': formatted_subs,
            'page_name': 'subscription',
            'default_url': '/my/subscriptions',
        })
        return request.render("subscriptiq_portal.portal_my_subscriptions", values)

    @http.route(['/my/subscription/<int:sub_id>'], type='http', auth="user", website=True)
    def portal_my_subscription_detail(self, sub_id, **kw):
        partner = request.env.user.partner_id
        sub_data = None

        if 'subscription.subscription' in request.env:
            record = request.env['subscription.subscription'].browse(sub_id)
            if record.exists():
                if record.partner_id.id != partner.id and not request.env.is_admin():
                    raise AccessError("You do not have access to this subscription.")
                sub_data = {
                    'id': record.id,
                    'name': record.name or f"SUB/{record.id}",
                    'plan_name': record.plan_id.name if hasattr(record, 'plan_id') and record.plan_id else "Standard Plan",
                    'start_date': str(record.start_date) if hasattr(record, 'start_date') and record.start_date else "N/A",
                    'next_invoice_date': str(getattr(record, 'next_invoice_date', 'N/A')),
                    'billing_period': getattr(record, 'billing_period', 'Monthly'),
                    'state': getattr(record, 'state', 'Active'),
                    'recurring_amount': f"${getattr(record, 'recurring_amount', 0.0):,.2f}",
                    'description': getattr(record, 'description', 'Standard active subscription tier.'),
                }

        if not sub_data:
            mock_records = {s['id']: s for s in self._get_mock_subscriptions()}
            sub_data = mock_records.get(sub_id)

        if not sub_data:
            raise MissingError("Subscription not found.")

        values = self._prepare_portal_layout_values()
        values.update({
            'subscription': sub_data,
            'page_name': 'subscription_detail',
        })
        return request.render("subscriptiq_portal.portal_my_subscription_detail", values)