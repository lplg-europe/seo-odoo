# -*- coding: utf-8 -*-
{
    "name": "SEO Suite",
    "version": "19.0.1.12.0",
    "summary": "SEO suite for Odoo: on-page, technical and content audit.",
    "description": """
SEO Suite
=========
An open-source SEO toolkit for Odoo, focused on analysis rather than just URL
rewrites, schema or breadcrumbs.

On-page SEO audit:
- Crawl a URL (free, no API key)
- Title, meta description, H1/H2, canonical, robots, lang, viewport
- Internal/external links, images (and images without alt), word count
- Open Graph, Schema.org (JSON-LD types), hreflang, favicon
- Performance: response time, page size, redirect chains
- Security: HTTPS, mixed content, unsafe target=_blank links
- Content: readability (Flesch), text/HTML ratio, top keywords (FR/EN)
- Internal PageRank (link score 1-100) across the crawl
- Automatic detection of on-page SEO issues, 0-100 score

Site crawl (multi-page):
- URL discovery via robots.txt / sitemap.xml and internal links (BFS)
- Respects robots.txt disallow rules
- One audit per page + site-level issues: broken pages (4xx/5xx),
  duplicate titles, duplicate meta descriptions, noindex pages

Actionable output:
- Issues classified by severity (critical / warning / info) and by
  category (title, meta, headings, content, images, technical)
- Issues menu: filter and group by category, severity, site or page
- Printable SEO Audit Report (PDF): score, action plan by work stream,
  site-level issues, page detail — ready to hand to a client

Tracking over time:
- One snapshot per crawl: score trend graph, crawl diff (new / resolved
  issues, added / removed pages)
- Scheduled crawls: daily cron re-crawls each site every N days and syncs
  Google data automatically

Integrations:
- Google PageSpeed Insights / Core Web Vitals per page (free BYO API key)
- Broken internal links checker (HEAD pass over discovered URLs)
- Google Search Console (BYO service account): clicks, impressions, CTR,
  position per page + top search queries + URL Inspection (real
  indexation status of every page)
- Google Analytics 4: views, sessions, users, engagement per page
- Keyword tracking: declare target queries, every sync stores the GSC
  position — trend graph per keyword
- DataForSEO (BYO paid key): monthly search volumes / CPC / competition
  and live SERP snapshots (the legal alternative to scraping Google)
- AI recommendations (BYO Claude or Gemini key): title/meta/H1 writing,
  bulk missing-meta suggestions, heading rewrites, JSON-LD generation —
  suggestions are stored for human validation, never auto-published
- MCP server (mcp/server.py): expose the same audits to AI assistants
""",
    "category": "Website/SEO",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["base", "base_setup", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/seo_audit_views.xml",
        "views/seo_site_views.xml",
        "views/seo_issue_views.xml",
        "views/seo_history_views.xml",
        "views/seo_keyword_views.xml",
        "views/seo_ai_prompt_views.xml",
        "views/seo_report_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "report/seo_site_report.xml",
        "data/ir_cron.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
