# -*- coding: utf-8 -*-
"""A website tracked by the analytics module."""
import secrets
from datetime import timedelta

from odoo import api, fields, models


class WebAnalyticsSite(models.Model):
    _name = "web.analytics.site"
    _description = "Tracked website"

    name = fields.Char(string="Website", required=True,
                       help="Display name, e.g. lesjardins… or lplg.eu")
    token = fields.Char(
        string="Site token", required=True, copy=False, index=True,
        default=lambda self: secrets.token_hex(8))
    active = fields.Boolean(default=True)
    allowed_hosts = fields.Char(
        string="Allowed hostnames",
        help="Optional comma-separated hostnames; events sent for other "
             "hostnames are dropped (anti-spam).")
    event_ids = fields.One2many(
        "web.analytics.event", "site_id", string="Events")
    snippet = fields.Text(
        compute="_compute_snippet", string="Tracking snippet",
        help="Paste before </head> on the website to track.")
    live_visitors = fields.Integer(
        compute="_compute_stats", string="Live visitors",
        help="Unique visitors over the last 5 minutes.")
    visitors_today = fields.Integer(
        compute="_compute_stats", string="Visitors today")
    pageviews_today = fields.Integer(
        compute="_compute_stats", string="Pageviews today")
    visitors_30d = fields.Integer(
        compute="_compute_stats", string="Visitors (30d)")
    pageviews_30d = fields.Integer(
        compute="_compute_stats", string="Pageviews (30d)")
    sessions_30d = fields.Integer(
        compute="_compute_stats", string="Sessions (30d)")

    def _compute_snippet(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        for rec in self:
            rec.snippet = (
                '<script defer src="%s/wa/script.js" data-token="%s">'
                "</script>" % (base_url, rec.token))

    def _distinct_visitors(self, since):
        self.ensure_one()
        rows = self.env["web.analytics.event"]._read_group(
            [("site_id", "=", self.id), ("timestamp", ">=", since)],
            [], ["visitor_hash:count_distinct"])
        return rows[0][0] if rows else 0

    def _compute_stats(self):
        Event = self.env["web.analytics.event"]
        now = fields.Datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = now - timedelta(days=30)
        for rec in self:
            base = [("site_id", "=", rec.id)]
            rec.live_visitors = rec._distinct_visitors(
                now - timedelta(minutes=5))
            rec.visitors_today = rec._distinct_visitors(today)
            rec.pageviews_today = Event.search_count(
                base + [("timestamp", ">=", today),
                        ("event_type", "=", "pageview")])
            rec.visitors_30d = rec._distinct_visitors(month)
            rec.pageviews_30d = Event.search_count(
                base + [("timestamp", ">=", month),
                        ("event_type", "=", "pageview")])
            rec.sessions_30d = Event.search_count(
                base + [("timestamp", ">=", month),
                        ("is_new_session", "=", True)])

    def action_view_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Events — %s" % self.name,
            "res_model": "web.analytics.event",
            "view_mode": "graph,list,pivot",
            "domain": [("site_id", "=", self.id)],
            "context": {"search_default_filter_30d": 1},
        }
