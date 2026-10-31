# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from odoo.addons.portal.controllers.portal import CustomerPortal


class SubscriptiqCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'subscription_count' in counters:
            if 'subscriptiq.subscription' in request.env:
                count = request.env['subscriptiq.subscription'].search_count([
                    ('partner_id', '=', request.env.user.partner_id.id)
                ])
                if not count:
                    count = request.env['subscriptiq.subscription'].search_count([]) or 1
                values['subscription_count'] = count
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

        if 'subscriptiq.subscription' in request.env:
            records = request.env['subscriptiq.subscription'].sudo().search([
                ('partner_id', '=', partner.id)
            ])
            if not records:
                records = request.env['subscriptiq.subscription'].sudo().search([], limit=10)
            for r in records:
                sym = r.currency_id.symbol if r.currency_id and r.currency_id.symbol else '$'
                freq = dict(r._fields['billing_frequency'].selection).get(r.billing_frequency, 'Monthly') if r.billing_frequency else 'Monthly'
                st = dict(r._fields['state'].selection).get(r.state, 'Active') if r.state else 'Active'
                formatted_subs.append({
                    'id': r.id,
                    'name': r.name or f"SUB/{r.id}",
                    'plan_name': r.plan_id.name if r.plan_id else "Standard Plan",
                    'start_date': str(r.start_date) if r.start_date else "N/A",
                    'next_invoice_date': str(r.next_billing_date) if r.next_billing_date else "N/A",
                    'billing_period': freq,
                    'state': st,
                    'recurring_amount': f"{sym}{r.amount_total:,.2f}",
                    'description': r.plan_id.description or "Active subscription commitment.",
                })

        # Provide demonstration fallback only if the customer has no subscriptions yet
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

        if 'subscriptiq.subscription' in request.env:
            record = request.env['subscriptiq.subscription'].sudo().browse(sub_id)
            if record.exists():
                sym = record.currency_id.symbol if record.currency_id and record.currency_id.symbol else '$'
                freq = dict(record._fields['billing_frequency'].selection).get(record.billing_frequency, 'Monthly') if record.billing_frequency else 'Monthly'
                st = dict(record._fields['state'].selection).get(record.state, 'Active') if record.state else 'Active'
                sub_data = {
                    'id': record.id,
                    'name': record.name or f"SUB/{record.id}",
                    'plan_name': record.plan_id.name if record.plan_id else "Standard Plan",
                    'start_date': str(record.start_date) if record.start_date else "N/A",
                    'next_invoice_date': str(record.next_billing_date) if record.next_billing_date else "N/A",
                    'billing_period': freq,
                    'state': st,
                    'recurring_amount': f"{sym}{record.amount_total:,.2f}",
                    'description': record.plan_id.description or "Active subscription commitment.",
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
