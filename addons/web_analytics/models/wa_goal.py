# -*- coding: utf-8 -*-
"""Conversion goals — count sessions that hit a page, fire a custom
event, or click a given outbound link."""
from datetime import timedelta

from odoo import api, fields, models

GOAL_TYPES = [
    ("path", "Page visited (path starts with)"),
    ("event", "Custom event (exact name)"),
    ("outbound", "Outbound click (URL contains)"),
]


class WebAnalyticsGoal(models.Model):
    _name = "web.analytics.goal"
    _description = "Conversion goal"

    name = fields.Char(string="Goal", required=True)
    site_id = fields.Many2one(
        "web.analytics.site", string="Site", required=True,
        ondelete="cascade", index=True)
    goal_type = fields.Selection(
        GOAL_TYPES, string="Type", required=True, default="path")
    pattern = fields.Char(
        string="Pattern", required=True,
        help='Path prefix ("/merci"), event name ("contact_form") or '
             'URL fragment ("calendly.com") depending on the type.')
    active = fields.Boolean(default=True)
    conversions_30d = fields.Integer(
        compute="_compute_stats", string="Conversions (30d)",
        help="Distinct sessions that completed the goal.")
    conversion_rate = fields.Float(
        compute="_compute_stats", string="Rate (%)", digits=(6, 1),
        help="Conversions divided by the site's sessions (30 days).")

    def _matching_domain(self, since):
        self.ensure_one()
        domain = [("site_id", "=", self.site_id.id),
                  ("timestamp", ">=", since)]
        if self.goal_type == "path":
            domain += [("event_type", "=", "pageview"),
                       ("path", "=like", "%s%%" % self.pattern)]
        elif self.goal_type == "event":
            domain += [("event_type", "=", "event"),
                       ("event_name", "=", self.pattern)]
        else:
            domain += [("event_type", "=", "outbound"),
                       ("event_name", "like", self.pattern)]
        return domain

    @api.depends("goal_type", "pattern", "site_id")
    def _compute_stats(self):
        Event = self.env["web.analytics.event"]
        since = fields.Datetime.now() - timedelta(days=30)
        for rec in self:
            # unsaved goal or unsaved site: nothing to count yet, and a
            # NewId must never reach a query
            if (not rec.pattern or not rec.site_id
                    or not isinstance(rec.site_id.id, int)):
                rec.conversions_30d = 0
                rec.conversion_rate = 0.0
                continue
            rows = Event._read_group(
                rec._matching_domain(since), [],
                ["session_id:count_distinct"])
            rec.conversions_30d = rows[0][0] if rows else 0
            sessions = Event.search_count(
                [("site_id", "=", rec.site_id.id),
                 ("timestamp", ">=", since),
                 ("is_new_session", "=", True)])
            rec.conversion_rate = (
                100.0 * rec.conversions_30d / sessions if sessions else 0.0)

    def action_view_conversions(self):
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(days=30)
        return {
            "type": "ir.actions.act_window",
            "name": "Conversions — %s" % self.name,
            "res_model": "web.analytics.event",
            "view_mode": "list,graph",
            "domain": self._matching_domain(since),
        }
