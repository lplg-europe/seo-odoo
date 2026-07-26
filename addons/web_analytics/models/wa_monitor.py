# -*- coding: utf-8 -*-
"""Uptime monitoring — periodic HTTP checks with email alerts on
down/recovery transitions."""
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..analytics_lib import check_http

_logger = logging.getLogger(__name__)


class WebAnalyticsMonitor(models.Model):
    _name = "web.analytics.monitor"
    _description = "Uptime monitor"

    name = fields.Char(string="Monitor", required=True)
    url = fields.Char(string="URL", required=True)
    active = fields.Boolean(default=True)
    interval_minutes = fields.Integer(
        string="Check every (min)", default=5)
    notify_email = fields.Char(
        string="Alert email",
        help="Sent when the monitor goes down or recovers.")
    is_up = fields.Boolean(string="Up", readonly=True, default=True)
    last_status = fields.Integer(string="HTTP status", readonly=True)
    last_error = fields.Char(string="Last error", readonly=True)
    response_ms = fields.Integer(string="Response (ms)", readonly=True)
    last_check = fields.Datetime(string="Last check", readonly=True)
    last_change = fields.Datetime(string="Up/down since", readonly=True)
    downtime_count = fields.Integer(
        string="Outages", readonly=True,
        help="Number of up→down transitions observed.")

    def action_check_now(self):
        self._run_check()
        return True

    def _run_check(self):
        for monitor in self:
            status, response_ms, error = check_http(monitor.url)
            up = bool(status and status < 400)
            values = {
                "last_status": status,
                "last_error": error,
                "response_ms": response_ms,
                "last_check": fields.Datetime.now(),
            }
            if up != monitor.is_up:
                values["is_up"] = up
                values["last_change"] = fields.Datetime.now()
                if not up:
                    values["downtime_count"] = monitor.downtime_count + 1
                monitor._notify(up, status, error)
            monitor.write(values)

    def _notify(self, up, status, error):
        self.ensure_one()
        if not self.notify_email:
            return
        label = ("HTTP %d" % status) if status else (error or "unreachable")
        subject = "%s %s is %s (%s)" % (
            "✅" if up else "🔴", self.name, "UP" if up else "DOWN", label)
        try:
            self.env["mail.mail"].sudo().create({
                "subject": subject,
                "email_to": self.notify_email,
                "body_html": "<p>%s<br/>URL: %s<br/>Status: %s</p>" % (
                    subject, self.url, label),
                "auto_delete": True,
            }).send()
        except Exception:  # noqa: BLE001 — alerting must never break checks
            _logger.exception("Uptime alert email failed for %s", self.name)

    @api.model
    def _cron_check(self):
        now = fields.Datetime.now()
        for monitor in self.search([("active", "=", True)]):
            due = (not monitor.last_check or monitor.last_check
                   + timedelta(minutes=max(1, monitor.interval_minutes))
                   <= now)
            if not due:
                continue
            try:
                monitor._run_check()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 — keep checking the others
                _logger.exception("Uptime check failed for %s", monitor.name)
                self.env.cr.rollback()
