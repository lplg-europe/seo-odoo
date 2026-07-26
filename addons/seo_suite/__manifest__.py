# -*- coding: utf-8 -*-
{
    "name": "SEO Suite",
    "version": "19.0.1.2.0",
    "summary": "SEO suite for Odoo: on-page, technical and content audit.",
    "description": """
SEO Suite
=========
An open-source SEO toolkit for Odoo, focused on analysis rather than just URL
rewrites, schema or breadcrumbs.

On-page SEO audit:
- Crawl a URL (free, no API key)
- Title, meta description, H1, canonical, robots
- Internal/external links, images (and images without alt), word count
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

Coming next: Google Search Console, keyword research, AI recommendations.
""",
    "category": "Website/SEO",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/seo_audit_views.xml",
        "views/seo_site_views.xml",
        "views/seo_issue_views.xml",
        "report/seo_site_report.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
