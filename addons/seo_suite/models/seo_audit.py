# -*- coding: utf-8 -*-
"""On-page SEO audit of a URL — pure-stdlib crawl engine."""
import gzip
import urllib.error
import urllib.request
from html.parser import HTMLParser

from odoo import fields, models
from odoo.exceptions import UserError

USER_AGENT = "SEO-Suite-Bot/0.1"
THIN_CONTENT_WORDS = 200


class SeoPageParser(HTMLParser):
    """Minimal HTML parser (stdlib) — extracts on-page SEO signals."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self.meta_description = None
        self.meta_robots = None
        self.canonical = None
        self.h1 = []
        self._in_h1 = False
        self._h1_buf = ""
        self.images = 0
        self.images_without_alt = 0
        self.internal_links = 0
        self.external_links = 0
        self.word_count = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description":
                self.meta_description = a.get("content")
            elif name == "robots":
                self.meta_robots = a.get("content")
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "h1":
            self._in_h1 = True
            self._h1_buf = ""
        elif tag == "a" and a.get("href"):
            href = a["href"]
            if href.startswith(("http://", "https://")):
                self.external_links += 1
            elif not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self.internal_links += 1
        elif tag == "img":
            self.images += 1
            if not a.get("alt"):
                self.images_without_alt += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            if self._skip:
                self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            text = self._h1_buf.strip()
            if text:
                self.h1.append(text)

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_h1:
            self._h1_buf += data
        stripped = data.strip()
        if stripped:
            self.word_count += len(stripped.split())


class SeoAudit(models.Model):
    _name = "seo.audit"
    _description = "SEO Audit of a page"
    _order = "audit_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="URL", required=True)
    audit_date = fields.Datetime(string="Analyzed on", readonly=True)
    status_code = fields.Integer(string="HTTP status", readonly=True)
    final_url = fields.Char(string="Final URL", readonly=True)
    title = fields.Char(string="Title", readonly=True)
    title_length = fields.Integer(string="Title length", readonly=True)
    meta_description = fields.Text(string="Meta description", readonly=True)
    meta_description_length = fields.Integer(string="Meta length", readonly=True)
    meta_robots = fields.Char(string="Meta robots", readonly=True)
    canonical = fields.Char(string="Canonical", readonly=True)
    h1 = fields.Text(string="H1", readonly=True)
    h1_count = fields.Integer(string="H1 count", readonly=True)
    word_count = fields.Integer(string="Word count", readonly=True)
    internal_links = fields.Integer(string="Internal links", readonly=True)
    external_links = fields.Integer(string="External links", readonly=True)
    images = fields.Integer(string="Images", readonly=True)
    images_without_alt = fields.Integer(string="Images without alt", readonly=True)
    issues = fields.Text(string="Detected issues", readonly=True)
    issue_count = fields.Integer(string="Issue count", readonly=True)

    def action_run_audit(self):
        for rec in self:
            rec._run_audit()
        return True

    def _run_audit(self):
        self.ensure_one()
        url = (self.name or "").strip()
        if not url:
            raise UserError("Please enter a URL to audit.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                final_url = resp.geturl()
                raw = resp.read(3_000_000)
                if resp.headers.get("Content-Encoding") == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                charset = resp.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            self.write({
                "status_code": e.code,
                "audit_date": fields.Datetime.now(),
                "issues": "HTTP %s" % e.code,
                "issue_count": 1,
            })
            return
        except Exception as e:  # noqa: BLE001
            raise UserError("Crawl failed: %s" % e)

        parser = SeoPageParser()
        try:
            parser.feed(html)
        except Exception:  # noqa: BLE001
            pass

        title = (parser.title or "").strip()
        desc = (parser.meta_description or "").strip()
        issues = []
        if not title:
            issues.append("Missing title")
        elif len(title) > 60:
            issues.append("Title too long (%d chars)" % len(title))
        elif len(title) < 20:
            issues.append("Title too short (%d chars)" % len(title))
        if not desc:
            issues.append("Missing meta description")
        elif len(desc) > 160:
            issues.append("Meta description too long (%d chars)" % len(desc))
        if len(parser.h1) == 0:
            issues.append("No H1")
        elif len(parser.h1) > 1:
            issues.append("%d H1 tags (only one recommended)" % len(parser.h1))
        if parser.meta_robots and "noindex" in parser.meta_robots.lower():
            issues.append("Page is noindex (not indexable)")
        if parser.word_count < THIN_CONTENT_WORDS:
            issues.append("Thin content (%d words)" % parser.word_count)
        if parser.images_without_alt:
            issues.append("%d image(s) without alt attribute" % parser.images_without_alt)

        self.write({
            "audit_date": fields.Datetime.now(),
            "status_code": status,
            "final_url": final_url,
            "title": title,
            "title_length": len(title),
            "meta_description": desc,
            "meta_description_length": len(desc),
            "meta_robots": parser.meta_robots or "",
            "canonical": parser.canonical or "",
            "h1": "\n".join(parser.h1),
            "h1_count": len(parser.h1),
            "word_count": parser.word_count,
            "internal_links": parser.internal_links,
            "external_links": parser.external_links,
            "images": parser.images,
            "images_without_alt": parser.images_without_alt,
            "issues": "\n".join(issues) if issues else "No issues detected",
            "issue_count": len(issues),
        })
