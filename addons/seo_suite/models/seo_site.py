# -*- coding: utf-8 -*-
"""Multi-page site crawl — discovers URLs (sitemap + internal links) and
audits every page, then reports cross-page issues."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..crawler import analyze_site, crawl


class SeoSite(models.Model):
    _name = "seo.site"
    _description = "SEO Site (multi-page crawl)"
    _order = "id desc"

    name = fields.Char(string="Site URL", required=True,
                       help="Root URL of the site, e.g. https://example.com")
    max_pages = fields.Integer(
        string="Max pages", default=30,
        help="Upper bound of pages fetched per crawl. Keep it reasonable: "
             "pages are fetched sequentially within the current request.")
    use_sitemap = fields.Boolean(
        string="Use sitemap.xml", default=True,
        help="Seed the crawl with URLs from robots.txt / sitemap.xml.")
    follow_links = fields.Boolean(
        string="Follow internal links", default=True,
        help="Discover pages by following same-site links (BFS).")
    last_crawl = fields.Datetime(string="Last crawl", readonly=True)
    discovered_count = fields.Integer(
        string="URLs discovered", readonly=True,
        help="Unique URLs seen during the last crawl (crawled or not).")
    audit_ids = fields.One2many("seo.audit", "site_id", string="Page audits")
    issue_ids = fields.One2many(
        "seo.audit.issue", "site_id", string="Issues")
    site_issues = fields.Text(string="Site-level issues", readonly=True)
    site_issue_count = fields.Integer(string="Site issue count", readonly=True)

    page_count = fields.Integer(compute="_compute_stats", string="Pages crawled")
    error_page_count = fields.Integer(compute="_compute_stats", string="Pages in error")
    issue_count = fields.Integer(compute="_compute_stats", string="Page issues")
    critical_count = fields.Integer(compute="_compute_stats", string="Critical")
    warning_count = fields.Integer(compute="_compute_stats", string="Warnings")
    info_count = fields.Integer(compute="_compute_stats", string="Info")
    score = fields.Integer(
        compute="_compute_stats", string="Score",
        help="Average of page scores (0-100).")
    avg_response_time = fields.Float(
        compute="_compute_stats", string="Avg response time (s)",
        digits=(6, 2))
    avg_word_count = fields.Integer(
        compute="_compute_stats", string="Avg word count")

    @api.depends("audit_ids.issue_count", "audit_ids.score",
                 "audit_ids.status_code", "audit_ids.error",
                 "audit_ids.critical_count", "audit_ids.warning_count",
                 "audit_ids.info_count", "audit_ids.response_time",
                 "audit_ids.word_count")
    def _compute_stats(self):
        for rec in self:
            audits = rec.audit_ids
            rec.page_count = len(audits)
            rec.issue_count = sum(audits.mapped("issue_count"))
            rec.critical_count = sum(audits.mapped("critical_count"))
            rec.warning_count = sum(audits.mapped("warning_count"))
            rec.info_count = sum(audits.mapped("info_count"))
            rec.error_page_count = len(audits.filtered(
                lambda a: a.error or a.status_code >= 400))
            rec.score = (
                round(sum(audits.mapped("score")) / len(audits))
                if audits else 0
            )
            rec.avg_response_time = (
                sum(audits.mapped("response_time")) / len(audits)
                if audits else 0.0
            )
            rec.avg_word_count = (
                round(sum(audits.mapped("word_count")) / len(audits))
                if audits else 0
            )

    def action_crawl(self):
        self.ensure_one()
        if not (self.name or "").strip():
            raise UserError("Please enter the site URL to crawl.")
        result = crawl(
            self.name,
            max_pages=max(1, self.max_pages or 30),
            use_sitemap=self.use_sitemap,
            follow_links=self.follow_links,
        )
        pages = result["pages"]
        root = pages[0]
        if root["error"] and not root["status"]:
            raise UserError(
                "Could not reach %s: %s" % (self.name, root["error"]))

        self.audit_ids.unlink()
        Audit = self.env["seo.audit"]
        Audit.create([
            dict(Audit._vals_from_page(page), name=page["url"], site_id=self.id)
            for page in pages
        ])

        site_issues = analyze_site(pages, result.get("favicon_ok", True))
        self.write({
            "last_crawl": fields.Datetime.now(),
            "discovered_count": result["discovered"],
            "site_issues": "\n".join(site_issues) or "No site-level issues",
            "site_issue_count": len(site_issues),
        })
        return True

    def action_view_audits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Page audits",
            "res_model": "seo.audit",
            "view_mode": "list,form",
            "domain": [("site_id", "=", self.id)],
            "context": {"default_site_id": self.id},
        }

    def action_view_issues(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Issues",
            "res_model": "seo.audit.issue",
            "view_mode": "list",
            "domain": [("site_id", "=", self.id)],
            "context": {"search_default_group_category": 1},
        }

    def _report_issue_groups(self):
        """Issues grouped by category, most severe first — the skeleton of
        the action plan in the printed report."""
        self.ensure_one()
        labels = dict(
            self.env["seo.audit.issue"]._fields["category"].selection)
        groups = {}
        for issue in self.issue_ids:
            group = groups.setdefault(issue.category, {
                "category": labels.get(issue.category, issue.category),
                "count": 0, "critical": 0, "warning": 0, "info": 0,
                "pages": set(),
            })
            group["count"] += 1
            group[issue.severity] += 1
            group["pages"].add(issue.audit_id.id)
        result = []
        for group in groups.values():
            group["page_count"] = len(group.pop("pages"))
            result.append(group)
        result.sort(key=lambda g: (-g["critical"], -g["warning"], -g["count"]))
        return result
