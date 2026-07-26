# -*- coding: utf-8 -*-
"""Bulk application of AI metas over a whole crawl."""
from odoo import models
from odoo.exceptions import UserError


class SeoSite(models.Model):
    _inherit = "seo.site"

    def action_apply_all_ai_metas(self):
        """Push every available AI title/meta onto its Website page."""
        self.ensure_one()
        candidates = self.audit_ids.filtered(
            lambda a: (a.ai_title or a.ai_meta_description))
        if not candidates:
            raise UserError(
                'No AI suggestions yet — run "AI: missing metas" first.')
        matched = candidates.filtered("website_page_id")
        matched.action_apply_meta_to_website()
        skipped = candidates - matched
        message = "%d page(s) updated on the Website." % len(matched)
        if skipped:
            message += (" %d suggestion(s) had no matching static website "
                        "page (blog/shop/job pages are managed in their "
                        "own apps): %s" % (
                            len(skipped),
                            ", ".join(skipped.mapped("name")[:5])))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "AI metas applied",
                "message": message,
                "type": "success" if matched else "warning",
                "sticky": bool(skipped),
            },
        }
