# -*- coding: utf-8 -*-
"""On-page SEO audit of a URL — backed by the pure-stdlib crawl engine."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..crawler import fetch_page


class SeoAudit(models.Model):
    _name = "seo.audit"
    _description = "SEO Audit of a page"
    _order = "audit_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="URL", required=True)
    site_id = fields.Many2one(
        "seo.site", string="Site", ondelete="cascade", index=True
    )
    audit_date = fields.Datetime(string="Analyzed on", readonly=True)
    status_code = fields.Integer(string="HTTP status", readonly=True)
    final_url = fields.Char(string="Final URL", readonly=True)
    error = fields.Char(string="Crawl error", readonly=True)
    score = fields.Integer(string="Score", readonly=True,
                           help="Naive 0-100 score: 100 minus a penalty per issue.")
    title = fields.Char(string="Title", readonly=True)
    title_length = fields.Integer(string="Title length", readonly=True)
    meta_description = fields.Text(string="Meta description", readonly=True)
    meta_description_length = fields.Integer(string="Meta length", readonly=True)
    meta_robots = fields.Char(string="Meta robots", readonly=True)
    canonical = fields.Char(string="Canonical", readonly=True)
    h1 = fields.Text(string="H1", readonly=True)
    h1_count = fields.Integer(string="H1 count", readonly=True)
    h2_count = fields.Integer(string="H2 count", readonly=True)
    word_count = fields.Integer(string="Word count", readonly=True)
    internal_links = fields.Integer(string="Internal links", readonly=True)
    external_links = fields.Integer(string="External links", readonly=True)
    images = fields.Integer(string="Images", readonly=True)
    images_without_alt = fields.Integer(string="Images without alt", readonly=True)
    response_time = fields.Float(string="Response time (s)", digits=(6, 2),
                                 readonly=True)
    page_size_kb = fields.Integer(string="Page size (KB)", readonly=True)
    redirect_count = fields.Integer(string="Redirect hops", readonly=True)
    is_https = fields.Boolean(string="HTTPS", readonly=True)
    lang = fields.Char(string="Language", readonly=True)
    viewport = fields.Boolean(string="Mobile viewport", readonly=True)
    og_status = fields.Selection(
        [("complete", "Complete"), ("partial", "Partial"),
         ("missing", "Missing")],
        string="Open Graph", readonly=True)
    schema_types = fields.Char(string="Schema.org types", readonly=True)
    schema_count = fields.Integer(string="Schema blocks", readonly=True)
    hreflang_count = fields.Integer(string="Hreflang tags", readonly=True)
    mixed_content = fields.Integer(string="Mixed content", readonly=True)
    unsafe_blank_links = fields.Integer(
        string="Unsafe _blank links", readonly=True)
    text_ratio = fields.Integer(
        string="Text/HTML ratio (%)", readonly=True)
    flesch_score = fields.Integer(string="Readability", readonly=True)
    flesch_label = fields.Char(string="Readability level", readonly=True)
    top_keywords = fields.Text(string="Top keywords", readonly=True)
    link_score = fields.Integer(
        string="Link score", readonly=True,
        help="Internal PageRank of the page within the crawl (1-100).")
    issues = fields.Text(string="Detected issues", readonly=True)
    issue_count = fields.Integer(string="Issue count", readonly=True)
    issue_ids = fields.One2many(
        "seo.audit.issue", "audit_id", string="Issues")
    critical_count = fields.Integer(string="Critical", readonly=True)
    warning_count = fields.Integer(string="Warnings", readonly=True)
    info_count = fields.Integer(string="Info", readonly=True)

    def action_run_audit(self):
        for rec in self:
            rec._run_audit()
        return True

    def _run_audit(self):
        self.ensure_one()
        url = (self.name or "").strip()
        if not url:
            raise UserError("Please enter a URL to audit.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        page = fetch_page(url)
        if page["error"] and not page["status"]:
            raise UserError("Crawl failed: %s" % page["error"])
        self.write(self._vals_from_page(page))

    @api.model
    def _vals_from_page(self, page):
        """Map a crawler page dict onto seo.audit field values."""
        issues = page["issues"]
        by_severity = {"critical": 0, "warning": 0, "info": 0}
        for issue in issues:
            by_severity[issue["severity"]] += 1
        return {
            "audit_date": fields.Datetime.now(),
            "status_code": page["status"],
            "final_url": page["final_url"],
            "error": page["error"],
            "score": page["score"],
            "title": page["title"],
            "title_length": len(page["title"]),
            "meta_description": page["meta_description"],
            "meta_description_length": len(page["meta_description"]),
            "meta_robots": page["meta_robots"],
            "canonical": page["canonical"],
            "h1": "\n".join(page["h1"]),
            "h1_count": len(page["h1"]),
            "h2_count": page["h2_count"],
            "word_count": page["word_count"],
            "internal_links": page["internal_links"],
            "external_links": page["external_links"],
            "images": page["images"],
            "images_without_alt": page["images_without_alt"],
            "response_time": page["response_time"],
            "page_size_kb": page["page_size_kb"],
            "redirect_count": page["redirect_count"],
            "is_https": page["is_https"],
            "lang": page["lang"],
            "viewport": page["viewport"],
            "og_status": page["og"],
            "schema_types": ", ".join(page["schema_types"])[:256],
            "schema_count": page["schema_count"],
            "hreflang_count": len(page["hreflangs"]),
            "mixed_content": page["mixed_content"],
            "unsafe_blank_links": page["unsafe_blank_links"],
            "text_ratio": page["text_ratio"],
            "flesch_score": page["flesch_score"] or 0,
            "flesch_label": page["flesch_label"],
            "top_keywords": ", ".join(
                "%s (%d)" % (word, count)
                for word, count in page["top_keywords"]),
            "link_score": page["link_score"],
            "issues": "\n".join(
                i["message"] for i in issues) or "No issues detected",
            "issue_count": len(issues),
            "critical_count": by_severity["critical"],
            "warning_count": by_severity["warning"],
            "info_count": by_severity["info"],
            "issue_ids": [(5, 0, 0)] + [(0, 0, dict(i)) for i in issues],
        }
