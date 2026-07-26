# -*- coding: utf-8 -*-
{
    "name": "SEO Suite — Website bridge",
    "version": "19.0.1.0.0",
    "summary": "Apply SEO Suite audit fixes directly to Odoo Website: "
               "AI metas in one click, 301 redirects for broken pages.",
    "description": """
SEO Suite — Website bridge
==========================
Closes the loop between the audit and the CMS (auto-installed when both
SEO Suite and Website are present):

- Each audited page is matched to its Odoo Website page
- Apply the AI-suggested title / meta description to the Website page
  in one click — per page, or in bulk for the whole crawl
- Turn a 404 found by the crawl into a 301 redirect (website.rewrite)
  pre-filled in one click
""",
    "category": "Website/SEO",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["seo_suite", "website"],
    "auto_install": True,
    "data": [
        "views/seo_views.xml",
    ],
    "installable": True,
}
