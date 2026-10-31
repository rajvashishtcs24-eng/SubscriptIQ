# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import logging
from typing import List, Dict, Any, Optional

_logger = logging.getLogger(__name__)


class DiscountService:
    """
    Handles discount rule evaluation, atomic reservation, and proportional
    fixed-discount allocation as approved in Rev 3.
    """

    @staticmethod
    def find_eligible_rule(
        env,
        partner_id: int,
        lines: List[Dict[str, Any]],
        billing_date,
        total_untaxed: float = 0.0,
        subscription_id: Optional[int] = None,
    ):
        """
        Evaluates active DiscountRules and returns the highest priority rule (lowest priority number).
        No stacking is permitted (T-14).
        """
        domain = [('active', '=', True)]
        rules = env['subscriptiq.discount.rule'].search(domain, order='priority ASC, id ASC')

        total_qty = sum(line.get('quantity', 0.0) for line in lines)
        product_ids = {line.get('product_id') for line in lines if line.get('product_id')}

        for rule in rules:
            # 1. Date validity check
            if rule.date_start and billing_date < rule.date_start:
                continue
            if rule.date_end and billing_date > rule.date_end:
                continue

            # 2. Usage limits check
            if rule.max_uses > 0 and rule.current_uses >= rule.max_uses:
                continue

            # 3. Minimum quantity check
            if rule.min_qty > 0 and total_qty < rule.min_qty:
                continue

            # 4. Minimum amount untaxed check
            if rule.min_amount_untaxed > 0:
                if total_untaxed < rule.min_amount_untaxed:
                    continue

            # 5. Product filter check (if restricted)
            if rule.product_ids:
                rule_pids = set(rule.product_ids.ids)
                if not rule_pids.intersection(product_ids):
                    continue

            # 6. Specific subscription filter (if specified)
            if rule.subscription_id_filter and subscription_id:
                allowed_subs = [int(s.strip()) for s in rule.subscription_id_filter.split(',') if s.strip().isdigit()]
                if allowed_subs and subscription_id not in allowed_subs:
                    continue

            # Highest priority eligible rule found
            return rule

        return None

    @staticmethod
    def allocate_fixed_discount(
        lines: List[Dict[str, Any]],
        fixed_discount_amount: float,
        currency,
        rule_product_ids=None,
    ) -> List[Dict[str, Any]]:
        """
        Executes the 11-step Rev 3 proportional fixed-discount allocation formula.
        Applies line-level percentage to native account.move.line.discount
        while leaving line price_unit unmodified (T-13, T-16).
        """
        if fixed_discount_amount <= 0 or not lines:
            for l in lines:
                l['discount'] = 0.0
            return lines

        # Step 1: Identify eligible lines
        eligible_indices = []
        for idx, line in enumerate(lines):
            pid = line.get('product_id')
            qty = line.get('quantity', 0.0)
            price_unit = line.get('price_unit', 0.0)
            subtotal = price_unit * qty

            # Exclude zero-value lines (Section 6.4)
            if subtotal <= 0:
                line['discount'] = 0.0
                continue

            if rule_product_ids and pid not in rule_product_ids:
                line['discount'] = 0.0
                continue

            eligible_indices.append(idx)

        # Step 2: Compute eligible subtotals
        subtotals = {}
        for idx in eligible_indices:
            l = lines[idx]
            subtotals[idx] = l['price_unit'] * l['quantity']
        s_total = sum(subtotals.values())

        # Step 3: Zero-total guard
        if s_total <= 0 or not eligible_indices:
            _logger.info("Total eligible amount is zero; proceeding without fixed discount allocation.")
            for l in lines:
                l['discount'] = 0.0
            return lines

        # Step 4: Guard discount exceeds total (Q-7: cap at 100% of eligible subtotal)
        d = min(fixed_discount_amount, s_total)

        # Step 5 & 6: Compute raw allocation and currency round
        allocations = {}
        for idx in eligible_indices:
            raw_alloc = d * (subtotals[idx] / s_total)
            allocations[idx] = currency.round(raw_alloc) if currency else round(raw_alloc, 2)

        # Step 7: Compute rounding remainder
        allocated_total = sum(allocations.values())
        d_rounded = currency.round(d) if currency else round(d, 2)
        remainder = d_rounded - allocated_total

        # Step 8: Allocate remainder to the first eligible line (Option A / Q-8)
        if remainder != 0:
            first_idx = eligible_indices[0]
            allocations[first_idx] = (currency.round(allocations[first_idx] + remainder)
                                     if currency else round(allocations[first_idx] + remainder, 2))

        # Step 9 & 10: Convert allocated amount to discount percentage for each line
        for idx in eligible_indices:
            s_i = subtotals[idx]
            alloc_i = allocations[idx]
            discount_pct = (alloc_i / s_i) * 100.0 if s_i > 0 else 0.0
            # Clamp between 0.0 and 100.0
            lines[idx]['discount'] = min(max(discount_pct, 0.0), 100.0)

        # Step 11: Ineligible lines have discount = 0.0
        for idx, line in enumerate(lines):
            if idx not in eligible_indices:
                line['discount'] = 0.0

        return lines
