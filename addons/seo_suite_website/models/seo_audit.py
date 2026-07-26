# -*- coding: utf-8 -*-
"""Bridge audit → Odoo Website: match the audited URL to a website.page
and push the AI-suggested metas into it."""
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import UserError


class SeoAudit(models.Model):
    _inherit = "seo.audit"

    website_page_id = fields.Many2one(
        "website.page", string="Website page",
        compute="_compute_website_page",
        help="The Odoo Website page matching this audited URL (static "
             "website pages only — blog posts, products, job offers have "
             "their own SEO fields in their respective apps).")

    @api.depends("final_url", "name")
    def _compute_website_page(self):
        Page = self.env["website.page"]
        for rec in self:
            path = urlsplit(rec.final_url or rec.name or "").path or "/"
            page = Page.search([("url", "=", path)], limit=1)
            if not page and path != "/" and path.endswith("/"):
                page = Page.search([("url", "=", path.rstrip("/"))], limit=1)
            rec.website_page_id = page

    def action_apply_meta_to_website(self):
        """Write the AI-suggested title/meta onto the matched page."""
        applied = 0
        for rec in self:
            if not (rec.ai_title or rec.ai_meta_description):
                if len(self) == 1:
                    raise UserError(
                        'Run "AI: title & meta" first — there is no '
                        "suggestion to apply.")
                continue
            if not rec.website_page_id:
                if len(self) == 1:
                    raise UserError(
                        "No matching Odoo Website page for %s. Only static "
                        "website pages can be updated here." % rec.name)
                continue
            values = {}
            if rec.ai_title:
                values["website_meta_title"] = rec.ai_title
            if rec.ai_meta_description:
                values["website_meta_description"] = rec.ai_meta_description
            rec.website_page_id.write(values)
            applied += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Metas applied to Website",
                "message": "%d page(s) updated. Re-crawl the site to see "
                           "the score improve." % applied,
                "type": "success",
            },
        }

    def action_create_redirect(self):
        """Open a pre-filled 301 redirect for this (broken) URL."""
        self.ensure_one()
        path = urlsplit(self.final_url or self.name or "").path or "/"
        return {
            "type": "ir.actions.act_window",
            "name": "Create 301 redirect",
            "res_model": "website.rewrite",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_name": "SEO fix: %s" % path,
                "default_redirect_type": "301",
                "default_url_from": path,
            },
        }
