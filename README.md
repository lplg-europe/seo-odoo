# SEO Odoo

An open-source SEO toolkit for Odoo, focused on analysis.

Most Odoo SEO modules focus on URL rewrites, schema or breadcrumbs. This
project adds **SEO analysis** — on-page audit and crawl today, with Search
Console, keywords and AI recommendations planned.

## Modules

| Module | Status | Description |
|---|---|---|
| `seo_suite` | ✅ v1 | On-page SEO audit of a URL (free crawl, no API key) |

### Roadmap
- Multi-page crawl (indexation, 404s, duplicate titles, thin content)
- Google Search Console integration (positions, striking-distance)
- Keyword research (BYO DataForSEO key, premium)
- AI recommendations (Claude / Gemini)
- Odoo Website helpers: sitemap, robots, schema, redirects

## Installation (dev)

1. Add `addons/` to your Odoo `addons_path` (odoo.conf).
2. Restart Odoo, enable **developer mode**.
3. Apps → *Update Apps List* → search **SEO Suite** → Install.
4. Menu **SEO → Audits** → enter a URL → **Run audit**.

> The manifest targets Odoo 19. For Odoo 17/18, adjust the version prefix in
> `addons/seo_suite/__manifest__.py`.

## License

LGPL-3 (standard OCA / Odoo open source). The crawl engine is pure Python
(stdlib), with no dependency and no proprietary data.

## Author

Maintained by [LPLG](https://lplg.eu).
