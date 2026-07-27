# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    seo_pagespeed_api_key = fields.Char(
        string="PageSpeed Insights API key",
        config_parameter="seo_suite.pagespeed_api_key",
        help="Optional free Google API key for PageSpeed Insights — without "
             "it the shared anonymous quota applies (a few calls per day). "
             "Get one at https://developers.google.com/speed/docs/insights/"
             "v5/get-started")
    seo_dataforseo_login = fields.Char(
        string="DataForSEO API login",
        config_parameter="seo_suite.dataforseo_login",
        help="Paid BYO service (https://dataforseo.com) for search volumes "
             "and live SERP snapshots. The API login is usually an email.")
    seo_dataforseo_password = fields.Char(
        string="DataForSEO API password",
        config_parameter="seo_suite.dataforseo_password")
    seo_ai_provider = fields.Selection(
        [("claude", "Claude (Anthropic)"), ("gemini", "Google Gemini")],
        string="AI provider", default="claude",
        config_parameter="seo_suite.ai_provider")
    seo_anthropic_api_key = fields.Char(
        string="Anthropic API key",
        config_parameter="seo_suite.anthropic_api_key",
        help="BYO key from https://platform.claude.com — used for AI title/"
             "meta suggestions, heading rewrites and JSON-LD generation.")
    seo_gemini_api_key = fields.Char(
        string="Gemini API key",
        config_parameter="seo_suite.gemini_api_key",
        help="BYO key from Google AI Studio.")
    seo_ai_model = fields.Char(
        string="AI model override",
        config_parameter="seo_suite.ai_model",
        help="Optional. Defaults: claude-opus-4-8 / gemini-2.5-flash.")
    seo_indexnow_key = fields.Char(
        string="IndexNow key",
        config_parameter="seo_suite.indexnow_key",
        help="Free, no account needed. Generate any 8-128 character "
             "hexadecimal string, publish it as a text file containing "
             "exactly that string at https://yoursite/<key>.txt, and paste "
             "it here.\n"
             "Submitting a URL then tells Bing, Yandex, Seznam and Naver to "
             "crawl it within minutes. Google does not participate in "
             "IndexNow — no tool can force a Google indexation.")
    seo_indexnow_key_location = fields.Char(
        string="IndexNow key URL",
        config_parameter="seo_suite.indexnow_key_location",
        help="Optional. Only needed when the key file is not at the site "
             "root, e.g. https://example.com/docs/<key>.txt")
    seo_google_service_account = fields.Char(
        string="Google service account (JSON key)",
        config_parameter="seo_suite.google_service_account",
        help="Paste the FULL JSON key of a Google Cloud service account to "
             "enable Search Console and Analytics syncing.\n"
             "1. In Google Cloud: enable the 'Google Search Console API' "
             "and 'Google Analytics Data API', create a service account "
             "and download a JSON key.\n"
             "2. Add the service account email as a user of your Search "
             "Console property and as a viewer of your GA4 property.\n"
             "3. Paste the whole JSON file content here.")
