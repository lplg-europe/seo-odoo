# -*- coding: utf-8 -*-
"""Measures that must never be summed in a graph or pivot view.

Odoo aggregates numeric fields with SUM unless the field says otherwise.
For a state measured at a point in time — a score, a rank, a percentage —
that produces nonsense: the crawl-history graph showed a 0-100 score
climbing past 450 because it added up every snapshot of the day.

Counts stay additive on purpose, so this also pins the fields that must
*not* be averaged.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import BaseCase, TransactionCase, tagged


@tagged("standard", "at_install")
class TestHistoryAggregators(TransactionCase):

    AVERAGED = [
        "score", "page_count", "discovered_count", "error_page_count",
        "issue_count", "critical_count", "warning_count", "info_count",
        "site_issue_count", "broken_link_count", "avg_response_time",
        "avg_word_count",
    ]
    # Produced by one crawl, so a period total is meaningful.
    SUMMED = [
        "new_issue_count", "resolved_issue_count",
        "new_page_count", "removed_page_count",
    ]

    def test_snapshot_measures_are_averaged(self):
        fields_ = self.env["seo.crawl.history"]._fields
        for name in self.AVERAGED:
            self.assertEqual(
                fields_[name].aggregator, "avg",
                "%s is a state, not a quantity: summing snapshots of it "
                "is meaningless" % name)

    def test_per_crawl_counts_stay_additive(self):
        fields_ = self.env["seo.crawl.history"]._fields
        for name in self.SUMMED:
            self.assertNotEqual(
                fields_[name].aggregator, "avg",
                "%s counts what one crawl produced — a period total is "
                "the useful figure" % name)


@tagged("standard", "at_install")
class TestKeywordAggregators(TransactionCase):

    def test_rank_and_rate_are_averaged(self):
        fields_ = self.env["seo.keyword.history"]._fields
        for name in ("position", "ctr"):
            self.assertEqual(fields_[name].aggregator, "avg", name)

    def test_traffic_counts_stay_additive(self):
        fields_ = self.env["seo.keyword.history"]._fields
        for name in ("clicks", "impressions"):
            self.assertNotEqual(fields_[name].aggregator, "avg", name)


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
