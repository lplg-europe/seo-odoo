# -*- coding: utf-8 -*-
"""Audit → website.page matching.

The first class pins the bug that motivated the guard: auditing a client
site and applying AI metas wrote them onto a local page that merely
shared the path. Writing SEO metadata onto the wrong site is a data
integrity failure, not a cosmetic one — a page is only ever matched when
the *host* matches too.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import TransactionCase, tagged

from ..models.seo_audit import bare_host


@tagged("standard", "at_install")
class TestNoCrossSiteMatch(TransactionCase):
    """A page belongs to a domain, never to a path alone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env["website"].create({
            "name": "Mine", "domain": "https://mine.example"})
        cls.page = cls.env["website.page"].create({
            "name": "Contact",
            "url": "/contactus",
            "website_id": cls.website.id,
            "type": "qweb",
            "arch": "<div>contact</div>",
            "key": "seo_suite_website.test_contact",
        })
        cls.site = cls.env["seo.site"].create({"name": "https://mine.example"})

    def _audit(self, url):
        return self.env["seo.audit"].create({
            "name": url, "site_id": self.site.id})

    def test_client_site_never_matches_a_local_page(self):
        audit = self._audit("https://client.be/contactus")
        self.assertFalse(
            audit.website_page_id,
            "an audited URL on another domain must never match a local page")

    def test_own_site_matches(self):
        audit = self._audit("https://mine.example/contactus")
        self.assertEqual(audit.website_page_id, self.page)

    def test_www_variant_matches(self):
        audit = self._audit("https://www.mine.example/contactus")
        self.assertEqual(audit.website_page_id, self.page)

    def test_trailing_slash_matches(self):
        audit = self._audit("https://mine.example/contactus/")
        self.assertEqual(audit.website_page_id, self.page)

    def test_website_without_domain_matches_nothing(self):
        self.website.domain = False
        audit = self._audit("https://mine.example/contactus")
        self.assertFalse(
            audit.website_page_id,
            "with no domain configured the host cannot be verified, so "
            "nothing may be matched")

    def test_apply_explains_why_nothing_matched(self):
        audit = self._audit("https://client.be/contactus")
        audit.write({"ai_title": "T", "ai_meta_description": "D"})
        with self.assertRaises(Exception) as ctx:
            audit.action_apply_meta_to_website()
        self.assertIn("domain", str(ctx.exception).lower())


@tagged("standard", "at_install")
class TestBareHost(TransactionCase):
    def test_forms_reduce_to_the_same_host(self):
        for value in ("example.be", "www.example.be", "https://example.be/",
                      "https://WWW.Example.be:443/path"):
            self.assertEqual(bare_host(value), "example.be", value)

    def test_empty_stays_empty(self):
        self.assertEqual(bare_host(""), "")
        self.assertEqual(bare_host(False), "")


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
