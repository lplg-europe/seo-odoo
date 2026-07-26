# -*- coding: utf-8 -*-
{
    "name": "Web Analytics",
    "version": "19.0.1.0.0",
    "summary": "Privacy-first, cookieless web analytics inside Odoo "
               "(Plausible-style).",
    "description": """
Web Analytics
=============
Self-hosted, privacy-first web analytics for your websites — no cookies,
no consent banner needed for basic analytics, no Google.

- One-line tracking snippet (~1.5 KB script, SPA-aware, sendBeacon)
- Cookieless visitor counting: server-side hash with a daily rotating
  salt — the visitor IP is never stored anywhere
- Sessions (30-minute sliding window), pageviews, custom events
- Acquisition channels: Direct, Organic Search, Organic Social, AI
  (ChatGPT/Claude/Perplexity referrals), Email, Paid, Referral
- UTM campaign tracking, devices / browsers / OS / languages
- Live visitors, today / 30-day stats, native Odoo graph & pivot views

Companion of the SEO Suite module (same repository), installable
independently.
""",
    "category": "Website/Analytics",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/wa_views.xml",
    ],
    "installable": True,
    "application": True,
}
