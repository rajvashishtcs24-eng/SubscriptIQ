# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta
from typing import Tuple


class PeriodService:
    """
    Pure Python service for subscription billing period arithmetic.
    Handles anchor day adjustments, leap years, and month transitions.
    No database access or ORM dependencies.
    """

    @staticmethod
    def is_leap_year(year: int) -> bool:
        """Determines if a year is a leap year using Gregorian calendar rules."""
        if year % 400 == 0:
            return True
        if year % 100 == 0:
            return False
        return year % 4 == 0

    @staticmethod
    def last_day_of_month(year: int, month: int) -> int:
        """Returns the number of days in the specified month and year."""
        if month in {1, 3, 5, 7, 8, 10, 12}:
            return 31
        if month in {4, 6, 9, 11}:
            return 30
        if month == 2:
            return 29 if PeriodService.is_leap_year(year) else 28
        raise ValueError(f"Invalid month: {month}. Must be between 1 and 12.")

    @staticmethod
    def advance_monthly(current_date: date, day_anchor: int) -> date:
        """
        Calculates the next billing date one month in the future,
        preserving the original day_anchor where possible.
        If the target month has fewer days than day_anchor, caps to the last day of that month.
        """
        year = current_date.year
        month = current_date.month

        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1

        max_day = PeriodService.last_day_of_month(next_year, next_month)
        next_day = min(day_anchor, max_day)
        return date(next_year, next_month, next_day)

    @staticmethod
    def advance_yearly(current_date: date, day_anchor: int) -> date:
        """
        Calculates the next billing date one year in the future,
        handling Feb 29 on leap years appropriately.
        """
        next_year = current_date.year + 1
        month = current_date.month
        max_day = PeriodService.last_day_of_month(next_year, month)
        next_day = min(day_anchor, max_day)
        return date(next_year, month, next_day)

    @staticmethod
    def compute_period(
        frequency: str,
        anchor_date: date,
        day_anchor: int = None,
    ) -> Tuple[date, date, date]:
        """
        Computes the billing period (period_start, period_end, next_billing_date)
        from a given anchor date and billing frequency.

        Returns:
            Tuple[date, date, date]:
                period_start (inclusive)
                period_end (inclusive)
                next_billing_date (period_end + 1 day or anchored next date)
        """
        if not anchor_date:
            raise ValueError("anchor_date is required")

        if not day_anchor:
            day_anchor = anchor_date.day

        period_start = anchor_date

        if frequency == 'daily':
            period_end = period_start
            next_billing_date = period_start + timedelta(days=1)
        elif frequency == 'weekly':
            period_end = period_start + timedelta(days=6)
            next_billing_date = period_start + timedelta(days=7)
        elif frequency == 'monthly':
            next_billing_date = PeriodService.advance_monthly(period_start, day_anchor)
            period_end = next_billing_date - timedelta(days=1)
        elif frequency == 'yearly':
            next_billing_date = PeriodService.advance_yearly(period_start, day_anchor)
            period_end = next_billing_date - timedelta(days=1)
        else:
            raise ValueError(f"Unsupported billing frequency: {frequency}. Supported: daily, weekly, monthly, yearly")

        return period_start, period_end, next_billing_date
