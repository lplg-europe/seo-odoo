# -*- coding: utf-8 -*-
"""Opening the creation form must not crash.

The stats are computed with raw SQL on the record id. A record being
created carries a NewId, which psycopg2 cannot adapt into a query, so
merely clicking "New" raised ProgrammingError: can't adapt type 'NewId'.
These tests reproduce the onchange path (`.new()`) rather than a saved
record, which is the only way the bug shows.
"""
from odoo.tests import TransactionCase, tagged


@tagged("standard", "at_install")
class TestUnsavedRecords(TransactionCase):

    def test_new_site_computes_zeroes(self):
        site = self.env["web.analytics.site"].new({"name": "example.com"})
        self.assertFalse(isinstance(site.id, int), "record must be unsaved")
        for field in ("live_visitors", "visitors_today", "pageviews_today",
                      "visitors_30d", "pageviews_30d", "sessions_30d",
                      "bounce_rate_30d", "avg_session_seconds_30d",
                      "lcp_p75_ms"):
            self.assertEqual(site[field], 0, field)

    def test_new_goal_without_site(self):
        goal = self.env["web.analytics.goal"].new(
            {"name": "Signup", "goal_type": "page", "pattern": "/thanks"})
        self.assertEqual(goal.conversions_30d, 0)
        self.assertEqual(goal.conversion_rate, 0.0)

    def test_new_goal_on_unsaved_site(self):
        site = self.env["web.analytics.site"].new({"name": "example.com"})
        goal = self.env["web.analytics.goal"].new(
            {"name": "Signup", "goal_type": "page", "pattern": "/thanks",
             "site_id": site.id})
        self.assertEqual(goal.conversions_30d, 0)

    def test_new_funnel_step(self):
        funnel = self.env["web.analytics.funnel"].new({"name": "Checkout"})
        step = self.env["web.analytics.funnel.step"].new(
            {"name": "Cart", "funnel_id": funnel.id,
             "step_type": "page", "pattern": "/cart"})
        self.assertEqual(step.sessions_count, 0)
        self.assertEqual(step.conversion_pct, 0.0)
        self.assertEqual(step.drop_pct, 0.0)

    def test_saved_site_still_queries(self):
        """The guard must not silence a real site: a saved one still runs
        the SQL and simply reports zero when it has no events."""
        site = self.env["web.analytics.site"].create({"name": "saved.test"})
        self.assertTrue(isinstance(site.id, int))
        self.assertEqual(site.pageviews_30d, 0)
        self.env["web.analytics.event"].create({
            "site_id": site.id, "event_type": "pageview", "path": "/",
            "visitor_hash": "abcdef123456", "session_id": "s1",
            "is_new_session": True,
        })
        site.invalidate_recordset()
        self.assertEqual(site.pageviews_30d, 1)
        self.assertEqual(site.sessions_30d, 1)
