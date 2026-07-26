# -*- coding: utf-8 -*-
"""Pure-stdlib SEO crawl engine — no Odoo import, testable standalone.

- fetch_page(url)   analyze one page (fetch + parse + on-page issues + score)
- crawl(root, ...)  multi-page site crawl (sitemap.xml + internal links, BFS)
- analyze_site(pages)  cross-page issues (duplicates, errors, noindex)
"""
import gzip
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

USER_AGENT = "SEO-Suite-Bot/0.1"
THIN_CONTENT_WORDS = 200
TITLE_MIN, TITLE_MAX = 20, 60
META_DESC_MAX = 160
MAX_BYTES = 3_000_000
DEFAULT_DELAY = 0.25  # polite pause between requests (seconds)
MAX_SITEMAP_URLS = 500

# Issue severities and their score penalty (score = 100 - sum of penalties).
SEVERITY_WEIGHT = {"critical": 25, "warning": 10, "info": 5}
# Issue categories — stable keys shared with the Odoo models.
CATEGORIES = ("title", "meta", "headings", "content", "images", "links",
              "technical")

# Never enqueue obvious non-page resources.
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".zip", ".rar", ".7z", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".mp3", ".mp4", ".avi", ".mov", ".woff",
    ".woff2", ".ttf", ".eot", ".xml", ".rss",
)


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
        self.links = []  # raw href values of <a> tags
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
            href = a["href"].strip()
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self.links.append(href)
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


def fetch(url, timeout=15):
    """GET a URL. Returns {status, final_url, body, content_type, is_html, error}."""
    result = {
        "status": 0, "final_url": url, "body": "",
        "content_type": "", "is_html": False, "error": "",
    }
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["status"] = resp.status
            result["final_url"] = resp.geturl()
            raw = resp.read(MAX_BYTES)
            if resp.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            ctype = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset() or "utf-8"
            result["content_type"] = ctype
            result["is_html"] = ctype in ("text/html", "application/xhtml+xml")
            result["body"] = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        result["final_url"] = e.url or url
    except urllib.error.URLError as e:
        result["error"] = str(e.reason)
    except Exception as e:  # noqa: BLE001 — timeout, bad charset, etc.
        result["error"] = str(e)
    return result


def _bare_host(netloc):
    host = netloc.lower().rsplit("@", 1)[-1]
    return host[4:] if host.startswith("www.") else host


def same_site(netloc_a, netloc_b):
    """True when two hosts are the same site (www-insensitive)."""
    return _bare_host(netloc_a) == _bare_host(netloc_b)


def normalize_link(base_url, href, site_netloc):
    """Absolute crawlable same-site URL (fragment stripped), or None."""
    absolute = urldefrag(urljoin(base_url, href.strip()))[0]
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    if not same_site(parts.netloc, site_netloc):
        return None
    if parts.path.lower().endswith(SKIP_EXTENSIONS):
        return None
    return absolute


def _norm_for_compare(url):
    parts = urlsplit(urldefrag(url)[0])
    path = parts.path.rstrip("/") or "/"
    return (parts.netloc.lower(), path, parts.query)


def _issue(severity, category, message):
    return {"severity": severity, "category": category, "message": message}


def page_issues(page):
    """On-page SEO issues for one fetched page.

    Returns a list of dicts {"severity", "category", "message"}.
    """
    if page["error"]:
        return [_issue("critical", "technical",
                       "Crawl error: %s" % page["error"])]
    if page["status"] >= 400:
        return [_issue("critical", "technical", "HTTP %d" % page["status"])]
    if not page["is_html"]:
        return []
    issues = []
    title = page["title"]
    desc = page["meta_description"]
    if not title:
        issues.append(_issue("critical", "title", "Missing title"))
    elif len(title) > TITLE_MAX:
        issues.append(_issue("warning", "title",
                             "Title too long (%d chars)" % len(title)))
    elif len(title) < TITLE_MIN:
        issues.append(_issue("warning", "title",
                             "Title too short (%d chars)" % len(title)))
    if not desc:
        issues.append(_issue("warning", "meta", "Missing meta description"))
    elif len(desc) > META_DESC_MAX:
        issues.append(_issue("warning", "meta",
                             "Meta description too long (%d chars)" % len(desc)))
    if len(page["h1"]) == 0:
        issues.append(_issue("warning", "headings", "No H1"))
    elif len(page["h1"]) > 1:
        issues.append(_issue("warning", "headings",
                             "%d H1 tags (only one recommended)" % len(page["h1"])))
    if "noindex" in page["meta_robots"].lower():
        issues.append(_issue("critical", "technical",
                             "Page is noindex (not indexable)"))
    canonical = page["canonical"]
    if canonical:
        target = urljoin(page["final_url"], canonical)
        if _norm_for_compare(target) != _norm_for_compare(page["final_url"]):
            issues.append(_issue("info", "technical",
                                 "Canonicalized to another URL (%s)" % canonical))
    if page["word_count"] < THIN_CONTENT_WORDS:
        issues.append(_issue("warning", "content",
                             "Thin content (%d words)" % page["word_count"]))
    if page["images_without_alt"]:
        issues.append(_issue("warning", "images",
                             "%d image(s) without alt attribute"
                             % page["images_without_alt"]))
    return issues


def issues_text(issues):
    """Plain-text one-line-per-issue rendering of structured issues."""
    return "\n".join(i["message"] for i in issues)


def page_score(page):
    """Naive 0-100 score: 100 minus a severity-weighted penalty per issue."""
    if page["error"] or page["status"] >= 400:
        return 0
    penalty = sum(SEVERITY_WEIGHT[i["severity"]] for i in page["issues"])
    return max(0, 100 - penalty)


def fetch_page(url, timeout=15):
    """Fetch and analyze one page. Returns a flat dict of SEO signals."""
    f = fetch(url, timeout=timeout)
    page = {
        "url": url,
        "status": f["status"],
        "final_url": f["final_url"] or url,
        "content_type": f["content_type"],
        "is_html": f["is_html"],
        "error": f["error"],
        "title": "", "meta_description": "", "meta_robots": "", "canonical": "",
        "h1": [], "word_count": 0, "internal_links": 0, "external_links": 0,
        "images": 0, "images_without_alt": 0, "links": [],
    }
    if f["is_html"] and f["body"] and not f["error"] and 0 < f["status"] < 400:
        parser = SeoPageParser()
        try:
            parser.feed(f["body"])
        except Exception:  # noqa: BLE001 — badly broken HTML
            pass
        page.update({
            "title": (parser.title or "").strip(),
            "meta_description": (parser.meta_description or "").strip(),
            "meta_robots": (parser.meta_robots or "").strip(),
            "canonical": (parser.canonical or "").strip(),
            "h1": parser.h1,
            "word_count": parser.word_count,
            "images": parser.images,
            "images_without_alt": parser.images_without_alt,
            "links": parser.links,
        })
        site_netloc = urlsplit(page["final_url"]).netloc
        internal = external = 0
        for href in parser.links:
            parts = urlsplit(urljoin(page["final_url"], href))
            if parts.scheme not in ("http", "https"):
                continue
            if same_site(parts.netloc, site_netloc):
                internal += 1
            else:
                external += 1
        page["internal_links"] = internal
        page["external_links"] = external
    page["issues"] = page_issues(page)
    page["score"] = page_score(page)
    return page


def load_robots(origin, timeout=10):
    """Fetch <origin>/robots.txt. Returns (RobotFileParser or None, [sitemap urls])."""
    f = fetch(origin.rstrip("/") + "/robots.txt", timeout=timeout)
    if f["status"] != 200 or not f["body"]:
        return None, []
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(f["body"].splitlines())
    return rp, list(rp.site_maps() or [])


def _sitemap_locs(xml_text):
    """(is_index, [loc urls]) from a sitemap/sitemapindex document."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return False, []
    is_index = root.tag.lower().endswith("sitemapindex")
    locs = [
        el.text.strip()
        for el in root.iter()
        if el.tag.lower().endswith("loc") and el.text and el.text.strip()
    ]
    return is_index, locs


def discover_sitemap_urls(origin, robots_sitemaps=None, timeout=10):
    """Collect page URLs from the site's sitemap(s)."""
    candidates = list(robots_sitemaps or []) or [origin.rstrip("/") + "/sitemap.xml"]
    urls, seen_maps = [], set()
    while candidates and len(urls) < MAX_SITEMAP_URLS and len(seen_maps) < 10:
        sm_url = candidates.pop(0)
        if sm_url in seen_maps:
            continue
        seen_maps.add(sm_url)
        f = fetch(sm_url, timeout=timeout)
        if f["status"] != 200 or not f["body"]:
            continue
        is_index, locs = _sitemap_locs(f["body"])
        if is_index:
            candidates.extend(locs)
        else:
            urls.extend(locs)
    return urls[:MAX_SITEMAP_URLS]


def crawl(root_url, max_pages=30, use_sitemap=True, follow_links=True,
          delay=DEFAULT_DELAY, timeout=15):
    """Crawl a site starting at root_url.

    Returns {"pages": [page dicts], "discovered": int, "disallowed": int,
    "sitemap_urls": int, "site_netloc": str}.
    """
    root_url = (root_url or "").strip()
    if not root_url.startswith(("http://", "https://")):
        root_url = "https://" + root_url

    root_page = fetch_page(root_url, timeout=timeout)
    root_page["source"] = "root"
    pages = [root_page]

    base = urlsplit(root_page["final_url"] or root_url)
    site_netloc = base.netloc
    origin = "%s://%s" % (base.scheme or "https", base.netloc)
    seen = {root_url, root_page["final_url"]}

    if root_page["error"] and not root_page["status"]:
        return {"pages": pages, "discovered": 1, "disallowed": 0,
                "sitemap_urls": 0, "site_netloc": site_netloc}

    rp, robots_sitemaps = load_robots(origin)

    queue = []

    def enqueue(base_url, hrefs, source):
        for href in hrefs:
            normalized = normalize_link(base_url, href, site_netloc)
            if normalized and normalized not in seen:
                seen.add(normalized)
                queue.append((normalized, source))

    sitemap_count = 0
    if use_sitemap:
        sitemap_urls = discover_sitemap_urls(origin, robots_sitemaps)
        sitemap_count = len(sitemap_urls)
        enqueue(origin + "/", sitemap_urls, "sitemap")
    if follow_links:
        enqueue(root_page["final_url"], root_page["links"], "link")

    disallowed = 0
    while queue and len(pages) < max_pages:
        url, source = queue.pop(0)
        if rp and not rp.can_fetch(USER_AGENT, url):
            disallowed += 1
            continue
        if delay:
            time.sleep(delay)
        page = fetch_page(url, timeout=timeout)
        page["source"] = source
        pages.append(page)
        if follow_links and page["is_html"]:
            enqueue(page["final_url"], page["links"], "link")

    return {
        "pages": pages,
        "discovered": len(seen),
        "disallowed": disallowed,
        "sitemap_urls": sitemap_count,
        "site_netloc": site_netloc,
    }


def analyze_site(pages):
    """Cross-page issues over a crawl result (list of strings)."""
    issues = []
    ok = [p for p in pages
          if p["is_html"] and not p["error"] and 0 < p["status"] < 400]

    errors = [p for p in pages if p["error"] or p["status"] >= 400]
    for p in errors:
        label = ("HTTP %d" % p["status"]) if p["status"] else p["error"]
        issues.append("Page in error: %s (%s)" % (p["url"], label))

    by_title = {}
    for p in ok:
        if p["title"]:
            by_title.setdefault(p["title"], []).append(p)
    for title, group in by_title.items():
        if len(group) > 1:
            issues.append(
                'Duplicate title on %d pages ("%s"): %s'
                % (len(group), title[:70],
                   ", ".join(p["url"] for p in group))
            )

    by_desc = {}
    for p in ok:
        if p["meta_description"]:
            by_desc.setdefault(p["meta_description"], []).append(p)
    for desc, group in by_desc.items():
        if len(group) > 1:
            issues.append(
                'Duplicate meta description on %d pages ("%s…"): %s'
                % (len(group), desc[:60],
                   ", ".join(p["url"] for p in group))
            )

    noindex = [p for p in ok if "noindex" in p["meta_robots"].lower()]
    if noindex:
        issues.append(
            "%d page(s) blocked by noindex: %s"
            % (len(noindex), ", ".join(p["url"] for p in noindex))
        )
    return issues
