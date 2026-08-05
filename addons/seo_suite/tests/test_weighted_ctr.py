# -*- coding: utf-8 -*-
"""A rate aggregated over a group must be weighted, never averaged.

Odoo offers sum/avg/min/max and nothing else, so a CTR grouped by month
came out as the mean of daily rates: a day with 2 impressions counted as
much as a day with 300. On real data a 12.07% month was reported as
8.42%. These tests pin the corrected arithmetic and the shape of the
result, which is easy to break when touching _read_group.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import TransactionCase, tagged


@tagged("standard", "at_install")
class TestWeightedCtr(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = cls.env["seo.site"].create({"name": "https://ctr.test"})
        # One quiet day at 50%, one busy day at 1%. The plain mean says
        # 25.5%; the truth is 51/1002 = 5.09%.
        cls.env["seo.search.performance"].create([
            {"site_id": cls.site.id, "date": "2026-01-01",
             "clicks": 1, "impressions": 2, "ctr": 50.0, "position": 3.0},
            {"site_id": cls.site.id, "date": "2026-01-02",
             "clicks": 50, "impressions": 1000, "ctr": 5.0, "position": 12.0},
        ])
        cls.model = cls.env["seo.search.performance"]
        cls.domain = [("site_id", "=", cls.site.id)]

    def test_grouped_ctr_is_the_ratio_of_totals(self):
        [(_site, ctr)] = self.model._read_group(
            self.domain, ["site_id"], ["ctr:avg"])
        self.assertAlmostEqual(ctr, 100.0 * 51 / 1002, places=4)

    def test_plain_mean_would_have_been_wrong(self):
        [(_site, ctr)] = self.model._read_group(
            self.domain, ["site_id"], ["ctr:avg"])
        self.assertNotAlmostEqual(ctr, (50.0 + 5.0) / 2, places=2)

    def test_helper_aggregates_are_not_leaked_into_the_result(self):
        # the override adds clicks/impressions to the query to compute the
        # ratio; a caller asking for one aggregate must get one value
        rows = self.model._read_group(self.domain, ["site_id"], ["ctr:avg"])
        self.assertEqual(len(rows[0]), 2, rows)

    def test_requested_aggregates_keep_their_order_and_values(self):
        [(_site, clicks, ctr, impressions)] = self.model._read_group(
            self.domain, ["site_id"],
            ["clicks:sum", "ctr:avg", "impressions:sum"])
        self.assertEqual(clicks, 51)
        self.assertEqual(impressions, 1002)
        self.assertAlmostEqual(ctr, 100.0 * 51 / 1002, places=4)

    def test_other_averages_are_left_alone(self):
        # position is a rank, its plain mean is the right answer
        [(_site, position)] = self.model._read_group(
            self.domain, ["site_id"], ["position:avg"])
        self.assertAlmostEqual(position, 7.5, places=4)

    def test_zero_impressions_does_not_divide_by_zero(self):
        empty = self.env["seo.site"].create({"name": "https://silent.test"})
        self.env["seo.search.performance"].create({
            "site_id": empty.id, "date": "2026-01-01",
            "clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0})
        [(_site, ctr)] = self.model._read_group(
            [("site_id", "=", empty.id)], ["site_id"], ["ctr:avg"])
        self.assertEqual(ctr, 0.0)

    def test_grouping_by_month_stays_weighted(self):
        [(_month, ctr)] = self.model._read_group(
            self.domain, ["date:month"], ["ctr:avg"])
        self.assertAlmostEqual(ctr, 100.0 * 51 / 1002, places=4)


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
