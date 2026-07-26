# -*- coding: utf-8 -*-
"""One-click prospect flow: paste a URL, crawl it, get the printable
audit report — built for 'free SEO audit' offers."""
from odoo import fields, models
from odoo.exceptions import UserError


class SeoReportWizard(models.TransientModel):
    _name = "seo.report.wizard"
    _description = "Quick SEO audit report"

    url = fields.Char(string="Website URL", required=True)
    max_pages = fields.Integer(string="Max pages", default=30)
    check_links = fields.Boolean(
        string="Check remaining links", default=True,
        help="Also HEAD-check discovered-but-not-crawled URLs — broken "
             "links make the strongest impression in a prospect report.")

    def action_generate(self):
        """Crawl (reusing the site if it exists) and open the PDF report."""
        self.ensure_one()
        url = (self.url or "").strip()
        if not url:
            raise UserError("Please enter the website URL.")
        Site = self.env["seo.site"]
        temp = Site.new({"name": url})
        host = temp._bare_host()
        site = Site.search([]).filtered(
            lambda s: s._bare_host() == host)[:1]
        if site:
            # Existing (possibly monitored) site: keep its configuration.
            site.action_crawl()
        else:
            site = Site.create({
                "name": url,
                "max_pages": max(1, self.max_pages or 30),
                "check_links": self.check_links,
            })
            site.action_crawl()
        return self.env.ref(
            "seo_suite.action_report_seo_site").report_action(site)
