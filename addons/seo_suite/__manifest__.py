# -*- coding: utf-8 -*-
{
    "name": "SEO Suite",
    "version": "19.0.1.0.0",
    "summary": "SEO suite for Odoo: on-page, technical and content audit.",
    "description": """
SEO Suite
=========
An open-source SEO toolkit for Odoo, focused on analysis rather than just URL
rewrites, schema or breadcrumbs.

Module 1 — On-page SEO audit:
- Crawl a URL (free, no API key)
- Title, meta description, H1, canonical, robots
- Internal/external links, images (and images without alt), word count
- Automatic detection of on-page SEO issues

Coming next: multi-page crawl, Google Search Console, keyword research,
AI recommendations.
""",
    "category": "Website/SEO",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/seo_audit_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
