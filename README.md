# SEO Odoo

An open-source SEO toolkit for Odoo, focused on analysis.

Most Odoo SEO modules focus on URL rewrites, schema or breadcrumbs. This
project adds **SEO analysis** — on-page audit and crawl today, with Search
Console, keywords and AI recommendations planned.

## Features

| Feature | Status | Description |
|---|---|---|
| On-page audit | ✅ | Audit a single URL: title, meta, H1, canonical, robots, links, images, 0-100 score |
| Site crawl | ✅ | Multi-page crawl: sitemap.xml + internal links (BFS), respects robots.txt, one audit per page |
| Site-level issues | ✅ | Broken pages (4xx/5xx), duplicate titles, duplicate meta descriptions, noindex pages |
| Issue triage | ✅ | Every issue classified by severity (critical/warning/info) and category; filter & group in the Issues menu |
| Audit report (PDF) | ✅ | Printable client-ready report: score, action plan by work stream, page detail |

The crawl engine ([crawler.py](addons/seo_suite/crawler.py)) is pure Python
stdlib with **no Odoo dependency** — it can be reused standalone (scripts, CI,
other projects) or swapped into another frontend.

### Roadmap
- Scheduled crawls (cron) + history / score trend
- Google Search Console integration (positions, striking-distance)
- Keyword research (BYO DataForSEO key, premium)
- AI recommendations (Claude / Gemini)
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
