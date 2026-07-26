# -*- coding: utf-8 -*-
"""Pure-stdlib helpers for the web analytics module — no Odoo import.

Privacy model (Plausible-style, clean-room):
- no cookies, no client-side identifier for counting
- visitor id = sha256(daily_salt + ip + user_agent + site_token)[:12]
- the salt rotates every UTC day, so visitors cannot be tracked across
  days and the raw IP is never stored anywhere
"""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

SESSION_WINDOW_MINUTES = 30

_BOT_RE = re.compile(
    r"bot|crawler|spider|headless|lighthouse|slurp|curl|wget|python-requests"
    r"|scrapy|monitor|scan|preview|facebookexternalhit|whatsapp|telegram"
    r"|embedly|pingdom|uptime", re.IGNORECASE)

SEARCH_DOMAINS = ("google.", "bing.", "duckduckgo.", "search.yahoo.",
                  "qwant.", "ecosia.", "startpage.", "search.brave.",
                  "yandex.", "baidu.")
SOCIAL_DOMAINS = ("facebook.", "instagram.", "linkedin.", "twitter.",
                  "t.co", "x.com", "pinterest.", "tiktok.", "youtube.",
                  "reddit.", "threads.", "mastodon.")
AI_DOMAINS = ("chatgpt.com", "chat.openai.com", "claude.ai",
              "perplexity.ai", "gemini.google.com",
              "copilot.microsoft.com", "you.com", "phind.com")
PAID_PARAMS = ("gclid", "fbclid", "msclkid", "gad_source", "ttclid")


def is_bot(user_agent):
    return bool(_BOT_RE.search(user_agent or ""))


def visitor_hash(daily_salt, ip, user_agent, site_token):
    """12-hex-char anonymous visitor id (never reversible to the IP)."""
    raw = "%s|%s|%s|%s" % (daily_salt, ip or "", user_agent or "",
                           site_token or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def daily_salt(secret, utc_date_str):
    """Rotating salt: sha256(secret + YYYY-MM-DD)."""
    return hashlib.sha256(
        ("%s|%s" % (secret, utc_date_str)).encode("utf-8")).hexdigest()


def parse_device(user_agent):
    """(device_type, browser, os) from a raw user-agent string."""
    ua = user_agent or ""
    if re.search(r"iPad|Tablet", ua, re.I):
        device = "tablet"
    elif re.search(r"Mobile|iPhone|Android", ua, re.I):
        device = "mobile"
    else:
        device = "desktop"

    if "Edg/" in ua or "Edge/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "SamsungBrowser" in ua:
        browser = "Samsung Internet"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua or "CriOS/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    elif "MSIE" in ua or "Trident/" in ua:
        browser = "Internet Explorer"
    else:
        browser = "Other"

    if "Windows" in ua:
        os_name = "Windows"
    elif "Android" in ua:
        os_name = "Android"
    elif re.search(r"iPhone|iPad|iOS", ua):
        os_name = "iOS"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"
    return device, browser, os_name


def parse_utm(querystring):
    """{utm_source, utm_medium, utm_campaign, has_paid_ids} from ?qs."""
    params = parse_qs((querystring or "").lstrip("?"))

    def first(key):
        values = params.get(key) or [""]
        return values[0][:128]

    return {
        "utm_source": first("utm_source"),
        "utm_medium": first("utm_medium"),
        "utm_campaign": first("utm_campaign"),
        "has_paid_ids": any(key in params for key in PAID_PARAMS),
    }


def referrer_host(referrer, own_host=""):
    """Lowercased referrer host; '' for empty or same-site referrers."""
    host = urlsplit(referrer or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    own = (own_host or "").lower()
    if own.startswith("www."):
        own = own[4:]
    return "" if not host or host == own else host


def classify_channel(ref_host, utm_medium, utm_source, has_paid_ids):
    """Acquisition channel, simplified from industry-standard groupings."""
    medium = (utm_medium or "").lower()
    source = (utm_source or "").lower()
    if has_paid_ids or medium in ("cpc", "ppc", "paid", "paid_social",
                                  "display", "banner"):
        return "Paid"
    if medium == "email" or source in ("email", "newsletter", "mailchimp",
                                       "brevo"):
        return "Email"
    if any(ref_host == d or ref_host.endswith("." + d) or
           ref_host.startswith(d) for d in AI_DOMAINS):
        return "AI"
    if any(ref_host.startswith(d) or ("." + d) in ("." + ref_host)
           for d in SEARCH_DOMAINS):
        return "Organic Search"
    if any(ref_host.startswith(d) or ref_host == d.rstrip(".")
           or ref_host.endswith("." + d.rstrip("."))
           for d in SOCIAL_DOMAINS):
        return "Organic Social"
    if not ref_host:
        return "Direct"
    return "Referral"
