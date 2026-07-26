# -*- coding: utf-8 -*-
"""Keyword cannibalization: one query, several of your own pages.

When two pages of the same site rank for the same query, Google has to
pick one — and often picks the weaker. The clicks split, the internal
links split, and both pages plateau. Search Console knows this at the
query x page level; this model turns that raw data into a decision:
which page to keep, which to merge or redirect.
"""
from odoo import api, fields, models


class SeoCannibalization(models.Model):
    _name = "seo.cannibalization"
    _description = "Query ranking with several pages of the same site"
    _order = "impressions desc, id"
    _rec_name = "query"

    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    query = fields.Char(string="Query", required=True, index=True)
    page_count = fields.Integer(
        string="Competing pages", readonly=True,
        help="Pages of this site that Search Console saw ranking for the "
             "query over the period.")
    impressions = fields.Integer(string="Impressions", readonly=True)
    clicks = fields.Integer(string="Clicks", readonly=True)
    best_position = fields.Float(
        string="Best position", digits=(6, 1), readonly=True)
    winner_url = fields.Char(
        string="Strongest page", readonly=True,
        help="The page with the most impressions — the natural candidate "
             "to keep and reinforce.")
    detail = fields.Text(string="Competing pages detail", readonly=True)
    severity = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")],
        string="Severity", readonly=True, index=True)
    recommendation = fields.Text(string="Recommendation", readonly=True)
    date = fields.Datetime(string="Detected on", readonly=True)

    def action_view_pages(self):
        """Open the audits of the pages competing on this query."""
        self.ensure_one()
        urls = [line.split(" ")[0] for line in (self.detail or "").splitlines()
                if line.strip()]
        return {
            "type": "ir.actions.act_window",
            "name": "Pages competing on %s" % self.query,
            "res_model": "seo.audit",
            "view_mode": "list,form",
            "domain": [("site_id", "=", self.site_id.id),
                       ("name", "in", urls)],
        }

    @api.model
    def _build(self, site, rows, min_impressions=10):
        """Turn GSC query x page rows into cannibalization records.

        `rows` are the raw Search Console rows with keys ("query", "page"),
        clicks, impressions and position.
        """
        by_query = {}
        for row in rows:
            keys = row.get("keys") or []
            if len(keys) < 2:
                continue
            query, page = keys[0], keys[1]
            by_query.setdefault(query, []).append({
                "page": page,
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "position": float(row.get("position") or 0),
            })
        values = []
        now = fields.Datetime.now()
        for query, pages in by_query.items():
            pages = [p for p in pages if p["impressions"]]
            if len(pages) < 2:
                continue
            total_impressions = sum(p["impressions"] for p in pages)
            if total_impressions < min_impressions:
                continue
            pages.sort(key=lambda p: -p["impressions"])
            winner = pages[0]
            challengers = pages[1:]
            # the challengers' weight is what makes it a real problem
            share = 100.0 * sum(
                p["impressions"] for p in challengers) / total_impressions
            positions = [p["position"] for p in pages if p["position"]]
            spread = (max(positions) - min(positions)) if positions else 0
            if share >= 35 and spread <= 15:
                severity = "high"
            elif share >= 15:
                severity = "medium"
            else:
                severity = "low"
            values.append({
                "site_id": site.id,
                "query": query,
                "page_count": len(pages),
                "impressions": total_impressions,
                "clicks": sum(p["clicks"] for p in pages),
                "best_position": min(positions) if positions else 0,
                "winner_url": winner["page"],
                "detail": "\n".join(
                    "%s — position %.1f, %d impressions, %d clicks"
                    % (p["page"], p["position"], p["impressions"], p["clicks"])
                    for p in pages),
                "severity": severity,
                "recommendation": site._cannibalization_advice(
                    winner, challengers, severity),
                "date": now,
            })
        site.cannibalization_ids.unlink()
        return self.create(values) if values else self.browse()
