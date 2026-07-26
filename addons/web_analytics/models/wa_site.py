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
    daily_salt_rotation = fields.Boolean(
        string="Daily visitor-id rotation", default=True,
        help="ON (default): the anonymous visitor hash rotates every day — "
             "maximum privacy, but weekly retention cannot be measured.\n"
             "OFF: the hash stays stable across days (still cookieless, "
             "still no IP stored) — enables the retention cohorts.")
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
    bounce_rate_30d = fields.Integer(
        compute="_compute_stats", string="Bounce rate (%)",
        help="Sessions with a single pageview (30 days).")
    avg_session_seconds_30d = fields.Integer(
        compute="_compute_stats", string="Avg session (s)")
    lcp_p75_ms = fields.Integer(
        compute="_compute_stats", string="LCP p75 (ms)",
        help="75th percentile of Largest Contentful Paint (30 days) — "
             "good is under 2500 ms.")
    goal_ids = fields.One2many(
        "web.analytics.goal", "site_id", string="Goals")
    funnel_ids = fields.One2many(
        "web.analytics.funnel", "site_id", string="Funnels")
    retention_table = fields.Text(
        string="Retention cohorts", readonly=True)
    retention_date = fields.Datetime(
        string="Retention computed on", readonly=True)

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
            rec._compute_sql_stats(month)

    def _compute_sql_stats(self, since):
        """Bounce rate, avg session duration and LCP p75 (raw SQL —
        window/percentile aggregates the ORM cannot express)."""
        self.ensure_one()
        self.env.cr.execute("""
            WITH s AS (
                SELECT session_id,
                       COUNT(*) FILTER (WHERE event_type = 'pageview') AS pv,
                       EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp))
                           AS duration
                FROM web_analytics_event
                WHERE site_id = %s AND timestamp >= %s
                GROUP BY session_id)
            SELECT
                COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE pv <= 1)
                         / NULLIF(COUNT(*), 0)), 0),
                COALESCE(ROUND(AVG(duration)), 0)
            FROM s
        """, (self.id, since))
        bounce, avg_duration = self.env.cr.fetchone()
        self.bounce_rate_30d = int(bounce or 0)
        self.avg_session_seconds_30d = int(avg_duration or 0)
        self.env.cr.execute("""
            SELECT COALESCE(PERCENTILE_CONT(0.75)
                   WITHIN GROUP (ORDER BY lcp_ms), 0)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
              AND event_type = 'performance' AND lcp_ms > 0
        """, (self.id, since))
        self.lcp_p75_ms = int(self.env.cr.fetchone()[0] or 0)

    RETENTION_WEEKS = 8

    def action_compute_retention(self):
        """Weekly retention cohorts: share of each week's new visitors
        seen again in the following weeks."""
        self.ensure_one()
        weeks = self.RETENTION_WEEKS
        self.env.cr.execute("""
            WITH firsts AS (
                SELECT visitor_hash,
                       DATE_TRUNC('week', MIN(timestamp)) AS cohort
                FROM web_analytics_event
                WHERE site_id = %s AND timestamp >= %s
                GROUP BY visitor_hash),
            activity AS (
                SELECT DISTINCT visitor_hash,
                       DATE_TRUNC('week', timestamp) AS week
                FROM web_analytics_event
                WHERE site_id = %s AND timestamp >= %s)
            SELECT f.cohort::date,
                   FLOOR(EXTRACT(EPOCH FROM (a.week - f.cohort))
                         / 604800)::int AS offset_weeks,
                   COUNT(DISTINCT a.visitor_hash)
            FROM firsts f
            JOIN activity a USING (visitor_hash)
            GROUP BY 1, 2 ORDER BY 1, 2
        """, (self.id, fields.Datetime.now() - timedelta(weeks=weeks),
              self.id, fields.Datetime.now() - timedelta(weeks=weeks)))
        rows = self.env.cr.fetchall()
        cohorts = {}
        for cohort, offset, count in rows:
            cohorts.setdefault(cohort, {})[offset] = count
        lines = ["%-12s %8s  %s" % ("Cohort", "Visitors", " ".join(
            "%6s" % ("W+%d" % i) for i in range(weeks)))]
        for cohort in sorted(cohorts):
            data = cohorts[cohort]
            base = data.get(0, 0) or 1
            cells = []
            for i in range(weeks):
                if i in data:
                    cells.append("%5d%%" % round(100.0 * data[i] / base))
                else:
                    cells.append("%6s" % "·")
            lines.append("%-12s %8d  %s" % (
                cohort.strftime("%Y-%m-%d"), data.get(0, 0),
                " ".join(cells)))
        if self.daily_salt_rotation:
            lines.append("")
            lines.append(
                "⚠ Daily visitor-id rotation is ON for this site: visitors "
                "cannot be recognized across days, so cross-week retention "
                "reads ~0%. Turn the rotation off (Setup) to measure "
                "retention from now on.")
        self.write({
            "retention_table": "\n".join(lines),
            "retention_date": fields.Datetime.now(),
        })
        return True

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

    # ------------------------------------------------------------------
    # Printed report
    # ------------------------------------------------------------------

    @staticmethod
    def _report_delta(current, previous):
        """Percent change vs the previous period, None when no baseline."""
        if not previous:
            return None
        return int(round(100.0 * (current - previous) / previous))

    def _report_data(self, days=30):
        """Everything the printed traffic report needs, in one dict —
        last `days` days vs the previous period, raw SQL over the event
        table (aggregates the ORM cannot express)."""
        self.ensure_one()
        cr = self.env.cr
        now = fields.Datetime.now()
        since = now - timedelta(days=days)
        prev_since = now - timedelta(days=2 * days)

        def kpis(lo, hi):
            cr.execute("""
                SELECT COUNT(DISTINCT visitor_hash),
                       COUNT(*) FILTER (WHERE event_type = 'pageview'),
                       COUNT(*) FILTER (WHERE is_new_session)
                FROM web_analytics_event
                WHERE site_id = %s AND timestamp >= %s AND timestamp < %s
            """, (self.id, lo, hi))
            visitors, pageviews, sessions = cr.fetchone()
            cr.execute("""
                WITH s AS (
                    SELECT session_id,
                           COUNT(*) FILTER (WHERE event_type = 'pageview')
                               AS pv,
                           EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp))
                               AS d
                    FROM web_analytics_event
                    WHERE site_id = %s AND timestamp >= %s AND timestamp < %s
                    GROUP BY session_id)
                SELECT COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE pv <= 1)
                                / NULLIF(COUNT(*), 0)), 0),
                       COALESCE(ROUND(AVG(d)), 0)
                FROM s
            """, (self.id, lo, hi))
            bounce, duration = cr.fetchone()
            return {
                "visitors": visitors or 0, "pageviews": pageviews or 0,
                "sessions": sessions or 0, "bounce": int(bounce or 0),
                "duration": int(duration or 0),
            }

        current = kpis(since, now)
        previous = kpis(prev_since, since)

        cr.execute("""
            SELECT timestamp::date,
                   COUNT(*) FILTER (WHERE event_type = 'pageview')
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
            GROUP BY 1
        """, (self.id, since))
        by_day = dict(cr.fetchall())
        series = []
        for offset in range(days):
            day = (now - timedelta(days=days - 1 - offset)).date()
            series.append({"day": day, "pageviews": by_day.get(day, 0)})
        max_pageviews = max([s["pageviews"] for s in series] + [1])

        def top(query, params, limit):
            cr.execute(query + " LIMIT %d" % limit, params)
            return cr.fetchall()

        top_pages = top("""
            SELECT path, COUNT(*), COUNT(DISTINCT visitor_hash)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
              AND event_type = 'pageview' AND COALESCE(path, '') != ''
            GROUP BY path ORDER BY 2 DESC
        """, (self.id, since), 10)

        channels = top("""
            SELECT COALESCE(NULLIF(channel, ''), 'Direct'), COUNT(*)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s AND is_new_session
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 12)

        referrers = top("""
            SELECT referrer_host, COUNT(*)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s AND is_new_session
              AND COALESCE(referrer_host, '') != ''
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 10)

        campaigns = top("""
            SELECT utm_campaign, COUNT(*)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s AND is_new_session
              AND COALESCE(utm_campaign, '') != ''
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 8)

        devices = top("""
            SELECT COALESCE(device_type, 'unknown'),
                   COUNT(DISTINCT visitor_hash)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 5)

        countries = top("""
            SELECT country, COUNT(DISTINCT visitor_hash)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
              AND COALESCE(country, '') != ''
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 8)

        custom_events = top("""
            SELECT event_name, COUNT(*)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
              AND event_type NOT IN ('pageview', 'performance')
              AND COALESCE(event_name, '') != ''
            GROUP BY 1 ORDER BY 2 DESC
        """, (self.id, since), 8)

        cr.execute("""
            SELECT COALESCE(PERCENTILE_CONT(0.75)
                   WITHIN GROUP (ORDER BY lcp_ms), 0)
            FROM web_analytics_event
            WHERE site_id = %s AND timestamp >= %s
              AND event_type = 'performance' AND lcp_ms > 0
        """, (self.id, since))
        lcp_p75 = int(cr.fetchone()[0] or 0)

        goals = [{
            "name": goal.name, "conversions": goal.conversions_30d,
            "rate": goal.conversion_rate,
        } for goal in self.goal_ids.filtered("active")]

        return {
            "days": days, "since": since, "until": now,
            "current": current, "previous": previous,
            "deltas": {key: self._report_delta(current[key], previous[key])
                       for key in current},
            "series": series, "max_pageviews": max_pageviews,
            "top_pages": top_pages,
            "channels": channels,
            "channel_total": sum(n for _, n in channels) or 1,
            "referrers": referrers, "campaigns": campaigns,
            "devices": devices,
            "device_total": sum(n for _, n in devices) or 1,
            "countries": countries, "custom_events": custom_events,
            "lcp_p75": lcp_p75, "goals": goals,
            "conversions_total": sum(g["conversions"] for g in goals),
        }
