# -*- coding: utf-8 -*-
{
    "name": "Web Analytics",
    "version": "19.0.2.2.0",
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
- UTM campaign tracking, devices / browsers / OS / languages / countries
  (via the server's GeoIP database when configured)
- Live visitors, bounce rate, session duration, today / 30-day stats
- Web Vitals (LCP / CLS / FCP / TTFB) measured natively, LCP p75
- Outbound-click tracking and JS error tracking
- Conversion goals (page visited, custom event, outbound click) with
  session-based conversion rates
- Multi-step funnels: ordered steps with per-step sessions, conversion
  and drop-off percentages
- Weekly retention cohorts (opt-in stable visitor hash — daily rotation
  stays the default for maximum privacy)
- Uptime monitoring: periodic HTTP checks with email alerts on
  down / recovery
- Native Odoo graph & pivot dashboards

Companion of the SEO Suite module (same repository), installable
independently.
""",
    "category": "Website/Analytics",
    "author": "LPLG",
    "website": "https://lplg.eu",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/wa_views.xml",
        "report/wa_site_report.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": True,
}
