# -*- coding: utf-8 -*-
"""Internal linking recommendations: "add a link from this page to that one".

The crawl already knows the internal link graph (who links to whom), the
internal PageRank of every page and, when Search Console is connected,
which pages have demand but no visibility. Crossing the three answers a
question no SEO tool answers concretely: which exact link should I add?
"""
from odoo import fields, models


class SeoLinkSuggestion(models.Model):
    _name = "seo.link.suggestion"
    _description = "Suggested internal link between two pages"
    _order = "score desc, id"
    _rec_name = "target_url"

    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    source_url = fields.Char(
        string="Add a link on", required=True,
        help="The page that should carry the new link — it has internal "
             "authority and covers the same topic.")
    target_url = fields.Char(
        string="Pointing to", required=True, index=True,
        help="The page that needs the link: it lacks internal support "
             "relative to the demand it attracts.")
    anchor = fields.Char(
        string="Suggested anchor",
        help="Shared topic between the two pages — a natural anchor text.")
    reason = fields.Text(string="Why", readonly=True)
    source_link_score = fields.Integer(
        string="Source authority", readonly=True,
        help="Internal PageRank of the linking page (1-100).")
    target_inbound = fields.Integer(
        string="Target inbound links", readonly=True)
    target_impressions = fields.Integer(
        string="Target impressions (28d)", readonly=True)
    score = fields.Integer(
        string="Priority", readonly=True, index=True,
        help="Higher means a bigger expected gain: strong source, "
             "under-linked target, proven search demand.")
    date = fields.Datetime(string="Computed on", readonly=True)

    def action_open_target(self):
        self.ensure_one()
        audit = self.env["seo.audit"].search(
            [("site_id", "=", self.site_id.id),
             ("name", "=", self.target_url)], limit=1)
        return {
            "type": "ir.actions.act_window",
            "res_model": "seo.audit",
            "res_id": audit.id,
            "view_mode": "form",
        }
