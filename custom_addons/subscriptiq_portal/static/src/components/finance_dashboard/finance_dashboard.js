/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SubscriptionFinanceDashboard extends Component {
    static template = "subscription_platform.FinanceDashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            kpis: {},
            filters: {
                date_from: "",
                date_to: "",
                plan_id: null
            }
        });

        onWillStart(async () => {
            await this.loadDashboardMetrics();
        });
    }

    async loadDashboardMetrics() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "subscription.finance.dashboard",
                "get_financial_kpis",
                [],
                {
                    date_from: this.state.filters.date_from || false,
                    date_to: this.state.filters.date_to || false,
                    plan_id: this.state.filters.plan_id || false
                }
            );
            this.state.kpis = data || {};
        } catch (e) {
            console.error("Dashboard metric load error", e);
        } finally {
            this.state.loading = false;
        }
    }

    async onFilterChange(ev) {
        const { name, value } = ev.target;
        this.state.filters[name] = value;
        await this.loadDashboardMetrics();
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount || 0);
    }
}

registry.category("actions").add("action_subscription_finance_dashboard_client", SubscriptionFinanceDashboard);