# -*- coding: utf-8 -*-
"""Tracked keywords — GSC position history per target query, optionally
enriched with DataForSEO search volumes and live SERP snapshots."""
from odoo import api, fields, models
from odoo.exceptions import UserError

# Convention: no impressions in the period = not visible = position 101.
POSITION_NOT_FOUND = 101


class SeoKeyword(models.Model):
    _name = "seo.keyword"
    _description = "Tracked SEO keyword"
    _order = "site_id, position, name"

    _unique_site_keyword = models.Constraint(
        "UNIQUE(site_id, name)",
        "This keyword is already tracked for this site.")

    name = fields.Char(string="Keyword", required=True)
    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    origin = fields.Selection(
        [("manual", "Tracked on purpose"),
         ("discovered", "Found in Search Console")],
        string="Origin", default="manual", required=True, readonly=True,
        help="Manual keywords are the ones you decided to rank for. "
             "Discovered ones are queries Google already shows you for — "
             "useful to see the demand you did not plan for.")
    position = fields.Float(
        string="Position", digits=(6, 1), readonly=True,
        help="Average Google position over the last 28 days "
             "(101 = not in the results).")
    clicks = fields.Integer(string="Clicks (28d)", readonly=True)
    impressions = fields.Integer(string="Impressions (28d)", readonly=True)
    ctr = fields.Float(string="CTR (%)", digits=(6, 2), readonly=True)
    best_page = fields.Char(
        string="Ranking page", readonly=True,
        help="The page Google shows most for this query.")
    last_sync = fields.Datetime(string="Last sync", readonly=True)
    history_ids = fields.One2many(
        "seo.keyword.history", "keyword_id", string="History")
    position_delta = fields.Float(
        compute="_compute_position_delta", digits=(6, 1),
        string="Δ places",
        help="Places gained (positive) or lost since the previous sync.")
    volume = fields.Integer(
        string="Volume/month", readonly=True,
        help="Monthly Google searches (DataForSEO).")
    cpc = fields.Float(string="CPC ($)", digits=(6, 2), readonly=True)
    competition = fields.Integer(
        string="Competition", readonly=True,
        help="Google Ads competition index 0-100 (DataForSEO).")
    our_position_serp = fields.Integer(
        string="Live SERP position", readonly=True,
        help="Position of our site in the live SERP snapshot "
             "(0 = not in the checked depth).")
    serp_snapshot = fields.Text(string="SERP top 10", readonly=True)
    serp_date = fields.Datetime(string="SERP checked on", readonly=True)

    @api.depends("history_ids.position")
    def _compute_position_delta(self):
        for rec in self:
            points = rec.history_ids.sorted("date")[-2:]
            if len(points) == 2:
                rec.position_delta = points[0].position - points[1].position
            else:
                rec.position_delta = 0.0

    def action_view_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Position history — %s" % self.name,
            "res_model": "seo.keyword.history",
            "view_mode": "graph,list",
            "domain": [("keyword_id", "=", self.id)],
            "context": {"default_keyword_id": self.id},
        }

    def action_analyze_serp(self):
        """Live SERP snapshot for this keyword via DataForSEO (paid, BYO)."""
        self.ensure_one()
        site = self.site_id
        login, password = site._dataforseo_credentials()
        from ..dataforseo import DataForSeoError, serp_organic
        try:
            serp = serp_organic(
                login, password, self.name,
                location=site.dfs_location, language=site.dfs_language)
        except DataForSeoError as e:
            raise UserError(str(e))
        site_netloc = site._bare_host()
        our_position = 0
        lines = []
        for item in serp["items"]:
            domain = (item["domain"] or "").lower()
            bare = domain[4:] if domain.startswith("www.") else domain
            marker = ""
            if bare == site_netloc:
                marker = "  ◄ US"
                if not our_position:
                    our_position = item["position"]
            if item["position"] <= 10:
                lines.append("%2d. %-40s %s%s" % (
                    item["position"], domain[:40],
                    (item["title"] or "")[:60], marker))
        self.write({
            "our_position_serp": our_position,
            "serp_snapshot": "\n".join(lines) or "No organic results",
            "serp_date": fields.Datetime.now(),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "SERP analyzed",
                "message": "Cost: $%.4f — our position: %s" % (
                    serp["cost"],
                    our_position or "not in top %d" % len(serp["items"])),
                "type": "success",
            },
        }


class SeoKeywordHistory(models.Model):
    _name = "seo.keyword.history"
    _description = "Tracked keyword position snapshot"
    _order = "date desc, id desc"
    _rec_name = "date"

    keyword_id = fields.Many2one(
        "seo.keyword", string="Keyword", required=True,
        ondelete="cascade", index=True)
    site_id = fields.Many2one(
        related="keyword_id.site_id", store=True, index=True)
    date = fields.Datetime(
        string="Date", required=True, default=fields.Datetime.now)
    # A rank and a rate are averaged, never summed: two days at position 8
    # do not make position 16. Clicks and impressions, on the other hand,
    # are genuine counts and stay additive over a period.
    position = fields.Float(
        string="Position", digits=(6, 1), readonly=True, aggregator="avg")
    clicks = fields.Integer(string="Clicks", readonly=True)
    impressions = fields.Integer(string="Impressions", readonly=True)
    ctr = fields.Float(
        string="CTR (%)", digits=(6, 2), readonly=True, aggregator="avg")
    page = fields.Char(string="Ranking page", readonly=True)
