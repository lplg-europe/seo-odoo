# -*- coding: utf-8 -*-
"""One detected SEO issue on one audited page — filterable and groupable,
so an agency can turn a crawl into a categorized action plan."""
from odoo import fields, models

SEVERITIES = [
    ("critical", "Critical"),
    ("warning", "Warning"),
    ("info", "Info"),
]

CATEGORIES = [
    ("title", "Title"),
    ("meta", "Meta description"),
    ("headings", "Headings"),
    ("content", "Content"),
    ("images", "Images"),
    ("links", "Links"),
    ("social", "Social / Open Graph"),
    ("performance", "Performance"),
    ("security", "Security"),
    ("technical", "Technical"),
]


class SeoAuditIssue(models.Model):
    _name = "seo.audit.issue"
    _description = "SEO issue detected on a page"
    _order = "audit_id, id"
    _rec_name = "message"

    audit_id = fields.Many2one(
        "seo.audit", string="Audit", required=True,
        ondelete="cascade", index=True)
    site_id = fields.Many2one(
        "seo.site", string="Site", related="audit_id.site_id",
        store=True, index=True)
    url = fields.Char(string="URL", related="audit_id.name")
    severity = fields.Selection(SEVERITIES, string="Severity", required=True)
    category = fields.Selection(CATEGORIES, string="Category", required=True)
    message = fields.Char(string="Issue", required=True)
    how_to_fix = fields.Text(string="How to fix", readonly=True)
