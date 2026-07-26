# -*- coding: utf-8 -*-
"""One snapshot per crawl — powers the score trend and the crawl diff
(new/resolved issues, added/removed pages) between two runs."""
from odoo import api, fields, models

# (field, label, lower_is_better) — the crawl-to-crawl comparison table.
COMPARED_METRICS = [
    ("score", "Score", False),
    ("page_count", "Pages crawled", False),
    ("discovered_count", "URLs discovered", False),
    ("issue_count", "Page issues", True),
    ("critical_count", "Critical issues", True),
    ("warning_count", "Warnings", True),
    ("info_count", "Info issues", True),
    ("error_page_count", "Pages in error", True),
    ("site_issue_count", "Site-level issues", True),
    ("broken_link_count", "Broken links", True),
    ("avg_response_time", "Avg response (s)", True),
    ("avg_word_count", "Avg words/page", False),
]


class SeoCrawlHistory(models.Model):
    _name = "seo.crawl.history"
    _description = "SEO crawl snapshot"
    _order = "date desc, id desc"
    _rec_name = "date"

    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    date = fields.Datetime(
        string="Crawl date", required=True,
        default=fields.Datetime.now)
    score = fields.Integer(string="Score", readonly=True)
    score_delta = fields.Integer(
        string="Δ score", readonly=True,
        help="Score difference with the previous crawl.")
    page_count = fields.Integer(string="Pages", readonly=True)
    discovered_count = fields.Integer(string="URLs discovered", readonly=True)
    error_page_count = fields.Integer(string="Pages in error", readonly=True)
    issue_count = fields.Integer(string="Issues", readonly=True)
    critical_count = fields.Integer(string="Critical", readonly=True)
    warning_count = fields.Integer(string="Warnings", readonly=True)
    info_count = fields.Integer(string="Info", readonly=True)
    site_issue_count = fields.Integer(string="Site issues", readonly=True)
    broken_link_count = fields.Integer(string="Broken links", readonly=True)
    avg_response_time = fields.Float(
        string="Avg response (s)", digits=(6, 2), readonly=True)
    avg_word_count = fields.Integer(string="Avg words", readonly=True)
    new_issue_count = fields.Integer(string="New issues", readonly=True)
    resolved_issue_count = fields.Integer(
        string="Resolved issues", readonly=True)
    new_issues = fields.Text(string="New issues (detail)", readonly=True)
    resolved_issues = fields.Text(
        string="Resolved issues (detail)", readonly=True)
    new_page_count = fields.Integer(string="New pages", readonly=True)
    removed_page_count = fields.Integer(string="Removed pages", readonly=True)
    new_pages = fields.Text(string="New pages (detail)", readonly=True)
    removed_pages = fields.Text(
        string="Removed pages (detail)", readonly=True)
    comparison = fields.Text(
        compute="_compute_comparison", string="Vs previous crawl")
    # Internal JSON state used to diff against the next crawl.
    issues_snapshot = fields.Text(readonly=True)
    urls_snapshot = fields.Text(readonly=True)

    def _compute_comparison(self):
        for rec in self:
            previous = self.search([
                ("site_id", "=", rec.site_id.id),
                "|", ("date", "<", rec.date),
                "&", ("date", "=", rec.date), ("id", "<", rec.id or 0),
            ], order="date desc, id desc", limit=1)
            if not previous:
                rec.comparison = "First crawl — nothing to compare yet."
                continue
            lines = ["%-22s %12s   %12s   %s" % (
                "Metric", "Previous", "Current", "Verdict")]
            for field_name, label, lower_is_better in COMPARED_METRICS:
                prev_val = previous[field_name]
                cur_val = rec[field_name]
                if isinstance(cur_val, float):
                    prev_txt, cur_txt = ("%.2f" % prev_val), ("%.2f" % cur_val)
                else:
                    prev_txt, cur_txt = str(prev_val), str(cur_val)
                if cur_val == prev_val:
                    verdict = "="
                else:
                    improved = ((cur_val < prev_val) == lower_is_better)
                    verdict = "▲ Improved" if improved else "▼ Regressed"
                lines.append("%-22s %12s → %12s   %s" % (
                    label, prev_txt, cur_txt, verdict))
            rec.comparison = "\n".join(lines)
