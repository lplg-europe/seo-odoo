# -*- coding: utf-8 -*-
"""Bridge audit → Odoo Website: match the audited URL to a website.page
and push the AI-suggested metas into it."""
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import UserError


def bare_host(value):
    """Comparable host from a URL, a domain setting, or a bare hostname.

    Odoo's website.domain is free text — "example.com", "www.example.com"
    or "https://example.com/" are all seen in the wild — so everything is
    reduced to a lowercase host without the www prefix before comparing.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    host = urlsplit(value).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


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
        """Match on host AND path — never on the path alone.

        Matching by path was a data-integrity bug: auditing a client site
        and clicking "Apply AI metas" wrote a meta meant for
        client.be/contactus onto the local /contactus, because both share
        the path. The host now has to match the website's configured
        domain, so a page is only ever updated on the site it belongs to.
        A website with no domain set matches nothing — see
        action_apply_meta_to_website for the message that says so.
        """
        Page = self.env["website.page"]
        for rec in self:
            split = urlsplit(rec.final_url or rec.name or "")
            path = split.path or "/"
            host = bare_host(split.netloc)
            paths = [path] if path == "/" else [path, path.rstrip("/")]
            match = Page.browse()
            if host:
                for page in Page.search([("url", "in", list(set(paths)))]):
                    if bare_host(page.website_id.domain) == host:
                        match = page
                        break
            rec.website_page_id = match

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
                        "No Odoo Website page on this database matches %s.\n\n"
                        "Pages are matched on domain *and* path, so a site "
                        "hosted elsewhere is never touched. If this URL is "
                        "one of your own websites, set its address in "
                        "Website → Configuration → Settings → Domain, then "
                        "try again. Only static website pages can be "
                        "updated here." % rec.name)
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

    def _allow_indexing(self):
        """Clear the two barriers Odoo controls on the matched page.

        website_indexed = False makes Odoo drop the page from sitemap.xml
        AND emit <meta name="robots" content="noindex"> — so a page left
        unchecked can never be indexed, whatever else is done. Flipping it
        back is the only "click that helps indexing" that really exists.
        """
        blocked = self.filtered(
            lambda a: a.website_page_id and not a.website_page_id.sudo(
            ).website_indexed)
        blocked.mapped("website_page_id").sudo().write(
            {"website_indexed": True})
        return len(blocked)

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
