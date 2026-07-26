# -*- coding: utf-8 -*-
"""One analytics event (pageview or custom event) — privacy-first:
no cookie, no IP stored, anonymous daily-rotating visitor hash."""
import secrets
from datetime import timedelta

from odoo import api, fields, models

from ..analytics_lib import SESSION_WINDOW_MINUTES

EVENT_TYPES = [
    ("pageview", "Pageview"),
    ("event", "Custom event"),
    ("outbound", "Outbound click"),
    ("error", "JS error"),
    ("performance", "Web vitals"),
]


class WebAnalyticsEvent(models.Model):
    _name = "web.analytics.event"
    _description = "Analytics event"
    _order = "timestamp desc, id desc"
    _rec_name = "path"

    site_id = fields.Many2one(
        "web.analytics.site", string="Site", required=True,
        ondelete="cascade", index=True)
    timestamp = fields.Datetime(
        string="Time", required=True, index=True,
        default=fields.Datetime.now)
    event_type = fields.Selection(
        EVENT_TYPES, string="Type", required=True, default="pageview")
    event_name = fields.Char(string="Event name")
    path = fields.Char(string="Path", index=True)
    page_title = fields.Char(string="Page title")
    referrer_host = fields.Char(string="Referrer", index=True)
    channel = fields.Char(string="Channel", index=True)
    utm_source = fields.Char(string="UTM source")
    utm_medium = fields.Char(string="UTM medium")
    utm_campaign = fields.Char(string="UTM campaign")
    visitor_hash = fields.Char(string="Visitor", index=True, size=12)
    session_id = fields.Char(string="Session", index=True, size=14)
    is_new_session = fields.Boolean(
        string="New session", help="First event of its session — counting "
                                   "these counts sessions.")
    device_type = fields.Selection(
        [("desktop", "Desktop"), ("mobile", "Mobile"),
         ("tablet", "Tablet")], string="Device")
    browser = fields.Char(string="Browser")
    os = fields.Char(string="OS")
    lang = fields.Char(string="Language", size=8)
    country = fields.Char(
        string="Country", size=2, index=True,
        help="ISO country code (needs a GeoIP database configured on "
             "the Odoo server; empty otherwise).")
    lcp_ms = fields.Integer(
        string="LCP (ms)", help="Largest Contentful Paint.")
    fcp_ms = fields.Integer(
        string="FCP (ms)", help="First Contentful Paint.")
    ttfb_ms = fields.Integer(
        string="TTFB (ms)", help="Time To First Byte.")
    cls_milli = fields.Integer(
        string="CLS (x1000)",
        help="Cumulative Layout Shift multiplied by 1000 "
             "(100 = CLS 0.1, the 'good' threshold).")

    @api.model
    def _ingest(self, site, values):
        """Create an event, reusing the visitor's session when its last
        activity is under 30 minutes old (sliding window)."""
        last = self.search(
            [("site_id", "=", site.id),
             ("visitor_hash", "=", values["visitor_hash"])],
            order="timestamp desc", limit=1)
        window = fields.Datetime.now() - timedelta(
            minutes=SESSION_WINDOW_MINUTES)
        if last and last.timestamp >= window:
            values["session_id"] = last.session_id
            values["is_new_session"] = False
        else:
            values["session_id"] = secrets.token_hex(7)
            values["is_new_session"] = True
        values["site_id"] = site.id
        return self.create(values)
