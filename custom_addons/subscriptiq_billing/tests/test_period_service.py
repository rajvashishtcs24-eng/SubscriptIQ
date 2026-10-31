# -*- coding: utf-8 -*-
# Part of SubscriptIQ. See LICENSE file for full copyright and licensing details.

import unittest
from datetime import date
from ..services.period_service import PeriodService


class TestPeriodService(unittest.TestCase):
    """
    Unit tests for PeriodService pure Python calendar and billing period arithmetic.
    """

    def test_daily_standard(self):
        p_start, p_end, n_date = PeriodService.compute_period('daily', date(2026, 11, 1))
        self.assertEqual(p_start, date(2026, 11, 1))
        self.assertEqual(p_end, date(2026, 11, 1))
        self.assertEqual(n_date, date(2026, 11, 2))

    def test_weekly_standard(self):
        p_start, p_end, n_date = PeriodService.compute_period('weekly', date(2026, 11, 1))
        self.assertEqual(p_start, date(2026, 11, 1))
        self.assertEqual(p_end, date(2026, 11, 7))
        self.assertEqual(n_date, date(2026, 11, 8))

    def test_monthly_standard(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2026, 11, 15), day_anchor=15)
        self.assertEqual(p_start, date(2026, 11, 15))
        self.assertEqual(p_end, date(2026, 12, 14))
        self.assertEqual(n_date, date(2026, 12, 15))

    def test_monthly_jan31(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2026, 1, 31), day_anchor=31)
        self.assertEqual(p_start, date(2026, 1, 31))
        self.assertEqual(n_date, date(2026, 2, 28))
        self.assertEqual(p_end, date(2026, 2, 27))

    def test_monthly_feb28_anchor31(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2026, 2, 28), day_anchor=31)
        self.assertEqual(n_date, date(2026, 3, 31))

    def test_monthly_apr30_anchor31(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2026, 4, 30), day_anchor=31)
        self.assertEqual(n_date, date(2026, 5, 31))

    def test_monthly_leap_feb29(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2028, 2, 29), day_anchor=29)
        self.assertEqual(n_date, date(2028, 3, 29))

    def test_monthly_non_leap_anchor29(self):
        p_start, p_end, n_date = PeriodService.compute_period('monthly', date(2027, 2, 28), day_anchor=29)
        self.assertEqual(n_date, date(2027, 3, 29))

    def test_yearly_standard(self):
        p_start, p_end, n_date = PeriodService.compute_period('yearly', date(2026, 6, 15), day_anchor=15)
        self.assertEqual(p_start, date(2026, 6, 15))
        self.assertEqual(p_end, date(2027, 6, 14))
        self.assertEqual(n_date, date(2027, 6, 15))

    def test_yearly_leap_feb29(self):
        p_start, p_end, n_date = PeriodService.compute_period('yearly', date(2028, 2, 29), day_anchor=29)
        self.assertEqual(n_date, date(2029, 2, 28))

    def test_is_leap_year_logic(self):
        self.assertTrue(PeriodService.is_leap_year(2028))
        self.assertFalse(PeriodService.is_leap_year(2026))
        self.assertFalse(PeriodService.is_leap_year(1900))
        self.assertTrue(PeriodService.is_leap_year(2000))

    def test_last_day_of_month_logic(self):
        self.assertEqual(PeriodService.last_day_of_month(2026, 2), 28)
        self.assertEqual(PeriodService.last_day_of_month(2028, 2), 29)
        self.assertEqual(PeriodService.last_day_of_month(2026, 4), 30)
        self.assertEqual(PeriodService.last_day_of_month(2026, 1), 31)
