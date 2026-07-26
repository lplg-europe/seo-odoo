# -*- coding: utf-8 -*-
"""One snapshot per crawl — powers the score trend and the crawl diff
(new/resolved issues, added/removed pages) between two runs."""
from odoo import fields, models


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
    # Internal JSON state used to diff against the next crawl.
    issues_snapshot = fields.Text(readonly=True)
    urls_snapshot = fields.Text(readonly=True)
