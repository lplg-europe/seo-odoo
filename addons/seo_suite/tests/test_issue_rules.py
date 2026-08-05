# -*- coding: utf-8 -*-
"""Issue rules: no obsolete finding, no defect charged twice.

An audit is only worth its findings. Two failures matter more than a
missed detection: reporting a risk that no longer exists, and counting
one defect as two. Both inflate the total and cost the agency its
credibility when a client checks.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import BaseCase, tagged

from ..crawler import LOW_TEXT_RATIO, THIN_CONTENT_WORDS, page_issues


def page(**overrides):
    """A clean HTML page; each test breaks exactly what it measures."""
    base = {
        "url": "https://x.be/p", "final_url": "https://x.be/p",
        "status": 200, "error": "", "is_html": True,
        "title": "A perfectly reasonable page title here",
        "meta_description": (
            "A meta description of the right length, long enough to be "
            "kept by Google and short enough not to be cut off midway."),
        "h1": ["One single H1"], "headings": [(1, "Title"), (2, "Sub")],
        "word_count": 800, "text_ratio": 40,
        "images": 2, "images_without_alt": 0,
        "internal_links": 5, "external_links": 1,
        "canonical": "https://x.be/p", "meta_robots": "",
        "x_robots_tag": "", "header_canonical": "",
        "lang": "fr", "viewport": True, "og": "complete",
        "schema_count": 1, "schema_types": ["Organization"],
        "mixed_content": 0, "unsafe_blank_links": 0,
        "redirect_count": 0, "response_time": 0.3, "is_https": True,
        "hreflangs": [], "click_depth": 1, "hsts": True,
        "inbound_links": 3,
    }
    base.update(overrides)
    return base


def messages(**overrides):
    return [i["message"] for i in page_issues(page(**overrides))]


@tagged("standard", "at_install")
class TestObsoleteRules(BaseCase):
    """A finding that is no longer true must not be reported."""

    def test_blank_links_without_noopener_are_not_reported(self):
        # Chrome 88 / Firefox 79 / Safari 12.1 apply noopener implicitly
        # since 2021: tab-nabbing is unreachable, so flagging it once per
        # page only inflated the audit.
        found = messages(unsafe_blank_links=12)
        self.assertFalse([m for m in found if "noopener" in m], found)

    def test_clean_page_reports_nothing(self):
        self.assertEqual(messages(), [])


@tagged("standard", "at_install")
class TestNoDoubleCharging(BaseCase):
    """Thin content and low text ratio are one defect, not two."""

    def test_thin_page_with_low_ratio_raises_a_single_content_issue(self):
        found = [i for i in page_issues(page(word_count=171, text_ratio=3))
                 if i["category"] == "content"]
        self.assertEqual(len(found), 1, found)
        # the ratio still has to reach the reader, inside that one issue
        self.assertIn("171 words", found[0]["message"])
        self.assertIn("3%", found[0]["message"])

    def test_thin_page_with_healthy_ratio_does_not_mention_the_ratio(self):
        found = [i for i in page_issues(page(word_count=171, text_ratio=45))
                 if i["category"] == "content"]
        self.assertEqual(len(found), 1, found)
        self.assertNotIn("%", found[0]["message"])

    def test_long_page_buried_in_markup_still_reports_the_ratio(self):
        # enough words but drowned in markup: the writing is fine, the
        # template is not — that is a real and distinct finding
        found = [i for i in page_issues(
            page(word_count=THIN_CONTENT_WORDS + 500, text_ratio=2))
            if i["category"] == "content"]
        self.assertEqual(len(found), 1, found)
        self.assertIn("Low text/HTML ratio", found[0]["message"])

    def test_thin_threshold_boundary_is_not_flagged(self):
        found = [i for i in page_issues(
            page(word_count=THIN_CONTENT_WORDS, text_ratio=LOW_TEXT_RATIO))
            if i["category"] == "content"]
        self.assertEqual(found, [])


@tagged("standard", "at_install")
class TestPenaltyIsChargedOnce(BaseCase):
    """The score must reflect the corrected rules."""

    def test_thin_page_loses_one_warning_not_a_warning_plus_an_info(self):
        from ..crawler import SEVERITY_WEIGHT, page_score
        p = page(word_count=171, text_ratio=3)
        p["issues"] = page_issues(p)
        self.assertEqual(
            page_score(p), 100 - SEVERITY_WEIGHT["warning"])


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
