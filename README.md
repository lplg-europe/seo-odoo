# SEO Odoo

An open-source SEO toolkit for Odoo, focused on analysis.

Most Odoo SEO modules focus on URL rewrites, schema or breadcrumbs. This
project adds **SEO analysis** — on-page audit and crawl today, with Search
Console, keywords and AI recommendations planned.

## Features

| Feature | Status | Description |
|---|---|---|
| On-page audit | ✅ | Audit a single URL: title, meta, H1/H2, canonical, robots, links, images, 0-100 score |
| Site crawl | ✅ | Multi-page crawl: sitemap.xml + internal links (BFS), respects robots.txt, one audit per page |
| Site-level issues | ✅ | Broken pages (4xx/5xx), duplicate titles, duplicate meta descriptions, noindex pages, missing favicon |
| Issue triage | ✅ | Every issue classified by severity (critical/warning/info) and category; filter & group in the Issues menu |
| Audit report (PDF) | ✅ | Printable client-ready report: score, action plan by work stream, page detail |
| Social & schema | ✅ | Open Graph completeness, Schema.org JSON-LD types, hreflang, `html lang`, viewport |
| Performance & security | ✅ | Response time, page size, redirect chains, HTTPS, mixed content, unsafe `target=_blank` |
| Content quality | ✅ | Readability (Flesch), text/HTML ratio, top keywords (FR/EN stop-words) |
| Link score | ✅ | Internal PageRank (damping 0.85) across crawled pages, normalized 1-100 |
| PageSpeed Insights | ✅ | Per-page Core Web Vitals + Lighthouse scores, mobile & desktop (free BYO Google key, SEO → Configuration) |
| Broken links | ✅ | Optional HEAD pass over discovered-but-not-crawled URLs, with referring pages |
| Search Console | ✅ | BYO service account: clicks/impressions/CTR/position per page, top queries, and **URL Inspection** (real indexation status of every page) |
| Google Analytics 4 | ✅ | Views, sessions, users, engagement per page (28 days) |
| History & trend | ✅ | One snapshot per crawl: score trend graph + crawl diff (new/resolved issues, added/removed pages) |
| Scheduled crawls | ✅ | Daily cron re-crawls each site every N days and syncs Google data — the recurring-contract engine |
| Keyword tracking | ✅ | Declare target queries; every sync stores the GSC position → trend per keyword |
| SERP & volumes | ✅ | DataForSEO (BYO paid key): monthly volumes/CPC/competition + live SERP snapshots with competitor list |
| Quick audit | ✅ | One-click wizard: paste a prospect URL → crawl → printable report (built for "free SEO audit" offers) |

The crawl engine ([crawler.py](addons/seo_suite/crawler.py)) is pure Python
stdlib with **no Odoo dependency** — it can be reused standalone (scripts, CI,
other projects) or swapped into another frontend.

The crawl engine stays dependency-free; Google integrations sign their
service-account JWT with `cryptography`, which ships with standard Odoo.

### Roadmap
- AI recommendations (Claude / Gemini)
- Backlinks & domain overview (DataForSEO)
- Server log analyzer (bots, LLM crawlers)
- Odoo Website helpers: sitemap, robots, schema, redirects

## Installation (dev)

1. Add `addons/` to your Odoo `addons_path` (odoo.conf).
2. Restart Odoo, enable **developer mode**.
3. Apps → *Update Apps List* → search **SEO Suite** → Install.
4. Menu **SEO → Sites** → enter the root URL → **Crawl site**, or
   **SEO → Audits** for a single-page audit.

> The manifest targets Odoo 19. For Odoo 17/18, adjust the version prefix in
> `addons/seo_suite/__manifest__.py`.

## License

LGPL-3 (standard OCA / Odoo open source). The crawl engine is pure Python
(stdlib), with no dependency and no proprietary data.

## Author

Maintained by [LPLG](https://lplg.eu).
