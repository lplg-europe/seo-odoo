# -*- coding: utf-8 -*-
"""Multi-page site crawl — discovers URLs (sitemap + internal links) and
audits every page, then reports cross-page issues."""
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..crawler import analyze_site, crawl

_logger = logging.getLogger(__name__)


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
    auto_crawl_interval = fields.Integer(
        string="Auto-crawl every (days)", default=0,
        help="0 disables scheduled crawls. Otherwise the daily cron "
             "re-crawls the site every N days (and syncs Google data when "
             "a service account is configured), building the score history.")
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
    history_ids = fields.One2many(
        "seo.crawl.history", "site_id", string="Crawl history")
    history_count = fields.Integer(
        compute="_compute_history_count", string="Crawls")
    keyword_ids = fields.One2many(
        "seo.keyword", "site_id", string="Tracked keywords")
    keyword_count = fields.Integer(
        compute="_compute_keyword_count", string="Keywords")
    dfs_location = fields.Char(
        string="SERP location", default="Belgium",
        help="DataForSEO location_name for volumes and live SERPs, "
             'e.g. "Belgium" or "Paris,Ile-de-France,France".')
    dfs_language = fields.Char(
        string="SERP language", default="fr",
        help="DataForSEO language_code, e.g. fr, nl, en.")
    bl_rank = fields.Integer(
        string="Domain rank", readonly=True,
        help="DataForSEO backlink rank of the domain (0-1000).")
    bl_backlinks = fields.Integer(string="Backlinks", readonly=True)
    bl_referring_domains = fields.Integer(
        string="Referring domains", readonly=True)
    bl_referring_pages = fields.Integer(
        string="Referring pages", readonly=True)
    bl_broken_backlinks = fields.Integer(
        string="Broken backlinks", readonly=True)
    bl_dofollow = fields.Integer(string="Dofollow links", readonly=True)
    bl_spam_score = fields.Integer(
        string="Spam score", readonly=True,
        help="Average spam score of the backlink profile (0-100, "
             "lower is better).")
    bl_first_seen = fields.Char(string="First backlink seen", readonly=True)
    bl_date = fields.Datetime(string="Backlinks fetched on", readonly=True)
    brand_name = fields.Char(
        string="Brand name",
        help="The brand to look for in AI answers, e.g. "
             '"Les Trois Chênes". Used by AI Visibility.')
    ai_competitors = fields.Char(
        string="Competitor brands",
        help="Comma-separated competitor brand names for the AI share "
             "of voice comparison.")
    ai_prompt_ids = fields.One2many(
        "seo.ai.prompt", "site_id", string="AI prompts")
    ai_mentions_chatgpt = fields.Integer(
        string="ChatGPT mention prompts", readonly=True,
        help="Prompts where ChatGPT mentions or cites this domain "
             "(DataForSEO LLM Mentions, US/en dataset).")
    ai_mentions_google = fields.Integer(
        string="AI Overview mention prompts", readonly=True)
    ai_mentions_detail = fields.Text(
        string="AI mention prompts", readonly=True)
    ai_share_of_voice = fields.Text(
        string="AI share of voice", readonly=True)
    ai_visibility_date = fields.Datetime(
        string="AI visibility scanned on", readonly=True)
    ai_visibility_pct = fields.Integer(
        compute="_compute_ai_visibility", string="AI visibility (%)",
        help="Share of prompt-explorer results where the brand is "
             "mentioned.")
    ai_cited_pct = fields.Integer(
        compute="_compute_ai_visibility", string="AI citations (%)")
    report_frequency = fields.Selection(
        [("none", "Disabled"), ("weekly", "Weekly"),
         ("monthly", "Monthly")],
        string="Client report", default="none", required=True,
        help="This Odoo instance emails the audit report (PDF + summary) "
             "for this site on schedule — nothing is sent through any "
             "third-party service.")
    report_email = fields.Char(
        string="Report recipients",
        help="Comma-separated email addresses (e.g. the client).")
    report_last_sent = fields.Datetime(
        string="Report last sent", readonly=True)

    @api.depends("ai_prompt_ids.result_ids.brand_mentioned",
                 "ai_prompt_ids.result_ids.domain_cited")
    def _compute_ai_visibility(self):
        for rec in self:
            results = rec.ai_prompt_ids.mapped("result_ids")
            count = len(results)
            rec.ai_visibility_pct = (
                round(100 * len(results.filtered("brand_mentioned")) / count)
                if count else 0)
            rec.ai_cited_pct = (
                round(100 * len(results.filtered("domain_cited")) / count)
                if count else 0)

    @api.depends("history_ids")
    def _compute_history_count(self):
        for rec in self:
            rec.history_count = len(rec.history_ids)

    @api.depends("keyword_ids")
    def _compute_keyword_count(self):
        for rec in self:
            rec.keyword_count = len(rec.keyword_ids)

    def _bare_host(self):
        self.ensure_one()
        host = urlsplit(
            self.name if "://" in (self.name or "")
            else "https://" + (self.name or "")).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    def _dataforseo_credentials(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        login = get_param("seo_suite.dataforseo_login")
        password = get_param("seo_suite.dataforseo_password")
        if not login or not password:
            raise UserError(
                "DataForSEO is not configured. Add the API login/password "
                "in SEO → Configuration → Settings (paid service, "
                "https://dataforseo.com).")
        return login, password

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
    https_pct = fields.Integer(
        compute="_compute_stats", string="HTTPS (%)")
    mobile_pct = fields.Integer(
        compute="_compute_stats", string="Mobile-friendly (%)",
        help="Pages with a viewport meta tag.")
    schema_pct = fields.Integer(
        compute="_compute_stats", string="Structured data (%)",
        help="Pages with at least one schema.org block.")
    indexable_pct = fields.Integer(
        compute="_compute_stats", string="Indexable (%)",
        help="Pages returning 200 without a noindex directive.")

    @api.depends("audit_ids.issue_count", "audit_ids.score",
                 "audit_ids.status_code", "audit_ids.error",
                 "audit_ids.critical_count", "audit_ids.warning_count",
                 "audit_ids.info_count", "audit_ids.response_time",
                 "audit_ids.word_count", "audit_ids.is_https",
                 "audit_ids.viewport", "audit_ids.schema_count",
                 "audit_ids.meta_robots")
    def _compute_stats(self):
        for rec in self:
            audits = rec.audit_ids
            count = len(audits)
            rec.page_count = count
            rec.issue_count = sum(audits.mapped("issue_count"))
            rec.critical_count = sum(audits.mapped("critical_count"))
            rec.warning_count = sum(audits.mapped("warning_count"))
            rec.info_count = sum(audits.mapped("info_count"))
            rec.error_page_count = len(audits.filtered(
                lambda a: a.error or a.status_code >= 400))
            rec.score = (
                round(sum(audits.mapped("score")) / count) if count else 0)
            rec.avg_response_time = (
                sum(audits.mapped("response_time")) / count if count else 0.0)
            rec.avg_word_count = (
                round(sum(audits.mapped("word_count")) / count)
                if count else 0)

            def pct(predicate):
                return round(
                    100 * len(audits.filtered(predicate)) / count
                ) if count else 0

            rec.https_pct = pct(lambda a: a.is_https)
            rec.mobile_pct = pct(lambda a: a.viewport)
            rec.schema_pct = pct(lambda a: a.schema_count > 0)
            rec.indexable_pct = pct(
                lambda a: a.status_code == 200 and not a.error
                and "noindex" not in (a.meta_robots or "").lower())

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

        site_issues = analyze_site(pages, result)
        self.write({
            "last_crawl": fields.Datetime.now(),
            "discovered_count": result["discovered"],
            "checked_link_count": result.get("checked_links", 0),
            "broken_link_count": len(result.get("broken_links") or []),
            "site_issues": "\n".join(site_issues) or "No site-level issues",
            "site_issue_count": len(site_issues),
        })
        self._create_history_snapshot()
        return True

    def _issue_keys(self):
        """Stable identifiers of the current issues, for cross-crawl diffs.

        Numbers are normalized ("Thin content (163 words)" -> "(N words)")
        so a changed count does not read as a new issue.
        """
        self.ensure_one()
        return {
            "%s | %s | %s" % (
                issue.url, issue.category, re.sub(r"\d+", "N", issue.message))
            for issue in self.issue_ids
        }

    def _create_history_snapshot(self):
        """Snapshot the crawl and diff it against the previous snapshot."""
        self.ensure_one()
        History = self.env["seo.crawl.history"]
        previous = History.search(
            [("site_id", "=", self.id)], order="date desc, id desc", limit=1)
        current_issues = self._issue_keys()
        current_urls = set(self.audit_ids.mapped("name"))
        new_issues = resolved_issues = []
        new_pages = removed_pages = []
        if previous:
            try:
                prev_issues = set(json.loads(previous.issues_snapshot or "[]"))
                prev_urls = set(json.loads(previous.urls_snapshot or "[]"))
            except ValueError:
                prev_issues, prev_urls = set(), set()
            new_issues = sorted(current_issues - prev_issues)
            resolved_issues = sorted(prev_issues - current_issues)
            new_pages = sorted(current_urls - prev_urls)
            removed_pages = sorted(prev_urls - current_urls)
        History.create({
            "site_id": self.id,
            "score": self.score,
            "score_delta": self.score - previous.score if previous else 0,
            "page_count": self.page_count,
            "discovered_count": self.discovered_count,
            "error_page_count": self.error_page_count,
            "issue_count": self.issue_count,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "site_issue_count": self.site_issue_count,
            "broken_link_count": self.broken_link_count,
            "avg_response_time": self.avg_response_time,
            "avg_word_count": self.avg_word_count,
            "new_issue_count": len(new_issues),
            "resolved_issue_count": len(resolved_issues),
            "new_issues": "\n".join(new_issues),
            "resolved_issues": "\n".join(resolved_issues),
            "new_page_count": len(new_pages),
            "removed_page_count": len(removed_pages),
            "new_pages": "\n".join(new_pages),
            "removed_pages": "\n".join(removed_pages),
            "issues_snapshot": json.dumps(sorted(current_issues)),
            "urls_snapshot": json.dumps(sorted(current_urls)),
        })

    @api.model
    def _cron_crawl(self):
        """Daily cron: re-crawl sites whose interval has elapsed."""
        now = fields.Datetime.now()
        has_google = bool(self.env["ir.config_parameter"].sudo().get_param(
            "seo_suite.google_service_account"))
        for site in self.search([("auto_crawl_interval", ">", 0)]):
            due = (not site.last_crawl or site.last_crawl
                   + timedelta(days=site.auto_crawl_interval) <= now)
            if not due:
                continue
            try:
                site.action_crawl()
                if has_google:
                    try:
                        site.action_sync_google()
                    except Exception:  # noqa: BLE001 — Google is best-effort
                        _logger.exception(
                            "Scheduled Google sync failed for %s", site.name)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 — never break the whole batch
                _logger.exception("Scheduled crawl failed for %s", site.name)
                self.env.cr.rollback()

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
            for row in query_rows[:50]
        ]
        self._sync_keywords(token, prop, query_rows)
        self.write({
            "google_last_sync": fields.Datetime.now(),
            "gsc_top_queries": "\n".join(top) or "No query data yet",
        })
        return True

    def _sync_keywords(self, token, prop, query_rows):
        """Refresh tracked keywords from GSC and add a daily history point."""
        from ..google_api import GoogleApiError, gsc_search_analytics
        from .seo_keyword import POSITION_NOT_FOUND
        if not self.keyword_ids:
            return
        by_query = {row["key"].lower(): row for row in query_rows}
        try:
            page_rows = gsc_search_analytics(
                token, prop, dimension=["query", "page"], row_limit=1000)
        except GoogleApiError:
            page_rows = []
        best_page = {}
        for row in page_rows:
            query = row["keys"][0].lower()
            if query not in best_page:  # rows come sorted by clicks desc
                best_page[query] = row["keys"][1]
        History = self.env["seo.keyword.history"]
        today_start = fields.Datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
        for keyword in self.keyword_ids:
            row = by_query.get(keyword.name.strip().lower())
            vals = {
                "position": row["position"] if row else POSITION_NOT_FOUND,
                "clicks": row["clicks"] if row else 0,
                "impressions": row["impressions"] if row else 0,
                "ctr": row["ctr"] if row else 0.0,
                "best_page": best_page.get(
                    keyword.name.strip().lower(), ""),
                "last_sync": fields.Datetime.now(),
            }
            keyword.write(vals)
            point_vals = {
                "keyword_id": keyword.id,
                "position": vals["position"],
                "clicks": vals["clicks"],
                "impressions": vals["impressions"],
                "ctr": vals["ctr"],
                "page": vals["best_page"],
            }
            today_point = History.search([
                ("keyword_id", "=", keyword.id),
                ("date", ">=", today_start)], limit=1)
            if today_point:
                today_point.write(point_vals)
            else:
                History.create(point_vals)

    def action_fetch_volumes(self):
        """Search volumes / CPC / competition for all tracked keywords
        (DataForSEO, paid)."""
        self.ensure_one()
        if not self.keyword_ids:
            raise UserError("Add keywords to track first (Keywords tab).")
        login, password = self._dataforseo_credentials()
        from ..dataforseo import DataForSeoError, search_volume
        try:
            volumes, cost = search_volume(
                login, password, self.keyword_ids.mapped("name"),
                location=self.dfs_location or "Belgium",
                language=self.dfs_language or "fr")
        except DataForSeoError as e:
            raise UserError(str(e))
        for keyword in self.keyword_ids:
            data = volumes.get(keyword.name.strip().lower())
            if data:
                keyword.write(data)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Volumes updated",
                "message": "%d keyword(s) enriched — cost $%.4f" % (
                    len(self.keyword_ids), cost),
                "type": "success",
            },
        }

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

    AI_BULK_BATCH = 8  # pages per click, to stay within the request timeout

    def action_ai_suggest_missing_metas(self):
        """AI meta suggestions for every crawled page missing one (batched)."""
        self.ensure_one()
        candidates = self.audit_ids.filtered(
            lambda a: a.status_code == 200 and not a.error
            and not a.meta_description and not a.ai_meta_description)
        if not candidates:
            raise UserError(
                "No page needs a meta description suggestion (all pages "
                "have one, or already have an AI suggestion).")
        batch = candidates[:self.AI_BULK_BATCH]
        for audit in batch:
            audit.action_ai_suggest_meta()
        remaining = len(candidates) - len(batch)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "AI suggestions generated",
                "message": "%d page(s) done%s" % (
                    len(batch),
                    " — %d remaining, click again" % remaining
                    if remaining else ", all pages covered"),
                "type": "success" if not remaining else "warning",
                "sticky": bool(remaining),
            },
        }

    def action_ai_visibility_scan(self):
        """LLM Mentions scan: prompts citing this domain in ChatGPT and
        Google AI Overview, plus brand share of voice vs competitors."""
        self.ensure_one()
        login, password = self._dataforseo_credentials()
        from ..dataforseo import (
            DataForSeoError, llm_mentions_search, llm_share_of_voice)
        host = self._bare_host()
        total_cost = 0.0
        detail = []
        counts = {}
        try:
            for platform, label in (("chat_gpt", "ChatGPT"),
                                    ("google", "Google AI Overview")):
                rows, cost = llm_mentions_search(
                    login, password, host, platform=platform)
                total_cost += cost
                counts[platform] = len(rows)
                detail.append("=== %s — %d prompt(s) mention/cite %s ==="
                              % (label, len(rows), host))
                for row in rows[:20]:
                    detail.append("- %s (AI search volume: %d)"
                                  % (row["question"], row["volume"]))
        except DataForSeoError as e:
            raise UserError(str(e))

        sov_lines = []
        brands = [b.strip() for b in (self.ai_competitors or "").split(",")
                  if b.strip()]
        if self.brand_name and brands:
            try:
                sov, cost = llm_share_of_voice(
                    login, password, [self.brand_name.strip()] + brands)
                total_cost += cost
                total = sum(r["mentions"] for r in sov) or 1
                sov_lines = [
                    "%-40s %6d mentions  (%d%%)" % (
                        r["brand"][:40], r["mentions"],
                        round(100 * r["mentions"] / total))
                    for r in sov]
            except DataForSeoError as e:
                sov_lines = ["Share of voice failed: %s" % e]

        self.write({
            "ai_mentions_chatgpt": counts.get("chat_gpt", 0),
            "ai_mentions_google": counts.get("google", 0),
            "ai_mentions_detail": "\n".join(detail) or "No mentions found",
            "ai_share_of_voice": "\n".join(sov_lines),
            "ai_visibility_date": fields.Datetime.now(),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "AI visibility scanned",
                "message": "ChatGPT: %d prompt(s), AI Overview: %d — "
                           "cost $%.4f" % (
                               counts.get("chat_gpt", 0),
                               counts.get("google", 0), total_cost),
                "type": "success",
            },
        }

    def action_fetch_backlinks(self):
        """Backlink profile overview via DataForSEO (paid, BYO)."""
        self.ensure_one()
        login, password = self._dataforseo_credentials()
        from ..dataforseo import DataForSeoError, backlinks_summary
        try:
            data, cost = backlinks_summary(
                login, password, self._bare_host())
        except DataForSeoError as e:
            raise UserError(str(e))
        self.write({
            "bl_rank": data["rank"],
            "bl_backlinks": data["backlinks"],
            "bl_referring_domains": data["referring_domains"],
            "bl_referring_pages": data["referring_pages"],
            "bl_broken_backlinks": data["broken_backlinks"],
            "bl_dofollow": data["dofollow"],
            "bl_spam_score": data["spam_score"],
            "bl_first_seen": data["first_seen"],
            "bl_date": fields.Datetime.now(),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Backlinks fetched",
                "message": "%d backlinks from %d referring domains — "
                           "cost $%.4f" % (
                               data["backlinks"],
                               data["referring_domains"], cost),
                "type": "success",
            },
        }

    def _analytics_summary_html(self):
        """Optional traffic block when the web_analytics module is
        installed and a tracked site matches this host (soft dependency —
        no hard module coupling)."""
        self.ensure_one()
        if "web.analytics.site" not in self.env:
            return ""
        host = self._bare_host()
        candidates = self.env["web.analytics.site"].search([])
        match = candidates.filtered(
            lambda s: host and (
                host in (s.allowed_hosts or "").lower()
                or host in (s.name or "").lower()))[:1]
        if not match:
            return ""
        return (
            "<h3>Traffic (30 days)</h3>"
            "<table cellpadding='4'>"
            "<tr><td>Visitors</td><td><b>%d</b></td>"
            "<td>Pageviews</td><td><b>%d</b></td></tr>"
            "<tr><td>Sessions</td><td><b>%d</b></td>"
            "<td>Bounce rate</td><td><b>%d%%</b></td></tr>"
            "</table>" % (match.visitors_30d, match.pageviews_30d,
                          match.sessions_30d, match.bounce_rate_30d))

    def _report_body_html(self):
        self.ensure_one()
        last = self.history_ids[:1]
        trend = ""
        if last and len(self.history_ids) > 1:
            trend = (" (%+d vs previous crawl — %d issue(s) resolved, "
                     "%d new)" % (last.score_delta,
                                  last.resolved_issue_count,
                                  last.new_issue_count))
        keywords = self.keyword_ids.filtered(
            lambda k: k.position and k.position < 101).sorted("position")[:5]
        keyword_rows = "".join(
            "<tr><td>%s</td><td align='right'>%.1f</td>"
            "<td align='right'>%+.1f</td><td align='right'>%d</td></tr>"
            % (k.name, k.position, k.position_delta, k.clicks)
            for k in keywords)
        keywords_html = (
            "<h3>Tracked keywords</h3><table cellpadding='4'>"
            "<tr><th align='left'>Keyword</th><th>Position</th>"
            "<th>Δ places</th><th>Clicks</th></tr>%s</table>"
            % keyword_rows) if keyword_rows else ""
        return (
            "<h2>SEO report — %(site)s</h2>"
            "<p>Overall score: <b>%(score)d/100</b>%(trend)s<br/>"
            "Last crawl: %(crawl)s — %(pages)d pages, %(issues)d issues "
            "(%(critical)d critical), %(errors)d pages in error, "
            "%(broken)d broken links.<br/>"
            "Indexable: %(indexable)d%% · HTTPS: %(https)d%% · "
            "Mobile-friendly: %(mobile)d%%</p>"
            "%(keywords)s%(analytics)s"
            "<p style='color:#888'>Full details in the attached report. "
            "Sent automatically by SEO Suite.</p>" % {
                "site": self.name, "score": self.score, "trend": trend,
                "crawl": self.last_crawl or "-",
                "pages": self.page_count, "issues": self.issue_count,
                "critical": self.critical_count,
                "errors": self.error_page_count,
                "broken": self.broken_link_count,
                "indexable": self.indexable_pct, "https": self.https_pct,
                "mobile": self.mobile_pct,
                "keywords": keywords_html,
                "analytics": self._analytics_summary_html(),
            })

    def action_send_report(self):
        """Email the audit report (PDF attached) to the configured
        recipients — sent by this Odoo instance, per site."""
        self.ensure_one()
        if not self.report_email:
            raise UserError(
                "Set the report recipients on the site first.")
        if not self.last_crawl:
            raise UserError("Crawl the site at least once first.")
        # paying clients get the complete report (recommendations included)
        report = self.env.ref("seo_suite.action_report_seo_site_full")
        attachments = []
        try:
            content, report_type = self.env["ir.actions.report"]\
                ._render_qweb_pdf(report, res_ids=self.ids)
        except Exception:  # noqa: BLE001 — e.g. wkhtmltopdf missing
            content, report_type = self.env["ir.actions.report"]\
                ._render_qweb_html(report, res_ids=self.ids)
        extension = "pdf" if report_type == "pdf" else "html"
        attachment = self.env["ir.attachment"].create({
            "name": "seo-report-%s.%s" % (
                fields.Date.to_string(fields.Date.today()), extension),
            "raw": content,
            "res_model": self._name,
            "res_id": self.id,
        })
        attachments.append(attachment.id)
        self.env["mail.mail"].sudo().create({
            "subject": "SEO report — %s — score %d/100" % (
                self.name, self.score),
            "email_to": self.report_email,
            "body_html": self._report_body_html(),
            "attachment_ids": [(6, 0, attachments)],
        }).send()
        self.report_last_sent = fields.Datetime.now()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Report sent",
                "message": "Emailed to %s (%s attached)." % (
                    self.report_email, extension.upper()),
                "type": "success",
            },
        }

    @api.model
    def _cron_send_reports(self):
        """Daily cron: email due weekly/monthly client reports."""
        now = fields.Datetime.now()
        deltas = {"weekly": timedelta(days=7),
                  "monthly": timedelta(days=30)}
        sites = self.search([("report_frequency", "in", list(deltas)),
                             ("report_email", "!=", False)])
        for site in sites:
            due = (not site.report_last_sent
                   or site.report_last_sent
                   + deltas[site.report_frequency] <= now)
            if not due or not site.last_crawl:
                continue
            try:
                site.action_send_report()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 — never break the batch
                _logger.exception(
                    "Scheduled report failed for %s", site.name)
                self.env.cr.rollback()

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

    def action_view_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Crawl history",
            "res_model": "seo.crawl.history",
            "view_mode": "graph,list,form",
            "domain": [("site_id", "=", self.id)],
            "context": {"default_site_id": self.id},
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

    _SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}

    def _report_path(self, url):
        """Short path of a page URL for the printed report — the domain is
        already in the report header, repeating it 50 times is noise."""
        base = (self.name or "").rstrip("/")
        if base and url.startswith(base):
            return url[len(base):] or "/"
        return url

    def _report_top_issues(self, limit=12):
        """Recurring issues across the whole site, worst first — the
        'fix these first' list of the printed report. Issues whose message
        only differs by a number ("Low text/HTML ratio (7%)" vs "(6%)")
        are counted together."""
        self.ensure_one()
        groups = {}
        for issue in self.issue_ids:
            key = re.sub(r"[\d.,]+", "#", issue.message or "")
            group = groups.setdefault(key, {
                "messages": set(), "severity": issue.severity,
                "how_to_fix": issue.how_to_fix, "pages": set()})
            group["messages"].add(issue.message)
            group["pages"].add(issue.audit_id.id)
            if self._SEV_ORDER[issue.severity] < \
                    self._SEV_ORDER[group["severity"]]:
                group["severity"] = issue.severity
        result = []
        for group in groups.values():
            messages = group.pop("messages")
            label = next(iter(messages))
            if len(messages) > 1:
                # the numbers vary per page -> strip the specifics
                label = re.sub(r"\s*\([^)]*\)", "", label)
                label = re.sub(r"^\d+\s*", "", label).strip()
                label = label[:1].upper() + label[1:]
            group["message"] = label
            group["page_count"] = len(group.pop("pages"))
            result.append(group)
        result.sort(key=lambda g: (
            self._SEV_ORDER[g["severity"]], -g["page_count"]))
        return result[:limit]

    def _report_page_rows(self, max_issues=3):
        """Page-detail rows for the printed report: only pages that need
        work, worst first, at most `max_issues` issue lines each — the full
        list lives in the app, the PDF is a summary."""
        self.ensure_one()
        rows = []
        for audit in self.audit_ids.sorted(key=lambda a: (a.score, a.name)):
            if not audit.issue_ids and not audit.error \
                    and audit.status_code < 400:
                continue
            issues = sorted(audit.issue_ids,
                            key=lambda i: self._SEV_ORDER[i.severity])
            rows.append({
                "path": self._report_path(audit.name),
                "status": audit.status_code,
                "score": audit.score,
                "error": audit.error,
                "issues": [{"message": i.message, "severity": i.severity}
                           for i in issues[:max_issues]],
                "more": max(0, len(issues) - max_issues),
            })
        return rows

    def _report_clean_pages(self):
        """Paths of the audited pages with nothing to report — one
        reassuring green line instead of empty table rows."""
        self.ensure_one()
        return [self._report_path(a.name) for a in self.audit_ids.sorted("name")
                if not a.issue_ids and not a.error and a.status_code < 400]

    def _report_keyword_buckets(self):
        """Tracked keywords grouped by opportunity level for the complete
        report — where to push first."""
        self.ensure_one()
        buckets = [
            ("Almost on the podium (positions 4-10)",
             "Quick wins: strengthen internal links to the target page and "
             "refresh its content — a small push can reach the top 3.", 4, 10),
            ("Page 2 (positions 11-20)",
             "One good optimization away from page 1: rewrite title/meta, "
             "deepen the content, add internal links.", 11, 20),
            ("Visible (positions 21-50)",
             "Longer-term work: dedicated content and backlinks.", 21, 50),
        ]
        result = []
        for label, advice, lo, hi in buckets:
            keywords = self.keyword_ids.filtered(
                lambda k: k.position and lo <= k.position <= hi
            ).sorted("position")
            if keywords:
                result.append({"label": label, "advice": advice, "keywords": [{
                    "name": k.name, "position": k.position,
                    "volume": k.volume, "clicks": k.clicks,
                    "best_page": self._report_path(k.best_page)
                    if k.best_page else "",
                } for k in keywords]})
        return result

    def _report_ai_meta_rows(self, limit=15):
        """Stored AI title/meta suggestions not applied yet — the
        ready-to-use deliverable of the complete report."""
        self.ensure_one()
        rows = []
        for audit in self.audit_ids.sorted(key=lambda a: (a.score, a.name)):
            if not (audit.ai_title or audit.ai_meta_description):
                continue
            rows.append({
                "path": self._report_path(audit.name),
                "title": audit.ai_title or "",
                "meta": audit.ai_meta_description or "",
            })
            if len(rows) >= limit:
                break
        return rows
