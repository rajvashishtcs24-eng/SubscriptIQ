from odoo import models, api, fields
from datetime import timedelta

class SubscriptionFinanceDashboard(models.TransientModel):
    _name = 'subscription.finance.dashboard'
    _description = 'Finance Analytics Aggregator'

    @api.model
    def get_financial_kpis(self, date_from=None, date_to=None, plan_id=None):
        params = []
        where_clause = "WHERE 1=1"

        if date_from:
            where_clause += " AND sub.start_date >= %s"
            params.append(date_from)
        if date_to:
            where_clause += " AND sub.start_date <= %s"
            params.append(date_to)
        if plan_id:
            where_clause += " AND sub.plan_id = %s"
            params.append(int(plan_id))

        query = f"""
            WITH sub_aggregates AS (
                SELECT 
                    COUNT(id) AS total_subs,
                    COUNT(CASE WHEN state = 'active' THEN 1 END) AS active_subs,
                    COUNT(CASE WHEN state = 'cancelled' THEN 1 END) AS cancelled_subs
                FROM subscription_subscription sub
                {where_clause}
            ),
            invoice_aggregates AS (
                SELECT
                    COALESCE(SUM(inv.amount_total), 0.0) AS total_invoiced,
                    COALESCE(SUM(inv.amount_residual), 0.0) AS total_outstanding,
                    COALESCE(SUM(CASE WHEN inv.invoice_date_due < CURRENT_DATE AND inv.amount_residual > 0 
                                      THEN inv.amount_residual ELSE 0 END), 0.0) AS total_overdue,
                    COUNT(CASE WHEN inv.payment_state = 'paid' THEN 1 END) AS paid_invoices_count,
                    COUNT(CASE WHEN inv.payment_state != 'paid' THEN 1 END) AS unpaid_invoices_count
                FROM account_move inv
                INNER JOIN subscription_subscription sub ON inv.subscription_id = sub.id
                {where_clause} AND inv.move_type = 'out_invoice' AND inv.state = 'posted'
            ),
            payment_aggregates AS (
                SELECT 
                    COALESCE(SUM(pay.amount), 0.0) AS total_revenue_collected
                FROM account_payment pay
                INNER JOIN account_move inv ON pay.id = inv.payment_id
                INNER JOIN subscription_subscription sub ON inv.subscription_id = sub.id
                {where_clause} AND pay.state = 'posted'
            )
            SELECT * FROM sub_aggregates, invoice_aggregates, payment_aggregates;
        """

        try:
            self.env.cr.execute(query, tuple(params * 3))
            kpi_metrics = self.env.cr.dictfetchone() or {}
        except Exception:
            kpi_metrics = {}

        trend_query = """
            SELECT 
                TO_CHAR(p.date, 'YYYY-MM') AS month_label,
                SUM(p.amount) as revenue_collected
            FROM account_payment p
            WHERE p.state = 'posted' AND p.date >= %s
            GROUP BY TO_CHAR(p.date, 'YYYY-MM')
            ORDER BY month_label ASC;
        """
        six_months_ago = fields.Date.today() - timedelta(days=180)
        try:
            self.env.cr.execute(trend_query, (six_months_ago,))
            revenue_trend = self.env.cr.dictfetchall()
        except Exception:
            revenue_trend = []

        plan_query = """
            SELECT p.name AS plan_name, COUNT(s.id) as subscriber_count
            FROM subscription_subscription s
            JOIN subscription_plan p ON s.plan_id = p.id
            WHERE s.state = 'active'
            GROUP BY p.name;
        """
        try:
            self.env.cr.execute(plan_query)
            plan_distribution = self.env.cr.dictfetchall()
        except Exception:
            plan_distribution = []

        return {
            'active_subscriptions': kpi_metrics.get('active_subs', 0),
            'total_subscriptions': kpi_metrics.get('total_subs', 0),
            'revenue_collected': kpi_metrics.get('total_revenue_collected', 0.0),
            'invoiced_amount': kpi_metrics.get('total_invoiced', 0.0),
            'outstanding_amount': kpi_metrics.get('total_outstanding', 0.0),
            'overdue_amount': kpi_metrics.get('total_overdue', 0.0),
            'paid_invoices_count': kpi_metrics.get('paid_invoices_count', 0),
            'unpaid_invoices_count': kpi_metrics.get('unpaid_invoices_count', 0),
            'revenue_trend': revenue_trend,
            'plan_distribution': plan_distribution,
        }