# -*- coding: utf-8 -*-
"""Domain diagnosis logic. Pure functions, no network, no database.

The snapshots below replay the real case that motivated dns_check.py: a
site whose www host worked while https://<bare> refused connections,
because the registrar's redirect service only listens on port 80. The
tests pin that this exact situation is reported, and that healthy or
differently-broken setups are not confused with it.
"""
import unittest  # noqa: F401 — standalone runner entry point below

from odoo.tests import BaseCase, tagged

from ..dns_check import (
    evaluate, merge_domain_lines, provider_name, registrable_domain)


def snapshot(**overrides):
    """A healthy www-canonical site; tests override what they break."""
    base = {
        "canonical": "www.example.be",
        "bare": "example.be",
        "www_host": "www.example.be",
        "ns": ["dns16.ovh.net", "ns16.ovh.net"],
        "mx": ["mx1.mail.ovh.net"],
        "apex_a": ["213.186.33.5"],
        "www_cname": "site.odoo.com",
        "spf": "v=spf1 include:mx.ovh.com ~all",
        "dmarc": "v=DMARC1; p=none;",
        "dnssec": True,
        "rdap": {"registrar": "OVH", "created": "2020-04-15"},
        "probes": {
            "http://example.be/": {
                "status": 301, "location": "https://www.example.be",
                "error": ""},
            "https://example.be/": {
                "status": 301, "location": "https://www.example.be",
                "error": ""},
            "http://www.example.be/": {
                "status": 301, "location": "https://www.example.be/",
                "error": ""},
            "https://www.example.be/": {
                "status": 200, "location": "", "error": ""},
        },
    }
    base.update(overrides)
    return base


@tagged("standard", "at_install")
class TestNakedDomainHttps(BaseCase):
    """The motivating case: HTTP-only redirect service on the apex."""

    def test_refused_apex_is_reported_with_the_http_redirect_hint(self):
        snap = snapshot()
        snap["probes"]["https://example.be/"] = {
            "status": 0, "location": "", "error": "refused"}
        issues = evaluate(snap)["issues"]
        hit = [m for m in issues if "https://example.be does not work" in m]
        self.assertEqual(len(hit), 1)
        # the HTTP 301 exists, so the message must say the redirect is
        # there but unreachable for HTTPS-first browsers
        self.assertIn("browsers try HTTPS first", hit[0])

    def test_healthy_site_reports_nothing(self):
        self.assertEqual(evaluate(snapshot())["issues"], [])

    def test_connection_reset_counts_as_broken_https(self):
        # OVH's redirect service alternates between refusing and
        # resetting on port 443; both must be reported the same way
        snap = snapshot()
        snap["probes"]["https://example.be/"] = {
            "status": 0, "location": "", "error": "reset"}
        issues = evaluate(snap)["issues"]
        self.assertTrue(
            any("https://example.be does not work" in m for m in issues))

    def test_unknown_error_label_still_reported(self):
        snap = snapshot()
        snap["probes"]["https://example.be/"] = {
            "status": 0, "location": "", "error": "[WinError 10054] x"}
        issues = evaluate(snap)["issues"]
        self.assertTrue(any("the connection fails" in m for m in issues))

    def test_broken_canonical_dominates(self):
        snap = snapshot()
        snap["probes"]["https://www.example.be/"] = {
            "status": 0, "location": "", "error": "timeout"}
        issues = evaluate(snap)["issues"]
        self.assertTrue(issues)
        self.assertIn("unreachable over HTTPS", issues[0])

    def test_both_variants_serving_content_is_duplicate(self):
        snap = snapshot()
        snap["probes"]["https://example.be/"] = {
            "status": 200, "location": "", "error": ""}
        issues = evaluate(snap)["issues"]
        self.assertTrue(any("two copies" in m for m in issues))

    def test_http_canonical_without_https_redirect(self):
        snap = snapshot()
        snap["probes"]["http://www.example.be/"] = {
            "status": 200, "location": "", "error": ""}
        issues = evaluate(snap)["issues"]
        self.assertTrue(any("redirecting to HTTPS" in m for m in issues))


@tagged("standard", "at_install")
class TestMailRecords(BaseCase):
    def test_missing_spf_and_dmarc_flagged_when_domain_has_mx(self):
        issues = evaluate(snapshot(spf="", dmarc=""))["issues"]
        self.assertTrue(any("SPF" in m for m in issues))
        self.assertTrue(any("DMARC" in m for m in issues))

    def test_no_mx_means_no_mail_findings(self):
        issues = evaluate(snapshot(mx=[], spf="", dmarc=""))["issues"]
        self.assertFalse(any("SPF" in m or "DMARC" in m for m in issues))


@tagged("standard", "at_install")
class TestHelpers(BaseCase):
    def test_provider_recognition(self):
        self.assertEqual(provider_name(["ns16.ovh.net"]), "OVH")
        self.assertEqual(
            provider_name(["dee.ns.cloudflare.com"]), "Cloudflare")

    def test_unknown_provider_falls_back_to_hostname(self):
        self.assertEqual(
            provider_name(["ns1.tiny-host.example."]),
            "ns1.tiny-host.example")

    def test_registrable_domain(self):
        self.assertEqual(
            registrable_domain("www.lesjardinsdescailmont.be"),
            "lesjardinsdescailmont.be")
        self.assertEqual(registrable_domain("shop.example.co.uk"),
                         "example.co.uk")

    def test_summary_contains_the_probe_lines(self):
        summary = evaluate(snapshot())["summary"]
        self.assertIn("Registrar: OVH", summary)
        self.assertIn("https://www.example.be/ : 200", summary)


@tagged("standard", "at_install")
class TestMergeDomainLines(BaseCase):
    """Domain findings replace their previous run, never the crawl's."""

    def test_crawl_lines_survive_and_domain_lines_are_replaced(self):
        existing = "No favicon found\nDomain: old finding"
        merged, count = merge_domain_lines(existing, ["new finding"])
        self.assertEqual(
            merged, "No favicon found\nDomain: new finding")
        self.assertEqual(count, 2)

    def test_placeholder_is_dropped_then_restored(self):
        merged, count = merge_domain_lines("No site-level issues", [])
        self.assertEqual(merged, "No site-level issues")
        self.assertEqual(count, 0)


if __name__ == "__main__":  # standalone: python -m unittest
    unittest.main()
