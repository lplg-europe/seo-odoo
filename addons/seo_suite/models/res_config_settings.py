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
