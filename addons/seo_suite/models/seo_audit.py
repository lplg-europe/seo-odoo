# -*- coding: utf-8 -*-
"""On-page SEO audit of a URL — backed by the pure-stdlib crawl engine."""
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..crawler import fetch_page, pagespeed


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
    headings_outline = fields.Text(
        string="Headings structure", readonly=True,
        help="Ordered H1-H6 outline of the page.")
    word_count = fields.Integer(string="Word count", readonly=True)
    reading_time = fields.Integer(
        string="Reading time (min)", readonly=True,
        help="Word count at 250 words per minute.")
    redirect_chain = fields.Char(string="Redirect chain", readonly=True)
    google_preview = fields.Html(
        string="Google preview", compute="_compute_google_preview",
        sanitize=False)
    internal_links = fields.Integer(string="Internal links", readonly=True)
    inbound_links = fields.Integer(
        string="Inbound internal links", readonly=True,
        help="How many other crawled pages link to this one — the internal "
             "vote of confidence Google reads as importance.")
    outlinks = fields.Text(
        string="Links to", readonly=True,
        help="Internal pages this one links to (one URL per line).")
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
    click_depth = fields.Integer(
        string="Click depth", readonly=True,
        help="Clicks from the homepage via internal links "
             "(0 = homepage, -1 = not reachable by links).")
    x_robots_tag = fields.Char(string="X-Robots-Tag", readonly=True)
    psi_date = fields.Datetime(string="PageSpeed run on", readonly=True)
    psi_perf_mobile = fields.Integer(string="Perf (mobile)", readonly=True)
    psi_seo_mobile = fields.Integer(string="SEO (mobile)", readonly=True)
    psi_a11y_mobile = fields.Integer(
        string="Accessibility (mobile)", readonly=True)
    psi_bp_mobile = fields.Integer(
        string="Best practices (mobile)", readonly=True)
    psi_perf_desktop = fields.Integer(string="Perf (desktop)", readonly=True)
    psi_seo_desktop = fields.Integer(string="SEO (desktop)", readonly=True)
    psi_a11y_desktop = fields.Integer(
        string="Accessibility (desktop)", readonly=True)
    psi_bp_desktop = fields.Integer(
        string="Best practices (desktop)", readonly=True)
    psi_lcp = fields.Char(string="LCP (mobile)", readonly=True)
    psi_cls = fields.Char(string="CLS (mobile)", readonly=True)
    psi_tbt = fields.Char(string="TBT (mobile)", readonly=True)
    psi_fcp = fields.Char(string="FCP (mobile)", readonly=True)
    psi_speed_index = fields.Char(string="Speed Index (mobile)", readonly=True)
    psi_dom_size = fields.Integer(
        string="DOM elements", readonly=True,
        help="Number of DOM elements (Lighthouse, mobile).")
    psi_total_weight_kb = fields.Integer(
        string="Total weight (KB)", readonly=True,
        help="Total network payload of the page (Lighthouse, mobile).")
    psi_render_blocking = fields.Integer(
        string="Render-blocking resources", readonly=True)
    psi_long_tasks = fields.Integer(
        string="Long tasks", readonly=True,
        help="Main-thread tasks over 50ms (Lighthouse, mobile).")
    gsc_clicks = fields.Integer(string="Clicks (28d)", readonly=True)
    gsc_impressions = fields.Integer(string="Impressions (28d)", readonly=True)
    gsc_ctr = fields.Float(string="CTR (%)", digits=(6, 2), readonly=True)
    gsc_position = fields.Float(
        string="Avg position", digits=(6, 1), readonly=True)
    index_verdict = fields.Char(
        string="Index verdict", readonly=True,
        help="Raw Google URL Inspection verdict: PASS = indexable, "
             "NEUTRAL = excluded, FAIL = error.")
    index_status = fields.Selection(
        [("indexed", "Indexed"),
         ("not_indexed", "Not indexed"),
         ("error", "Error")],
        string="Google index", compute="_compute_index_status", store=True,
        help="Is this page actually in the Google index? Empty means it "
             "has not been inspected yet — run Check indexation on the site.")
    index_state = fields.Char(
        string="Coverage", readonly=True,
        help='Google coverage state, e.g. "Submitted and indexed".')
    google_canonical = fields.Char(
        string="Google canonical", readonly=True)
    google_last_crawl = fields.Char(
        string="Last Google crawl", readonly=True)
    ga_views = fields.Integer(string="Views (28d)", readonly=True)
    ga_sessions = fields.Integer(string="Sessions (28d)", readonly=True)
    ga_users = fields.Integer(string="Users (28d)", readonly=True)
    ga_engagement = fields.Float(
        string="Engagement (%)", digits=(6, 1), readonly=True)
    ai_title = fields.Char(string="AI title", readonly=True)
    ai_meta_description = fields.Text(
        string="AI meta description", readonly=True)
    ai_h1 = fields.Char(string="AI H1", readonly=True)
    ai_keyword = fields.Char(string="AI target keyword", readonly=True)
    ai_topic = fields.Char(
        string="AI content topic", readonly=True,
        help="Complementary content idea to strengthen this page.")
    ai_headings = fields.Text(string="AI improved headings", readonly=True)
    ai_jsonld = fields.Text(string="AI JSON-LD", readonly=True)
    ai_date = fields.Datetime(string="AI suggestions on", readonly=True)
    issues = fields.Text(string="Detected issues", readonly=True)
    issue_count = fields.Integer(string="Issue count", readonly=True)
    issue_ids = fields.One2many(
        "seo.audit.issue", "audit_id", string="Issues")
    critical_count = fields.Integer(string="Critical", readonly=True)
    warning_count = fields.Integer(string="Warnings", readonly=True)
    info_count = fields.Integer(string="Info", readonly=True)

    # Google's raw vocabulary reads as nothing to a client: PASS/NEUTRAL
    # say neither "indexed" nor "not indexed".
    _INDEX_VERDICTS = {
        "PASS": "indexed",
        "NEUTRAL": "not_indexed",
        "FAIL": "error",
    }

    @api.depends("index_verdict")
    def _compute_index_status(self):
        for rec in self:
            rec.index_status = self._INDEX_VERDICTS.get(
                (rec.index_verdict or "").strip().upper(), False)

    @api.depends("title", "final_url", "meta_description")
    def _compute_google_preview(self):
        """Approximate Google snippet rendering (title/URL/description)."""
        for rec in self:
            if not rec.audit_date:
                rec.google_preview = False
                continue
            title = escape(
                (rec.title or "(no title)")[:60]
                + ("…" if rec.title_length > 60 else ""))
            url = escape(rec.final_url or rec.name or "")
            desc = escape(
                (rec.meta_description or "(no meta description)")[:160]
                + ("…" if rec.meta_description_length > 160 else ""))
            rec.google_preview = Markup(
                '<div style="max-width:600px;font-family:arial,sans-serif;'
                'padding:12px;border:1px solid #dfe1e5;border-radius:8px;">'
                '<div style="color:#202124;font-size:12px;'
                'margin-bottom:2px;">%s</div>'
                '<div style="color:#1a0dab;font-size:20px;'
                'line-height:1.3;">%s</div>'
                '<div style="color:#4d5156;font-size:14px;'
                'line-height:1.57;">%s</div></div>'
            ) % (url, title, desc)

    def action_run_audit(self):
        for rec in self:
            rec._run_audit()
        return True

    @api.model
    def _ai_complete(self, prompt, system=None, max_tokens=2048):
        """Run one completion on the configured AI provider (BYO key)."""
        get_param = self.env["ir.config_parameter"].sudo().get_param
        provider = get_param("seo_suite.ai_provider") or "claude"
        key_param = ("seo_suite.anthropic_api_key" if provider == "claude"
                     else "seo_suite.gemini_api_key")
        api_key = get_param(key_param)
        if not api_key:
            raise UserError(
                "No %s API key configured. Add it in SEO → Configuration "
                "→ Settings (AI recommendations)."
                % ("Anthropic" if provider == "claude" else "Gemini"))
        from ..ai_client import AiError, complete
        try:
            return complete(
                provider, api_key, prompt,
                system=system,
                model=get_param("seo_suite.ai_model"),
                max_tokens=max_tokens)
        except AiError as e:
            raise UserError(str(e))

    AI_SYSTEM = ("You are an expert SEO copywriter and technical SEO "
                 "consultant. You write precise, natural copy that ranks "
                 "well without keyword stuffing.")

    def _ai_page_context(self, with_text=True):
        """Fresh page data for AI prompts (re-fetches for current content)."""
        self.ensure_one()
        url = (self.final_url or self.name or "").strip()
        lang = self.lang or "the page's language"
        text = ""
        if with_text:
            page = fetch_page(url)
            text = page["text_excerpt"] or ""
        return url, lang, text

    def action_ai_suggest_meta(self):
        """AI-written title / meta description / H1 + keyword and topic."""
        self.ensure_one()
        url, lang, text = self._ai_page_context()
        prompt = (
            "Page URL: %s\n"
            "Current title: %s\n"
            "Current meta description: %s\n"
            "Page language: %s\n"
            "Page content (excerpt):\n%s\n\n"
            "Based on this page, produce:\n"
            '- "title": an SEO title of 50-60 characters including the main '
            "keyword naturally\n"
            '- "meta_description": 140-160 characters, compelling, includes '
            "the keyword, makes people want to click\n"
            '- "h1": one clear H1 for the page\n'
            '- "keyword": the main target keyword of this page\n'
            '- "topic": one complementary content topic that would '
            "strengthen this page's ranking\n\n"
            "Write title, meta_description and h1 in %s.\n"
            "Respond with ONLY a JSON object with keys title, "
            "meta_description, h1, keyword, topic."
            % (url, self.title or "(none)",
               self.meta_description or "(none)", lang, text, lang))
        from ..ai_client import AiError, extract_json
        response = self._ai_complete(prompt, system=self.AI_SYSTEM)
        try:
            data = extract_json(response)
        except AiError as e:
            raise UserError(str(e))
        self.write({
            "ai_title": (data.get("title") or "")[:256],
            "ai_meta_description": data.get("meta_description") or "",
            "ai_h1": (data.get("h1") or "")[:256],
            "ai_keyword": (data.get("keyword") or "")[:256],
            "ai_topic": (data.get("topic") or "")[:256],
            "ai_date": fields.Datetime.now(),
        })
        return True

    def action_ai_improve_headings(self):
        """AI rewrite of the page's heading structure."""
        self.ensure_one()
        if not self.headings_outline:
            raise UserError("Run the audit first (no headings captured).")
        url, lang, _ = self._ai_page_context(with_text=False)
        prompt = (
            "Page URL: %s\nPage title: %s\nPage language: %s\n\n"
            "Improve these headings for better Google ranking using current "
            "SEO best practices: use keywords wisely, differentiate "
            "duplicated headings while keeping their meaning, keep the "
            "hierarchy sensible (one H1, no level skips), and keep the "
            "page's language.\n\nHeadings:\n%s\n\n"
            "Output ONLY the improved headings, one per line, keeping the "
            '"H<level> — text" format.'
            % (url, self.title or "(none)", lang, self.headings_outline))
        self.write({
            "ai_headings": self._ai_complete(
                prompt, system=self.AI_SYSTEM).strip(),
            "ai_date": fields.Datetime.now(),
        })
        return True

    def action_ai_generate_jsonld(self):
        """AI-generated (or improved) schema.org JSON-LD for the page."""
        self.ensure_one()
        url, lang, text = self._ai_page_context()
        existing = ("Existing schema.org types on the page: %s.\nImprove or "
                    "complete the structured data." % self.schema_types
                    if self.schema_types else
                    "The page has no structured data yet. Generate the most "
                    "appropriate schema.org JSON-LD.")
        prompt = (
            "Page URL: %s\nPage title: %s\nMeta description: %s\nH1: %s\n"
            "Page language: %s\n%s\n"
            "Page content (excerpt):\n%s\n\n"
            "Output the JSON-LD object first (raw JSON, no markdown "
            'fences, ready to paste inside <script type="application/'
            'ld+json">), then a line containing only "---", then 2-3 '
            "sentences explaining your choices."
            % (url, self.title or "(none)",
               self.meta_description or "(none)", self.h1 or "(none)",
               lang, existing, text[:4000]))
        self.write({
            "ai_jsonld": self._ai_complete(
                prompt, system=self.AI_SYSTEM, max_tokens=3000).strip(),
            "ai_date": fields.Datetime.now(),
        })
        return True

    def action_run_pagespeed(self):
        """Query Google PageSpeed Insights (mobile + desktop) for this URL."""
        self.ensure_one()
        url = (self.final_url or self.name or "").strip()
        if not url:
            raise UserError("Run the audit first (or enter a URL).")
        api_key = self.env["ir.config_parameter"].sudo().get_param(
            "seo_suite.pagespeed_api_key") or None
        mobile = pagespeed(url, api_key=api_key, strategy="mobile")
        if mobile["error"]:
            raise UserError(
                "PageSpeed failed: %s\n\nTip: add a free Google API key in "
                "SEO → Configuration → Settings to raise the quota."
                % mobile["error"])
        desktop = pagespeed(url, api_key=api_key, strategy="desktop")
        self.write({
            "psi_date": fields.Datetime.now(),
            "psi_perf_mobile": mobile["performance"],
            "psi_seo_mobile": mobile["seo"],
            "psi_a11y_mobile": mobile["accessibility"],
            "psi_bp_mobile": mobile["best_practices"],
            "psi_lcp": mobile["lcp"],
            "psi_cls": mobile["cls"],
            "psi_tbt": mobile["tbt"],
            "psi_fcp": mobile["fcp"],
            "psi_speed_index": mobile["speed_index"],
            "psi_dom_size": mobile["dom_size"],
            "psi_total_weight_kb": mobile["total_weight_kb"],
            "psi_render_blocking": mobile["render_blocking"],
            "psi_long_tasks": mobile["long_tasks"],
            "psi_perf_desktop": desktop["performance"],
            "psi_seo_desktop": desktop["seo"],
            "psi_a11y_desktop": desktop["accessibility"],
            "psi_bp_desktop": desktop["best_practices"],
        })
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
            "headings_outline": "\n".join(
                "%sH%d — %s" % ("    " * (level - 1), level, text)
                for level, text in page["headings"][:100]),
            "reading_time": page["reading_time"],
            "redirect_chain": " ".join(page["redirect_chain"])[:512],
            "word_count": page["word_count"],
            "internal_links": page["internal_links"],
            "inbound_links": page.get("inbound_links", 0),
            "outlinks": "\n".join(page.get("outlink_urls") or ()),
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
            "click_depth": (page["click_depth"]
                            if page["click_depth"] is not None else -1),
            "x_robots_tag": page["x_robots_tag"],
            "issues": "\n".join(
                i["message"] for i in issues) or "No issues detected",
            "issue_count": len(issues),
            "critical_count": by_severity["critical"],
            "warning_count": by_severity["warning"],
            "info_count": by_severity["info"],
            "issue_ids": [(5, 0, 0)] + [
                (0, 0, {"severity": i["severity"], "category": i["category"],
                        "message": i["message"],
                        "how_to_fix": i.get("fix", "")})
                for i in issues],
        }
