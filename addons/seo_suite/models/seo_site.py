# -*- coding: utf-8 -*-
"""Multi-page site crawl — discovers URLs (sitemap + internal links) and
audits every page, then reports cross-page issues."""
import json
from urllib.parse import urlsplit

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
    check_links = fields.Boolean(
        string="Check remaining links", default=False,
        help="After the crawl, HEAD-check the discovered-but-not-crawled "
             "URLs to surface broken internal links (slower).")
    last_crawl = fields.Datetime(string="Last crawl", readonly=True)
    discovered_count = fields.Integer(
        string="URLs discovered", readonly=True,
        help="Unique URLs seen during the last crawl (crawled or not).")
    checked_link_count = fields.Integer(
        string="Links checked", readonly=True)
    broken_link_count = fields.Integer(
        string="Broken links", readonly=True,
        help="Broken internal links found beyond the crawled pages.")
    gsc_property = fields.Char(
        string="Search Console property",
        help='Property name in Search Console: "sc-domain:example.com" '
             '(domain property) or "https://www.example.com/" (URL prefix). '
             "Leave empty to auto-detect on first sync.")
    ga4_property_id = fields.Char(
        string="GA4 property ID",
        help="Numeric GA4 property ID (Admin → Property settings), "
             "e.g. 123456789. Leave empty to skip Analytics.")
    google_last_sync = fields.Datetime(
        string="Last Google sync", readonly=True)
    gsc_top_queries = fields.Text(
        string="Top search queries", readonly=True)
    indexed_page_count = fields.Integer(
        compute="_compute_index_stats", string="Indexed pages")
    not_indexed_page_count = fields.Integer(
        compute="_compute_index_stats", string="Not indexed")

    @api.depends("audit_ids.index_verdict")
    def _compute_index_stats(self):
        for rec in self:
            inspected = rec.audit_ids.filtered(lambda a: a.index_verdict)
            rec.indexed_page_count = len(inspected.filtered(
                lambda a: a.index_verdict == "PASS"))
            rec.not_indexed_page_count = len(inspected) - rec.indexed_page_count
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
            check_links=self.check_links,
        )
        pages = result["pages"]
        root = pages[0]
        if root["error"] and not root["status"]:
            raise UserError(
                "Could not reach %s: %s" % (self.name, root["error"]))

        # Upsert by URL so Google data (GSC/GA/PSI) survives re-crawls.
        Audit = self.env["seo.audit"]
        existing = {audit.name: audit for audit in self.audit_ids}
        crawled_urls = set()
        to_create = []
        for page in pages:
            vals = Audit._vals_from_page(page)
            crawled_urls.add(page["url"])
            audit = existing.get(page["url"])
            if audit:
                audit.write(vals)
            else:
                to_create.append(
                    dict(vals, name=page["url"], site_id=self.id))
        if to_create:
            Audit.create(to_create)
        self.audit_ids.filtered(
            lambda a: a.name not in crawled_urls).unlink()

        site_issues = analyze_site(
            pages, result.get("favicon_ok", True),
            broken_links=result.get("broken_links"),
            referrers=result.get("referrers"),
        )
        self.write({
            "last_crawl": fields.Datetime.now(),
            "discovered_count": result["discovered"],
            "checked_link_count": result.get("checked_links", 0),
            "broken_link_count": len(result.get("broken_links") or []),
            "site_issues": "\n".join(site_issues) or "No site-level issues",
            "site_issue_count": len(site_issues),
        })
        return True

    def _google_token(self, scopes):
        """Access token from the configured service account, or UserError."""
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "seo_suite.google_service_account")
        if not raw:
            raise UserError(
                "No Google service account configured. Paste the JSON key "
                "in SEO → Configuration → Settings (see the help there).")
        try:
            info = json.loads(raw)
        except ValueError:
            raise UserError(
                "The configured Google service account is not valid JSON. "
                "Paste the full key file downloaded from Google Cloud.")
        from ..google_api import GoogleApiError, get_access_token
        try:
            return get_access_token(info, scopes), info.get("client_email", "")
        except GoogleApiError as e:
            raise UserError(str(e))

    def _resolve_gsc_property(self, token, email):
        """Configured property, or auto-match from the accessible list."""
        from ..google_api import GoogleApiError, gsc_list_sites
        if self.gsc_property:
            return self.gsc_property
        host = urlsplit(
            self.name if "://" in self.name else "https://" + self.name
        ).netloc.lower()
        bare = host[4:] if host.startswith("www.") else host
        try:
            sites = gsc_list_sites(token)
        except GoogleApiError as e:
            raise UserError(str(e))
        match = ""
        for site_url, _perm in sites:
            if site_url == "sc-domain:" + bare:
                match = site_url
                break
            site_host = urlsplit(site_url).netloc.lower()
            if site_host and site_host in (host, "www." + bare, bare):
                match = match or site_url
        if not match:
            raise UserError(
                "No Search Console property matches %s.\n\nProperties this "
                "service account can read: %s\n\nAdd %s as a user of the "
                "property in Search Console, or fill in the property name "
                "on the site form." % (
                    self.name,
                    ", ".join(s for s, _ in sites) or "(none)",
                    email or "the service account"))
        self.gsc_property = match
        return match

    def action_sync_google(self):
        """Pull Search Console (per page + top queries) and GA4 metrics."""
        self.ensure_one()
        from ..google_api import (
            SCOPE_GA, SCOPE_GSC, GoogleApiError, ga4_run_report,
            gsc_search_analytics)
        token, email = self._google_token([SCOPE_GSC, SCOPE_GA])
        prop = self._resolve_gsc_property(token, email)

        def path_of(url):
            return urlsplit(url).path or "/"

        try:
            page_rows = gsc_search_analytics(token, prop, dimension="page")
            query_rows = gsc_search_analytics(
                token, prop, dimension="query", row_limit=50)
        except GoogleApiError as e:
            raise UserError(str(e))
        by_path = {path_of(row["key"]): row for row in page_rows}
        ga_by_path = {}
        if self.ga4_property_id:
            try:
                ga_by_path = ga4_run_report(
                    token, self.ga4_property_id.strip())
            except GoogleApiError as e:
                raise UserError(
                    "Search Console synced, but GA4 failed: %s" % e)
        for audit in self.audit_ids:
            path = path_of(audit.final_url or audit.name)
            row = by_path.get(path)
            ga = ga_by_path.get(path)
            vals = {
                "gsc_clicks": row["clicks"] if row else 0,
                "gsc_impressions": row["impressions"] if row else 0,
                "gsc_ctr": row["ctr"] if row else 0.0,
                "gsc_position": row["position"] if row else 0.0,
            }
            if ga_by_path:
                vals.update({
                    "ga_views": ga["views"] if ga else 0,
                    "ga_sessions": ga["sessions"] if ga else 0,
                    "ga_users": ga["users"] if ga else 0,
                    "ga_engagement": ga["engagement_rate"] if ga else 0.0,
                })
            audit.write(vals)
        top = [
            "%-50s %6d clicks %8d impr.  CTR %5.1f%%  pos %5.1f" % (
                row["key"][:50], row["clicks"], row["impressions"],
                row["ctr"], row["position"])
            for row in query_rows
        ]
        self.write({
            "google_last_sync": fields.Datetime.now(),
            "gsc_top_queries": "\n".join(top) or "No query data yet",
        })
        return True

    def action_check_indexation(self):
        """Google URL Inspection for every crawled page (quota-limited)."""
        self.ensure_one()
        from ..google_api import (
            SCOPE_GSC, GoogleApiError, gsc_inspect_url)
        token, email = self._google_token([SCOPE_GSC])
        prop = self._resolve_gsc_property(token, email)
        audits = self.audit_ids.filtered(lambda a: a.audit_date)[:50]
        if not audits:
            raise UserError("Crawl the site first.")
        done = 0
        quota_message = ""
        for audit in audits:
            try:
                result = gsc_inspect_url(
                    token, prop, audit.final_url or audit.name)
            except GoogleApiError as e:
                if "429" in str(e) and done:
                    # Stop without raising so the pages already inspected
                    # keep their results (a raise would roll them back).
                    quota_message = str(e)
                    break
                raise UserError(str(e))
            audit.write({
                "index_verdict": result["verdict"],
                "index_state": result["coverage_state"],
                "google_canonical": result["google_canonical"],
                "google_last_crawl": (
                    result["last_crawl"].replace("T", " ").rstrip("Z")),
            })
            done += 1
        if quota_message:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Indexation partially checked",
                    "message": "Quota reached after %d page(s): %s"
                               % (done, quota_message),
                    "type": "warning",
                    "sticky": True,
                },
            }
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
