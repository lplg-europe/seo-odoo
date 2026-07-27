# -*- coding: utf-8 -*-
"""Multi-step conversion funnels — how many sessions reach each step,
in order, within the analysis window."""
from datetime import timedelta

from odoo import api, fields, models

STEP_TYPES = [
    ("path", "Page visited (path starts with)"),
    ("event", "Custom event (exact name)"),
    ("outbound", "Outbound click (URL contains)"),
]


class WebAnalyticsFunnel(models.Model):
    _name = "web.analytics.funnel"
    _description = "Conversion funnel"

    name = fields.Char(string="Funnel", required=True)
    site_id = fields.Many2one(
        "web.analytics.site", string="Site", required=True,
        ondelete="cascade", index=True)
    period_days = fields.Integer(
        string="Window (days)", default=30,
        help="Sessions started within this window are analyzed.")
    step_ids = fields.One2many(
        "web.analytics.funnel.step", "funnel_id", string="Steps")
    completion_rate = fields.Float(
        compute="_compute_summary", string="Completion (%)", digits=(6, 1),
        help="Sessions reaching the last step vs sessions reaching "
             "the first one.")
    entered_sessions = fields.Integer(
        compute="_compute_summary", string="Sessions entered")

    @api.depends("step_ids.sessions_count")
    def _compute_summary(self):
        for rec in self:
            steps = rec.step_ids.sorted(
                key=lambda s: (s.sequence, s.id or 0))
            first = steps[:1].sessions_count if steps else 0
            last = steps[-1:].sessions_count if steps else 0
            rec.entered_sessions = first
            rec.completion_rate = 100.0 * last / first if first else 0.0

    def _step_sessions(self):
        """{step: {session_id: first_matching_timestamp}} computed
        sequentially — a session counts for step N only after having
        matched steps 1..N-1 in chronological order."""
        self.ensure_one()
        Event = self.env["web.analytics.event"]
        since = fields.Datetime.now() - timedelta(
            days=max(1, self.period_days or 30))
        reached_by_step = {}
        previous = None
        for step in self.step_ids.sorted(
                key=lambda s: (s.sequence, s.id or 0)):
            domain = [("site_id", "=", self.site_id.id),
                      ("timestamp", ">=", since)]
            if step.step_type == "path":
                domain += [("event_type", "=", "pageview"),
                           ("path", "=like", "%s%%" % (step.pattern or ""))]
            elif step.step_type == "event":
                domain += [("event_type", "=", "event"),
                           ("event_name", "=", step.pattern or "")]
            else:
                domain += [("event_type", "=", "outbound"),
                           ("event_name", "like", step.pattern or "")]
            rows = Event.search_read(
                domain, ["session_id", "timestamp"], order="timestamp asc")
            reached = {}
            for row in rows:
                sid = row["session_id"]
                if sid in reached:
                    continue
                if previous is None:
                    reached[sid] = row["timestamp"]
                else:
                    prev_ts = previous.get(sid)
                    if prev_ts is not None and row["timestamp"] >= prev_ts:
                        reached[sid] = row["timestamp"]
            reached_by_step[step] = reached
            previous = reached
        return reached_by_step


class WebAnalyticsFunnelStep(models.Model):
    _name = "web.analytics.funnel.step"
    _description = "Funnel step"
    _order = "funnel_id, sequence, id"

    funnel_id = fields.Many2one(
        "web.analytics.funnel", string="Funnel", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Step", required=True)
    step_type = fields.Selection(
        STEP_TYPES, string="Type", required=True, default="path")
    pattern = fields.Char(string="Pattern", required=True)
    sessions_count = fields.Integer(
        compute="_compute_counts", string="Sessions")
    conversion_pct = fields.Float(
        compute="_compute_counts", string="% of entry", digits=(6, 1))
    drop_pct = fields.Float(
        compute="_compute_counts", string="Drop-off (%)", digits=(6, 1),
        help="Share of the previous step's sessions lost at this step.")

    @api.depends("funnel_id", "sequence", "step_type", "pattern",
                 "funnel_id.period_days")
    def _compute_counts(self):
        # a funnel being created has a NewId: its steps have no sessions
        # yet, and querying on an unsaved id would fail
        unsaved = self.filtered(
            lambda s: s.funnel_id and not isinstance(s.funnel_id.id, int))
        for step in unsaved:
            step.sessions_count = 0
            step.conversion_pct = 0.0
            step.drop_pct = 0.0
        for funnel in (self - unsaved).mapped("funnel_id"):
            reached = funnel._step_sessions()
            first = None
            previous_count = None
            for step in funnel.step_ids.sorted(
                    key=lambda s: (s.sequence, s.id or 0)):
                count = len(reached.get(step, {}))
                if first is None:
                    first = count or 0
                step.sessions_count = count
                step.conversion_pct = 100.0 * count / first if first else 0.0
                step.drop_pct = (
                    100.0 * (previous_count - count) / previous_count
                    if previous_count else 0.0)
                previous_count = count
        for step in self.filtered(lambda s: not s.funnel_id):
            step.sessions_count = 0
            step.conversion_pct = 0.0
            step.drop_pct = 0.0
