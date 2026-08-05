# -*- coding: utf-8 -*-
"""Pure-stdlib SEO crawl engine — no Odoo import, testable standalone.

- fetch_page(url)   analyze one page (fetch + parse + on-page issues + score)
- crawl(root, ...)  multi-page site crawl (sitemap.xml + internal links, BFS)
- analyze_site(pages)  cross-page issues (duplicates, errors, noindex)
"""
import gzip
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import deque
from html.parser import HTMLParser
from urllib.parse import (
    quote, urldefrag, urlencode, urljoin, urlsplit, urlunsplit)

USER_AGENT = "SEO-Suite-Bot/0.2"
THIN_CONTENT_WORDS = 300
TITLE_MIN, TITLE_MAX = 20, 60
META_DESC_MAX = 160
MAX_BYTES = 3_000_000
MAX_TEXT_CHARS = 500_000  # cap on text kept for readability/keywords
DEFAULT_DELAY = 0.25  # polite pause between requests (seconds)
MAX_SITEMAP_URLS = 500
SLOW_RESPONSE_S = 1.0  # info issue above this response time
LOW_TEXT_RATIO = 10  # info issue below this text/HTML percentage
REDIRECT_CHAIN_MIN = 2  # warning at this many redirect hops
TOP_KEYWORDS = 10
PAGERANK_DAMPING = 0.85
PAGERANK_ITERATIONS = 10
MAX_LINK_CHECKS = 200  # cap on HEAD requests for the broken-links pass
MAX_REFERRERS = 3  # referring pages remembered per discovered URL
PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Major AI crawlers — checked against robots.txt for GEO/AI visibility.
AI_CRAWLERS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot",
               "Claude-User", "anthropic-ai", "PerplexityBot",
               "Google-Extended", "CCBot", "Meta-ExternalAgent",
               "Bytespider")

# Issue severities and their score penalty (score = 100 - sum of penalties).
SEVERITY_WEIGHT = {"critical": 25, "warning": 10, "info": 5}
# Issue categories — stable keys shared with the Odoo models.
CATEGORIES = ("title", "meta", "headings", "content", "images", "links",
              "social", "performance", "security", "technical")

# Compact stop-word lists for keyword extraction (site content is often
# French or English — both are always applied).
STOPWORDS = frozenset("""
le la les un une des du de d l au aux et ou où mais donc or ni car que qui
quoi dont ne pas plus moins très peu tout tous toute toutes ce cet cette ces
son sa ses leur leurs mon ma mes ton ta tes notre votre nos vos je tu il elle
on nous vous ils elles se sur sous dans par pour avec sans chez vers entre
est sont était être avoir fait faire comme aussi bien encore déjà ici là
the a an and or but if then else when at by for with about against between
into through during before after above below to from up down in out on off
over under again further once here there all any both each few more most
other some such no nor not only own same so than too very can will just
should now is are was were be been being have has had do does did of it its
this that these those you your yours he she they them their what which who
whom
""".split())

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
        self.headings = []  # ordered (level, text) for h1..h6, capped
        self._heading_level = 0
        self._heading_buf = ""
        self.images = 0
        self.images_without_alt = 0
        self.links = []  # raw href values of <a> tags
        self.word_count = 0
        self.lang = ""
        self.viewport = False
        self.has_favicon_link = False
        self.og = {}  # og:title / og:description / og:image -> content
        self.hreflangs = []  # hreflang codes of link rel=alternate
        self.ldjson = []  # raw contents of application/ld+json scripts
        self._in_ldjson = False
        self._ldjson_buf = ""
        self.resource_urls = []  # src/href of img, script, stylesheet, media
        self.unsafe_blank_links = 0  # target=_blank without noopener/noreferrer
        self.text_parts = []  # visible text, capped at MAX_TEXT_CHARS
        self._text_len = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            stype = (a.get("type") or "").lower()
            if "ld+json" in stype:
                self._in_ldjson = True
                self._ldjson_buf = ""
            if a.get("src"):
                self.resource_urls.append(a["src"])
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
            return
        if tag == "html":
            self.lang = (a.get("lang") or "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            prop = (a.get("property") or "").lower()
            if name == "description":
                self.meta_description = a.get("content")
            elif name == "robots":
                self.meta_robots = a.get("content")
            elif name == "viewport":
                self.viewport = True
            elif prop in ("og:title", "og:description", "og:image"):
                self.og[prop] = (a.get("content") or "").strip()
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            href = a.get("href")
            if rel == "canonical":
                self.canonical = href
            elif "icon" in rel:
                self.has_favicon_link = True
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflangs.append(a["hreflang"].strip())
            elif rel == "stylesheet" and href:
                self.resource_urls.append(href)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_level = int(tag[1])
            self._heading_buf = ""
        elif tag == "a":
            href = (a.get("href") or "").strip()
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self.links.append(href)
            if (a.get("target") or "").lower() == "_blank":
                rel = (a.get("rel") or "").lower()
                if "noopener" not in rel and "noreferrer" not in rel:
                    self.unsafe_blank_links += 1
        elif tag == "img":
            self.images += 1
            if not a.get("alt"):
                self.images_without_alt += 1
            src = a.get("src") or a.get("data-src")
            if src:
                self.resource_urls.append(src)
        elif tag in ("iframe", "audio", "video", "source", "embed"):
            if a.get("src"):
                self.resource_urls.append(a["src"])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            if tag == "script" and self._in_ldjson:
                self._in_ldjson = False
                if self._ldjson_buf.strip():
                    self.ldjson.append(self._ldjson_buf)
            if self._skip:
                self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = self._heading_buf.strip()
            if text and len(self.headings) < 200:
                self.headings.append((int(tag[1]), text))
            self._heading_level = 0

    @property
    def h1(self):
        return [text for level, text in self.headings if level == 1]

    @property
    def h2_count(self):
        return sum(1 for level, _ in self.headings if level == 2)

    def handle_data(self, data):
        if self._in_ldjson:
            self._ldjson_buf += data
        if self._skip:
            return
        if self._in_title:
            self.title = (self.title or "") + data
        if self._heading_level:
            self._heading_buf += data
        stripped = data.strip()
        if stripped:
            self.word_count += len(stripped.split())
            if self._text_len < MAX_TEXT_CHARS:
                self.text_parts.append(stripped)
                self._text_len += len(stripped) + 1


_LINK_CANONICAL_RE = re.compile(
    r'<([^>]+)>[^,]*?rel=["\']?canonical', re.IGNORECASE)


def fetch(url, timeout=15):
    """GET a URL. Returns {status, final_url, body, content_type, is_html,
    error, response_time, page_size_kb, redirect_count, redirect_chain,
    x_robots_tag, header_canonical, hsts}."""
    result = {
        "status": 0, "final_url": url, "body": "",
        "content_type": "", "is_html": False, "error": "",
        "response_time": 0.0, "page_size_kb": 0, "redirect_count": 0,
        "x_robots_tag": "", "header_canonical": "", "hsts": False,
    }
    redirects = {"count": 0, "chain": []}

    class _CountingRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirects["count"] += 1
            redirects["chain"].append("[%d] %s" % (code, newurl))
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_CountingRedirectHandler)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )
    started = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as resp:
            result["status"] = resp.status
            result["final_url"] = resp.geturl()
            raw = resp.read(MAX_BYTES)
            result["response_time"] = time.monotonic() - started
            if resp.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            result["page_size_kb"] = round(len(raw) / 1024)
            ctype = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset() or "utf-8"
            result["content_type"] = ctype
            result["is_html"] = ctype in ("text/html", "application/xhtml+xml")
            result["body"] = raw.decode(charset, errors="replace")
            result["x_robots_tag"] = resp.headers.get("X-Robots-Tag") or ""
            result["hsts"] = bool(
                resp.headers.get("Strict-Transport-Security"))
            link_match = _LINK_CANONICAL_RE.search(
                resp.headers.get("Link") or "")
            if link_match:
                result["header_canonical"] = link_match.group(1).strip()
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        result["final_url"] = e.url or url
        result["response_time"] = time.monotonic() - started
    except urllib.error.URLError as e:
        result["error"] = str(e.reason)
    except Exception as e:  # noqa: BLE001 — timeout, bad charset, etc.
        result["error"] = str(e)
    result["redirect_count"] = redirects["count"]
    result["redirect_chain"] = redirects["chain"]
    return result


def _bare_host(netloc):
    host = netloc.lower().rsplit("@", 1)[-1]
    return host[4:] if host.startswith("www.") else host


def same_site(netloc_a, netloc_b):
    """True when two hosts are the same site (www-insensitive)."""
    return _bare_host(netloc_a) == _bare_host(netloc_b)


# Zero-width / bidi marks CMS editors silently paste into hrefs. urlopen
# cannot encode them and raises UnicodeEncodeError, whose text used to end
# up verbatim in a client-facing audit.
_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF]
    + list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)))


def _requestable(url):
    """URL urlopen can actually send, or None.

    Strips invisible marks and percent-encodes non-ASCII so a truncated or
    decorated href becomes an honest 404 instead of a crawler stack trace.
    """
    cleaned = (url or "").translate(_INVISIBLE).strip()
    if not cleaned:
        return None
    try:
        cleaned.encode("ascii")
        return cleaned
    except UnicodeEncodeError:
        pass
    parts = urlsplit(cleaned)
    try:
        netloc = parts.netloc.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    return urlunsplit((
        parts.scheme, netloc, quote(parts.path, safe="/%:@!$&'()*+,;="),
        quote(parts.query, safe="/%:@!$&'()*+,;=?"), ""))


def root_prefix(root_url):
    """Section a crawl root confines the audit to, as a path ending in "/".

    A bare domain gives "/" (crawl everything). A root like
    https://example.com/fr/ gives "/fr/": the site record declares a
    section, so auditing the whole domain would blend other languages
    into the score.
    """
    path = urlsplit(root_url or "").path or "/"
    if not path.endswith("/"):  # .../fr/index.html -> /fr/
        path = path.rsplit("/", 1)[0] + "/"
    return path or "/"


def in_prefix(url, prefix):
    """True when a URL belongs to the crawl's declared section."""
    if not prefix or prefix == "/":
        return True
    path = urlsplit(url).path or "/"
    # trailing-slash insensitive: /fr, /fr/ and /fr/contact all match /fr/,
    # while /french/ correctly does not
    return (path.rstrip("/") + "/").startswith(prefix)


def normalize_link(base_url, href, site_netloc, path_prefix="/"):
    """Absolute crawlable same-site URL (fragment stripped), or None."""
    absolute = urldefrag(urljoin(base_url, href.strip()))[0]
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    if not same_site(parts.netloc, site_netloc):
        return None
    if parts.path.lower().endswith(SKIP_EXTENSIONS):
        return None
    if not in_prefix(absolute, path_prefix):
        return None
    return _requestable(absolute)


def _norm_for_compare(url):
    parts = urlsplit(urldefrag(url)[0])
    path = parts.path.rstrip("/") or "/"
    return (parts.netloc.lower(), path, parts.query)


_VOWELS = set("aeiouyàâäéèêëîïôöùûü")
_WORD_RE = re.compile(r"[a-zà-öø-ÿ][a-zà-öø-ÿ'-]{2,}", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?…]+")


def _count_syllables(word):
    """Heuristic syllable count: vowel groups, minus a final mute e."""
    word = word.lower()
    groups = 0
    previous_vowel = False
    for ch in word:
        is_vowel = ch in _VOWELS
        if is_vowel and not previous_vowel:
            groups += 1
        previous_vowel = is_vowel
    if word.endswith("e") and groups > 1:
        groups -= 1
    return max(1, groups)


def flesch_reading_ease(text):
    """Flesch Reading Ease (0-100-ish) and its label, or (None, "")."""
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    words = _WORD_RE.findall(text)
    if len(words) < 30 or not sentences:
        return None, ""
    syllables = sum(_count_syllables(w) for w in words)
    score = (206.835 - 1.015 * (len(words) / len(sentences))
             - 84.6 * (syllables / len(words)))
    score = round(max(0, min(120, score)))
    for threshold, label in ((90, "Very easy"), (80, "Easy"),
                             (70, "Fairly easy"), (60, "Standard"),
                             (50, "Fairly difficult"), (30, "Difficult")):
        if score >= threshold:
            return score, label
    return score, "Very difficult"


def top_keywords(text, limit=TOP_KEYWORDS):
    """Most frequent significant words: [(word, count), ...]."""
    counts = {}
    for word in _WORD_RE.findall(text.lower()):
        if word not in STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit]


def _schema_types(ldjson_blocks):
    """Distinct @type values found in ld+json blocks."""
    types = []

    def collect(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(x for x in t if isinstance(x, str))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    for block in ldjson_blocks:
        try:
            collect(json.loads(block))
        except (ValueError, TypeError):
            continue
    seen = []
    for t in types:
        if t not in seen:
            seen.append(t)
    return seen


def og_status(og):
    """'complete' / 'partial' / 'missing' for og:title+description+image."""
    have = sum(1 for k in ("og:title", "og:description", "og:image")
               if og.get(k))
    if have == 3:
        return "complete"
    return "partial" if have else "missing"


def _issue(severity, category, message, fix=""):
    return {"severity": severity, "category": category,
            "message": message, "fix": fix}


DEEP_PAGE_DEPTH = 5  # click depth from the homepage triggering an issue


def page_issues(page):
    """On-page SEO issues for one fetched page.

    Returns a list of dicts {"severity", "category", "message", "fix"}.
    """
    if page["error"]:
        loop = "redirect" in page["error"].lower()
        return [_issue(
            "critical", "technical",
            "Redirect loop or too many redirects" if loop
            else "Crawl error: %s" % page["error"],
            "Fix the redirect targets so they resolve to a final page."
            if loop else "Make the URL reachable or remove links to it.")]
    if page["status"] in (403, 429):
        return [_issue("critical", "technical",
                       "Page blocked (HTTP %d — WAF or bot challenge?)"
                       % page["status"],
                       "Allow legitimate crawlers (including search "
                       "engines) through your firewall/CDN rules.")]
    if page["status"] >= 500:
        return [_issue("critical", "technical",
                       "Server error (HTTP %d)" % page["status"],
                       "Fix the server-side error — search engines "
                       "may drop pages that keep failing.")]
    if page["status"] >= 400:
        return [_issue("critical", "technical", "HTTP %d" % page["status"],
                       "Restore the page or redirect (301) it to the "
                       "closest relevant page, and update links to it.")]
    if not page["is_html"]:
        return []
    issues = []
    title = page["title"]
    desc = page["meta_description"]
    if not title:
        issues.append(_issue(
            "critical", "title", "Missing title",
            "Add a unique <title> of 20-60 characters including the "
            "page's main keyword."))
    elif len(title) > TITLE_MAX:
        issues.append(_issue(
            "warning", "title", "Title too long (%d chars)" % len(title),
            "Shorten to about 60 characters so Google does not truncate "
            "it; put the keyword near the start."))
    elif len(title) < TITLE_MIN:
        issues.append(_issue(
            "warning", "title", "Title too short (%d chars)" % len(title),
            "Expand to 20-60 characters with a descriptive keyword — "
            "short titles waste ranking signal."))
    if not desc:
        issues.append(_issue(
            "warning", "meta", "Missing meta description",
            "Write a 140-160 character description that includes the "
            "keyword and gives a reason to click."))
    elif len(desc) > META_DESC_MAX:
        issues.append(_issue(
            "warning", "meta",
            "Meta description too long (%d chars)" % len(desc),
            "Trim to 160 characters or less — Google truncates the rest."))
    if len(page["h1"]) == 0:
        issues.append(_issue(
            "warning", "headings", "No H1",
            "Add exactly one H1 stating what the page is about."))
    elif len(page["h1"]) > 1:
        issues.append(_issue(
            "warning", "headings",
            "%d H1 tags (only one recommended)" % len(page["h1"]),
            "Keep one H1 and demote the others to H2/H3."))
    skip = _heading_skip(page["headings"])
    if skip:
        issues.append(_issue(
            "info", "headings",
            "Heading level skip (H%d follows H%d)" % skip,
            "Keep a logical heading hierarchy — do not jump levels "
            "(H2 after H1, H3 after H2...)."))
    robots_all = "%s %s" % (page["meta_robots"], page["x_robots_tag"])
    if "noindex" in robots_all.lower():
        issues.append(_issue(
            "critical", "technical",
            "Page is noindex (meta robots or X-Robots-Tag)",
            "Remove the noindex directive if this page should rank; "
            "keep it only for pages you want out of Google."))
    canonical = page["canonical"]
    header_canonical = page["header_canonical"]
    if canonical and header_canonical and _norm_for_compare(
            urljoin(page["final_url"], canonical)) != _norm_for_compare(
            urljoin(page["final_url"], header_canonical)):
        issues.append(_issue(
            "warning", "technical",
            "Canonical conflict (HTML says %s, HTTP header says %s)"
            % (canonical, header_canonical),
            "Make the <link rel=canonical> and the Link HTTP header "
            "point to the same URL — conflicting signals are ignored."))
    effective_canonical = canonical or header_canonical
    if effective_canonical:
        target = urljoin(page["final_url"], effective_canonical)
        if _norm_for_compare(target) != _norm_for_compare(page["final_url"]):
            issues.append(_issue(
                "info", "technical",
                "Canonicalized to another URL (%s)" % effective_canonical,
                "Expected for duplicates; if this page should rank on "
                "its own, make it self-canonical."))
    # Thin content and a low text/HTML ratio describe the same page from
    # two angles. Raising both charged one defect twice, so the ratio is
    # reported inside this issue when it applies and never on its own.
    if page["word_count"] < THIN_CONTENT_WORDS:
        ratio = page["text_ratio"]
        thin_ratio = 0 < ratio < LOW_TEXT_RATIO
        issues.append(_issue(
            "warning", "content",
            "Thin content (%d words%s)" % (
                page["word_count"],
                ", %d%% text" % ratio if thin_ratio else ""),
            "Expand the page to 300+ words of genuinely useful content, "
            "or merge it into a stronger page."))
    if page["images_without_alt"]:
        issues.append(_issue(
            "warning", "images",
            "%d image(s) without alt attribute"
            % page["images_without_alt"],
            "Describe each image in its alt attribute — it helps "
            "accessibility and image search."))
    if not page["lang"]:
        issues.append(_issue(
            "warning", "technical", "Missing lang attribute on <html>",
            'Add lang="fr" (or the page language) on the <html> tag.'))
    if not page["viewport"]:
        issues.append(_issue(
            "warning", "technical",
            "No viewport meta tag (not mobile-friendly)",
            'Add <meta name="viewport" content="width=device-width, '
            'initial-scale=1"> — Google indexes mobile-first.'))
    if page["og"] == "missing":
        issues.append(_issue(
            "warning", "social", "No Open Graph tags (poor social sharing)",
            "Add og:title, og:description and og:image so shares on "
            "social networks look good."))
    elif page["og"] == "partial":
        issues.append(_issue(
            "info", "social",
            "Incomplete Open Graph tags (need title, description and image)",
            "Complete the missing og: tags — the image drives most of "
            "the click-through on shares."))
    if not page["schema_types"] and not page["schema_count"]:
        issues.append(_issue(
            "info", "technical", "No structured data (schema.org)",
            "Add JSON-LD structured data (Organization, LocalBusiness, "
            "Article...) to qualify for rich results."))
    if not page["is_https"]:
        issues.append(_issue(
            "warning", "security", "Page served over HTTP",
            "Serve everything over HTTPS and 301-redirect HTTP URLs."))
    if page["mixed_content"]:
        issues.append(_issue(
            "warning", "security",
            "%d insecure http:// resource(s) on an HTTPS page"
            % page["mixed_content"],
            "Load all images/scripts/styles over https:// — browsers "
            "block or flag mixed content."))
    # No issue is raised for target="_blank" without rel="noopener".
    # Chrome 88, Firefox 79 and Safari 12.1 all apply noopener implicitly
    # since 2021, so tab-nabbing is no longer reachable through that path.
    # The count stays on the page dict for anyone auditing legacy browsers,
    # but reporting it inflated audits by one finding per page for a risk
    # that no current browser has.
    if page["is_html"] and page["internal_links"] + page["external_links"] == 0:
        issues.append(_issue(
            "warning", "links", "Dead-end page (no outgoing links)",
            "Link to related pages — dead ends waste link equity and "
            "strand visitors."))
    if page["redirect_count"] >= REDIRECT_CHAIN_MIN:
        issues.append(_issue(
            "warning", "performance",
            "Redirect chain (%d hops) to reach the page"
            % page["redirect_count"],
            "Point links and redirects straight to the final URL — "
            "each hop wastes crawl budget and speed."))
    if page["response_time"] > SLOW_RESPONSE_S:
        issues.append(_issue(
            "info", "performance",
            "Slow response (%.1fs)" % page["response_time"],
            "Aim for under 1s server response: caching, image "
            "optimization, faster hosting."))
    if (0 < page["text_ratio"] < LOW_TEXT_RATIO
            and page["word_count"] >= THIN_CONTENT_WORDS):
        # Only worth its own line when the page has enough words: the
        # markup, not the writing, is what drowns the text.
        issues.append(_issue(
            "info", "content",
            "Low text/HTML ratio (%d%%)" % page["text_ratio"],
            "Reduce markup bloat — the page has enough text, but it is "
            "buried under markup."))
    return issues


def _heading_skip(headings):
    """First (level, previous_level) heading-hierarchy skip, or None."""
    previous = None
    for level, _text in headings:
        if previous is not None and level > previous + 1:
            return (level, previous)
        previous = level
    return None


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
    final_url = f["final_url"] or url
    page = {
        "url": url,
        "status": f["status"],
        "final_url": final_url,
        "content_type": f["content_type"],
        "is_html": f["is_html"],
        "error": f["error"],
        "response_time": round(f["response_time"], 2),
        "page_size_kb": f["page_size_kb"],
        "redirect_count": f["redirect_count"],
        "redirect_chain": f["redirect_chain"],
        "is_https": urlsplit(final_url).scheme == "https",
        "title": "", "meta_description": "", "meta_robots": "", "canonical": "",
        "h1": [], "h2_count": 0, "headings": [], "reading_time": 0,
        "word_count": 0,
        "internal_links": 0, "external_links": 0,
        "inbound_links": 0, "outlink_urls": [],
        "images": 0, "images_without_alt": 0, "links": [],
        "lang": "", "viewport": True, "has_favicon_link": False,
        "og": "missing", "hreflangs": [], "schema_types": [], "schema_count": 0,
        "mixed_content": 0, "unsafe_blank_links": 0,
        "text_ratio": 0, "flesch_score": None, "flesch_label": "",
        "top_keywords": [], "link_score": 0, "text_excerpt": "",
        "x_robots_tag": f["x_robots_tag"],
        "header_canonical": f["header_canonical"],
        "hsts": f["hsts"], "click_depth": None,
    }
    if f["is_html"] and f["body"] and not f["error"] and 0 < f["status"] < 400:
        parser = SeoPageParser()
        try:
            parser.feed(f["body"])
        except Exception:  # noqa: BLE001 — badly broken HTML
            pass
        text = " ".join(parser.text_parts)
        page["text_excerpt"] = text[:8000]
        flesch, flesch_label = flesch_reading_ease(text)
        page.update({
            "title": (parser.title or "").strip(),
            "meta_description": (parser.meta_description or "").strip(),
            "meta_robots": (parser.meta_robots or "").strip(),
            "canonical": (parser.canonical or "").strip(),
            "h1": parser.h1,
            "h2_count": parser.h2_count,
            "headings": parser.headings,
            "reading_time": (parser.word_count + 249) // 250,
            "word_count": parser.word_count,
            "images": parser.images,
            "images_without_alt": parser.images_without_alt,
            "links": parser.links,
            "lang": parser.lang,
            "viewport": parser.viewport,
            "has_favicon_link": parser.has_favicon_link,
            "og": og_status(parser.og),
            "hreflangs": parser.hreflangs,
            "schema_types": _schema_types(parser.ldjson),
            "schema_count": len(parser.ldjson),
            "unsafe_blank_links": parser.unsafe_blank_links,
            "text_ratio": (round(len(text) * 100 / len(f["body"]))
                           if f["body"] else 0),
            "flesch_score": flesch,
            "flesch_label": flesch_label,
            "top_keywords": top_keywords(text),
        })
        site_netloc = urlsplit(final_url).netloc
        internal = external = 0
        for href in parser.links:
            parts = urlsplit(urljoin(final_url, href))
            if parts.scheme not in ("http", "https"):
                continue
            if same_site(parts.netloc, site_netloc):
                internal += 1
            else:
                external += 1
        page["internal_links"] = internal
        page["external_links"] = external
        if page["is_https"]:
            page["mixed_content"] = sum(
                1 for res in parser.resource_urls
                if res.strip().lower().startswith("http://"))
    page["issues"] = page_issues(page)
    page["score"] = page_score(page)
    return page


def check_url(url, timeout=10):
    """Lightweight availability check: HEAD, falling back to GET on 405.

    Returns (status, error) without downloading the body.
    """
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(
            url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, ""
        except urllib.error.HTTPError as e:
            if e.code == 405 and method == "HEAD":
                continue
            return e.code, ""
        except urllib.error.URLError as e:
            return 0, str(e.reason)
        except Exception as e:  # noqa: BLE001
            return 0, str(e)
    return 0, "unreachable"


def pagespeed(url, api_key=None, strategy="mobile", timeout=90):
    """Google PageSpeed Insights v5 scores for one URL.

    Returns {"performance", "accessibility", "best_practices", "seo" (0-100),
    "lcp", "cls", "tbt" (display strings), "error"}. Works without an API key
    for occasional calls; a (free) key raises the quota.
    """
    result = {"performance": 0, "accessibility": 0, "best_practices": 0,
              "seo": 0, "lcp": "", "cls": "", "tbt": "", "fcp": "",
              "speed_index": "", "dom_size": 0, "total_weight_kb": 0,
              "render_blocking": 0, "long_tasks": 0, "error": ""}
    params = [("url", url), ("strategy", strategy)]
    params += [("category", c) for c in
               ("performance", "accessibility", "best-practices", "seo")]
    if api_key:
        params.append(("key", api_key))
    req = urllib.request.Request(
        PSI_ENDPOINT + "?" + urlencode(params),
        headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8"))[
                "error"]["message"][:200]
        except Exception:  # noqa: BLE001
            pass
        result["error"] = "PageSpeed API HTTP %d%s" % (
            e.code, ": %s" % detail if detail else "")
        return result
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
        return result

    result.update(parse_pagespeed(data))
    return result


def parse_pagespeed(data):
    """Category scores + key Lighthouse audits from a PSI v5 response."""
    parsed = {}
    lighthouse = data.get("lighthouseResult") or {}
    categories = lighthouse.get("categories") or {}
    for key, category_name in (("performance", "performance"),
                               ("accessibility", "accessibility"),
                               ("best_practices", "best-practices"),
                               ("seo", "seo")):
        score = (categories.get(category_name) or {}).get("score")
        parsed[key] = round(score * 100) if score is not None else 0
    audits = lighthouse.get("audits") or {}
    for key, audit_name in (("lcp", "largest-contentful-paint"),
                            ("cls", "cumulative-layout-shift"),
                            ("tbt", "total-blocking-time"),
                            ("fcp", "first-contentful-paint"),
                            ("speed_index", "speed-index")):
        parsed[key] = (audits.get(audit_name) or {}).get("displayValue") or ""
    dom = (audits.get("dom-size") or {}).get("numericValue")
    parsed["dom_size"] = int(dom) if dom else 0
    weight = (audits.get("total-byte-weight") or {}).get("numericValue")
    parsed["total_weight_kb"] = round(weight / 1024) if weight else 0
    for key, audit_name in (("render_blocking", "render-blocking-resources"),
                            ("long_tasks", "long-tasks")):
        details = (audits.get(audit_name) or {}).get("details") or {}
        parsed[key] = len(details.get("items") or [])
    return parsed


def internal_link_graph(pages, site_netloc=None):
    """Adjacency of the crawled pages over their internal links.

    Returns (ok_pages, outlinks) where outlinks[i] is the set of indexes
    page i links to. Built once and shared by the PageRank, the click
    depths and the internal-linking recommendations — the three of them
    used to rebuild the very same index independently.
    """
    ok = [p for p in pages
          if p["is_html"] and not p["error"] and 0 < p["status"] < 400]
    if not ok:
        return [], []
    if site_netloc is None:
        site_netloc = urlsplit(ok[0]["final_url"]).netloc
    index = {}
    for i, page in enumerate(ok):
        index.setdefault(page["url"], i)
        index.setdefault(page["final_url"], i)
    outlinks = []
    for i, page in enumerate(ok):
        targets = set()
        for href in page["links"]:
            normalized = normalize_link(page["final_url"], href, site_netloc)
            j = index.get(normalized)
            if j is not None:
                targets.add(j)
        outlinks.append(targets)
    return ok, outlinks


def compute_link_graph(pages, site_netloc=None):
    """Store the internal link graph on each page.

    Sets page["inbound_links"] (how many crawled pages link to it) and
    page["outlink_urls"] (the final URLs it links to) so the audit can
    recommend "add a link from X to Y" without re-crawling.
    """
    ok, outlinks = internal_link_graph(pages, site_netloc)
    if not ok:
        return
    inbound = [0] * len(ok)
    for i, targets in enumerate(outlinks):
        for j in targets:
            if j != i:
                inbound[j] += 1
    for i, page in enumerate(ok):
        page["inbound_links"] = inbound[i]
        page["outlink_urls"] = sorted(
            ok[j]["final_url"] for j in outlinks[i] if j != i)


def compute_link_scores(pages, site_netloc=None):
    """Internal PageRank over the crawled pages, normalized 1-100.

    Follows the classic formulation: damping 0.85, 10 iterations, links to
    non-crawled or self URLs ignored. Sets page["link_score"] in place.
    """
    ok, outlinks = internal_link_graph(pages, site_netloc)
    if not ok:
        return
    n = len(ok)
    scores = [1.0 / n] * n
    for _ in range(PAGERANK_ITERATIONS):
        fresh = [(1 - PAGERANK_DAMPING) / n] * n
        for i, targets in enumerate(outlinks):
            real = [j for j in targets if j != i]  # a self-link votes nothing
            if real:
                share = PAGERANK_DAMPING * scores[i] / len(real)
                for j in real:
                    fresh[j] += share
        scores = fresh
    lo, hi = min(scores), max(scores)
    for page, score in zip(ok, scores):
        page["link_score"] = (
            100 if hi == lo else round(1 + 99 * (score - lo) / (hi - lo)))


def compute_click_depths(pages):
    """BFS click depth from the crawl root over the internal link graph.

    Sets page["click_depth"] (None = not reachable by links, e.g. found
    only in the sitemap) and appends a deep-page issue when >= 5 clicks.
    """
    ok, adjacency = internal_link_graph(pages)
    if not ok or pages[0] is not ok[0]:
        return  # no usable root to measure from
    depths = {0: 0}
    queue = deque([0])
    while queue:
        i = queue.popleft()
        for j in adjacency[i]:
            if j not in depths:
                depths[j] = depths[i] + 1
                queue.append(j)
    for i, page in enumerate(ok):
        page["click_depth"] = depths.get(i)
        if (page["click_depth"] or 0) >= DEEP_PAGE_DEPTH:
            page["issues"].append(_issue(
                "info", "links",
                "Deep page (%d clicks from the homepage)"
                % page["click_depth"],
                "Surface important pages within 3 clicks of the homepage "
                "via menus or internal links."))
            page["score"] = page_score(page)


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


def progress_message(done, total, elapsed):
    """Human progress line with a measured time estimate.

    The estimate comes from the observed pace, not a guess: after `done`
    pages in `elapsed` seconds, the remaining `total - done` pages will
    take about the same per-page time. `total` is itself a moving target
    while the frontier grows, which is why the text says "about".
    """
    if done <= 0 or elapsed <= 0:
        return "Crawling…"
    remaining = max(total - done, 0) * (elapsed / done)
    if remaining >= 90:
        eta = "about %d min left" % round(remaining / 60.0)
    elif remaining >= 5:
        eta = "about %d s left" % round(remaining)
    else:
        eta = "almost done"
    return "%d/%d pages — %s" % (done, total, eta)


def crawl(root_url, max_pages=30, use_sitemap=True, follow_links=True,
          check_links=False, delay=DEFAULT_DELAY, timeout=15, progress=None):
    """Crawl a site starting at root_url.

    Returns {"pages": [page dicts], "discovered": int, "disallowed": int,
    "sitemap_urls": int, "site_netloc": str, "favicon_ok": bool,
    "broken_links": [{"url", "status", "sources"}], "checked_links": int,
    "referrers": {url: [referring page urls]}}.

    With check_links=True, URLs discovered but not crawled (over max_pages)
    get a lightweight HEAD check so broken internal links surface even
    beyond the crawl budget (capped at MAX_LINK_CHECKS).

    `progress`, when given, is called as progress(done, expected_total)
    after every fetched page; expected_total is bounded by max_pages but
    grows with the link frontier. Callback errors are swallowed — no
    observer may break a crawl.
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
    # A root that carries a path declares a section (e.g. the /fr/ half of a
    # bilingual site): confine the audit to it. robots.txt, the sitemap and
    # the favicon still live at the domain root, so they keep using origin —
    # only what gets queued is filtered.
    prefix = root_prefix(root_page["final_url"] or root_url)
    seen = {root_url, root_page["final_url"]}
    referrers = {}

    if root_page["error"] and not root_page["status"]:
        return {"pages": pages, "discovered": 1, "disallowed": 0,
                "sitemap_urls": 0, "site_netloc": site_netloc,
                "favicon_ok": True, "broken_links": [], "checked_links": 0,
                "referrers": referrers}

    rp, robots_sitemaps = load_robots(origin)

    queue = []

    def enqueue(base_url, hrefs, source, referrer=None):
        for href in hrefs:
            normalized = normalize_link(base_url, href, site_netloc, prefix)
            if not normalized:
                continue
            refs = referrers.setdefault(normalized, [])
            ref = referrer or base_url
            if ref not in refs and len(refs) < MAX_REFERRERS:
                refs.append(ref)
            if normalized not in seen:
                seen.add(normalized)
                queue.append((normalized, source))

    sitemap_count = 0
    if use_sitemap:
        sitemap_urls = discover_sitemap_urls(origin, robots_sitemaps)
        sitemap_count = len(sitemap_urls)
        enqueue(origin + "/", sitemap_urls, "sitemap", referrer="sitemap.xml")
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
        if progress:
            try:
                progress(len(pages), min(max_pages, len(pages) + len(queue)))
            except Exception:  # noqa: BLE001 — observer only, never fatal
                pass
        if follow_links and page["is_html"]:
            enqueue(page["final_url"], page["links"], "link")

    compute_link_scores(pages, site_netloc)
    compute_click_depths(pages)
    compute_link_graph(pages, site_netloc)

    # Favicon: any <link rel=icon> on the site, else the /favicon.ico fallback.
    favicon_ok = any(p.get("has_favicon_link") for p in pages)
    if not favicon_ok:
        favicon_ok = fetch(origin + "/favicon.ico", timeout=10)["status"] == 200

    # GEO: which major AI crawlers does robots.txt lock out?
    ai_crawlers_blocked = []
    if rp:
        ai_crawlers_blocked = [
            bot for bot in AI_CRAWLERS
            if not rp.can_fetch(bot, origin + "/")]

    # Broken-links pass over the URLs discovered but not crawled.
    broken_links = []
    checked = 0
    if check_links:
        remaining = [url for url, _ in queue[:MAX_LINK_CHECKS]]
        for url in remaining:
            if rp and not rp.can_fetch(USER_AGENT, url):
                continue
            if delay:
                time.sleep(delay / 3)
            status, error = check_url(url, timeout=10)
            checked += 1
            if error or status >= 400:
                broken_links.append({
                    "url": url,
                    "status": status,
                    "error": error,
                    "sources": referrers.get(url, []),
                })

    return {
        "pages": pages,
        "discovered": len(seen),
        "disallowed": disallowed,
        "sitemap_urls": sitemap_count,
        "site_netloc": site_netloc,
        "favicon_ok": favicon_ok,
        "broken_links": broken_links,
        "checked_links": checked,
        "referrers": referrers,
        "complete": not queue,
        "ai_crawlers_blocked": ai_crawlers_blocked,
        "hsts_missing": bool(
            root_page["is_https"] and root_page["is_html"]
            and not root_page["hsts"]),
    }


def analyze_site(pages, meta=None):
    """Cross-page issues over a crawl result (list of strings).

    `meta` is the dict returned by crawl() — favicon_ok, broken_links,
    referrers, complete, ai_crawlers_blocked, hsts_missing are used.
    """
    meta = meta or {}
    issues = []
    referrers = meta.get("referrers") or {}
    ok = [p for p in pages
          if p["is_html"] and not p["error"] and 0 < p["status"] < 400]
    if not meta.get("favicon_ok", True):
        issues.append("No favicon found (no <link rel=icon> and no /favicon.ico)")
    if meta.get("hsts_missing"):
        issues.append(
            "No HSTS header (Strict-Transport-Security) on the homepage — "
            "add it so browsers always use HTTPS")
    blocked = meta.get("ai_crawlers_blocked") or []
    if blocked:
        issues.append(
            "robots.txt blocks AI crawlers: %s — your content cannot be "
            "read or cited by these AI assistants (keep only if intended)"
            % ", ".join(blocked))

    def linked_from(url):
        refs = [r for r in referrers.get(url, []) if r != url]
        return " — linked from: %s" % ", ".join(refs) if refs else ""

    errors = [p for p in pages if p["error"] or p["status"] >= 400]
    for p in errors:
        label = ("HTTP %d" % p["status"]) if p["status"] else p["error"]
        # A URL only ever seen as the target of a link is not "a page of the
        # site that broke": it is a link pointing at something that does not
        # exist. Saying otherwise reads as a false positive to the reader,
        # who checks the URL, finds it was never a page, and stops trusting
        # the whole report.
        kind = ("Broken internal link" if p.get("source") == "link"
                else "Page in error")
        issues.append("%s: %s (%s)%s"
                      % (kind, p["url"], label, linked_from(p["url"])))

    for link in meta.get("broken_links") or []:
        label = ("HTTP %d" % link["status"]) if link["status"] \
            else link.get("error", "unreachable")
        # Same distinction as above: a URL the site publishes in its own
        # sitemap is a page it declares, not a link. Calling it a broken
        # link sends the reader looking for a link that does not exist.
        refs = referrers.get(link["url"]) or []
        kind = ("Page in error (declared in sitemap.xml)"
                if refs and all(r == "sitemap.xml" for r in refs)
                else "Broken internal link")
        issues.append("%s: %s (%s)%s"
                      % (kind, link["url"], label, linked_from(link["url"])))

    # Orphan pages — only meaningful when every discovered URL was crawled.
    if meta.get("complete") and referrers and len(pages) > 1:
        orphans = []
        for p in ok[1:] if pages[0] in ok else ok:
            own = {p["url"], p["final_url"]}
            refs = [
                r for r in (referrers.get(p["url"], [])
                            + referrers.get(p["final_url"], []))
                if r not in own and r != "sitemap.xml"]
            if not refs:
                orphans.append(p["url"])
        if orphans:
            issues.append(
                "%d orphan page(s) — no internal link points to them "
                "(sitemap only): %s"
                % (len(orphans), ", ".join(orphans[:10])))

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
