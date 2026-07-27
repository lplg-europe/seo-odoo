# -*- coding: utf-8 -*-
"""URL handling of the crawler. Pure functions, no network, no database.

The first class is the important one: it pins the fact that the crawler
never invents a URL. A competitor audit reporting a 404 is only credible
if the URL came from the audited site itself, so a change that started
synthesizing URLs would be a trust bug, not just a defect.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import BaseCase, tagged

from ..crawler import (
    in_prefix, normalize_link, root_prefix, same_site, _requestable)

HOST = "www.caresolutions.be"
PAGE = "https://www.caresolutions.be/fr/service-desk/"


@tagged("standard", "at_install")
class TestNoUrlFabrication(BaseCase):
    """Regression guard: every crawled URL must trace back to the site."""

    def test_absolute_href_returned_verbatim(self):
        # the real case behind the "phantom 404" report: the audited site
        # hard-codes this dead URL in its own body copy
        href = "https://www.caresolutions.be/fr/contact/"
        self.assertEqual(normalize_link(PAGE, href, HOST), href)

    def test_root_relative_href_never_gains_the_section_prefix(self):
        self.assertEqual(
            normalize_link(PAGE, "/contact/", HOST),
            "https://www.caresolutions.be/contact/")

    def test_path_relative_href_resolves_against_the_page(self):
        self.assertEqual(
            normalize_link(PAGE, "contact/", HOST),
            "https://www.caresolutions.be/fr/service-desk/contact/")

    def test_off_site_link_is_dropped(self):
        self.assertIsNone(normalize_link(PAGE, "https://google.com/x", HOST))

    def test_www_and_bare_host_are_the_same_site(self):
        self.assertTrue(same_site("www.lplg.eu", "lplg.eu"))
        self.assertFalse(same_site("lplg.eu", "notlplg.eu"))

    def test_non_http_scheme_is_dropped(self):
        for href in ("mailto:a@b.c", "tel:+32473", "javascript:void(0)"):
            self.assertIsNone(normalize_link(PAGE, href, HOST))


@tagged("standard", "at_install")
class TestRootPrefix(BaseCase):
    """A site record naming a section must not audit the whole domain."""

    def test_bare_domain_means_everything(self):
        for root in ("https://lplg.eu", "https://lplg.eu/"):
            self.assertEqual(root_prefix(root), "/")

    def test_section_root(self):
        self.assertEqual(
            root_prefix("https://www.caresolutions.be/fr/"), "/fr/")

    def test_file_root_uses_its_directory(self):
        self.assertEqual(
            root_prefix("https://example.com/fr/index.html"), "/fr/")

    def test_prefix_matching_is_slash_insensitive(self):
        self.assertTrue(in_prefix("https://x.be/fr", "/fr/"))
        self.assertTrue(in_prefix("https://x.be/fr/", "/fr/"))
        self.assertTrue(in_prefix("https://x.be/fr/contact/", "/fr/"))

    def test_prefix_does_not_match_a_longer_word(self):
        # a naive startswith("/fr") would wrongly swallow the whole section
        self.assertFalse(in_prefix("https://x.be/french/", "/fr/"))
        self.assertFalse(in_prefix("https://x.be/frozen", "/fr/"))

    def test_bare_domain_prefix_is_a_no_op(self):
        self.assertTrue(in_prefix("https://x.be/anything/at/all", "/"))

    def test_link_outside_the_section_is_not_queued(self):
        self.assertIsNone(
            normalize_link(PAGE, "/contact/", HOST, "/fr/"))

    def test_link_inside_the_section_is_kept(self):
        # the fix must NOT hide the genuine broken link that started this
        href = "https://www.caresolutions.be/fr/contact/"
        self.assertEqual(normalize_link(PAGE, href, HOST, "/fr/"), href)


@tagged("standard", "at_install")
class TestRequestableUrls(BaseCase):
    """A decorated href must become an honest 404, not a stack trace."""

    def test_invisible_marks_are_stripped(self):
        self.assertEqual(
            _requestable("https://x.be/contact/‎"),
            "https://x.be/contact/")

    def test_truncation_ellipsis_is_percent_encoded(self):
        result = _requestable("https://x.be/actualites…")
        self.assertEqual(result, "https://x.be/actualites%E2%80%A6")
        result.encode("ascii")  # urlopen must be able to send it

    def test_accented_path_is_encoded(self):
        self.assertEqual(
            _requestable("https://x.be/santé/"), "https://x.be/sant%C3%A9/")

    def test_plain_ascii_url_is_untouched(self):
        url = "https://x.be/a/b?c=d&e=f"
        self.assertEqual(_requestable(url), url)

    def test_normalize_link_yields_only_sendable_urls(self):
        out = normalize_link(PAGE, "/actualites…", HOST)
        self.assertIsNotNone(out)
        out.encode("ascii")


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
