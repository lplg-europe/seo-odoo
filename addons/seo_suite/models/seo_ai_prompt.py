# -*- coding: utf-8 -*-
"""AI Visibility prompt explorer — ask real LLMs a question a prospect
would ask, and check whether the brand is mentioned and the site cited."""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

PLATFORMS = [
    ("chatgpt", "ChatGPT"),
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("perplexity", "Perplexity"),
]


def brand_mentioned(text, brand):
    """Word-boundary, case-insensitive brand detection."""
    if not text or not brand:
        return False
    pattern = r"(?<!\w)%s(?!\w)" % re.escape(brand.strip())
    return bool(re.search(pattern, text, re.IGNORECASE))


class SeoAiPrompt(models.Model):
    _name = "seo.ai.prompt"
    _description = "AI visibility prompt"
    _order = "id desc"

    name = fields.Char(
        string="Prompt", required=True,
        help='A question a prospect would ask an AI assistant, e.g. '
             '"best retirement home near Manage, Belgium".')
    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    web_search = fields.Boolean(
        string="Allow web search", default=True,
        help="Let the LLMs browse the web while answering (closer to "
             "real assistant behavior).")
    last_run = fields.Datetime(string="Last run", readonly=True)
    result_ids = fields.One2many(
        "seo.ai.prompt.result", "prompt_id", string="Results")
    mention_summary = fields.Char(
        compute="_compute_mention_summary", string="Visibility")

    @api.depends("result_ids.brand_mentioned", "result_ids.domain_cited")
    def _compute_mention_summary(self):
        for rec in self:
            results = rec.result_ids
            if not results:
                rec.mention_summary = "not run yet"
                continue
            rec.mention_summary = "mentioned %d/%d · cited %d/%d" % (
                len(results.filtered("brand_mentioned")), len(results),
                len(results.filtered("domain_cited")), len(results))

    def action_run(self):
        """Ask all four LLM platforms and record mentions/citations."""
        self.ensure_one()
        site = self.site_id
        brand = (site.brand_name or "").strip()
        if not brand:
            raise UserError(
                "Set the brand name on the site first (AI Visibility tab) "
                "— it is what we look for in the AI answers.")
        login, password = site._dataforseo_credentials()
        from ..dataforseo import DataForSeoError, llm_response
        host = site._bare_host()
        total_cost = 0.0
        self.result_ids.unlink()
        Result = self.env["seo.ai.prompt.result"]
        errors = []
        for platform, _label in PLATFORMS:
            try:
                data, cost = llm_response(
                    login, password, platform, self.name,
                    web_search=self.web_search)
            except DataForSeoError as e:
                errors.append("%s: %s" % (platform, e))
                continue
            total_cost += cost
            Result.create({
                "prompt_id": self.id,
                "platform": platform,
                "model": data["model"],
                "response": data["text"],
                "citations": "\n".join(data["citations"]),
                "brand_mentioned": brand_mentioned(data["text"], brand),
                "domain_cited": any(host in url.lower()
                                    for url in data["citations"]),
                "cost": cost,
            })
        self.last_run = fields.Datetime.now()
        if errors and not self.result_ids:
            raise UserError("All platforms failed:\n%s" % "\n".join(errors))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Prompt tested on %d platform(s)"
                         % len(self.result_ids),
                "message": "%s — cost $%.4f%s" % (
                    self.mention_summary, total_cost,
                    (" — failed: " + "; ".join(errors)) if errors else ""),
                "type": "warning" if errors else "success",
                "sticky": bool(errors),
            },
        }


class SeoAiPromptResult(models.Model):
    _name = "seo.ai.prompt.result"
    _description = "AI visibility prompt result"
    _order = "prompt_id, platform"

    prompt_id = fields.Many2one(
        "seo.ai.prompt", string="Prompt", required=True,
        ondelete="cascade", index=True)
    site_id = fields.Many2one(
        related="prompt_id.site_id", store=True, index=True)
    platform = fields.Selection(PLATFORMS, string="Platform", required=True)
    model = fields.Char(string="Model", readonly=True)
    response = fields.Text(string="Answer", readonly=True)
    citations = fields.Text(string="Cited URLs", readonly=True)
    brand_mentioned = fields.Boolean(string="Brand mentioned", readonly=True)
    domain_cited = fields.Boolean(string="Site cited", readonly=True)
    cost = fields.Float(string="Cost ($)", digits=(8, 4), readonly=True)
    date = fields.Datetime(
        string="Date", default=fields.Datetime.now, readonly=True)
