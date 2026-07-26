# -*- coding: utf-8 -*-
"""SEO Suite MCP server — expose the crawl engine to AI assistants.

A stdio JSON-RPC 2.0 server implementing the Model Context Protocol,
pure Python stdlib (no pip install). It reuses the same crawl engine as
the Odoo module (addons/seo_suite/crawler.py), so an assistant like
Claude gets the exact same audits as the Odoo UI.

Register it (e.g. in a .mcp.json at a project root):

    {"mcpServers": {"seo-suite": {"command": "python",
                                  "args": ["/path/to/seo-odoo/mcp/server.py"]}}}

Tools:
- audit_page(url)                       full on-page audit of one URL
- crawl_site(url, max_pages, use_sitemap, check_links)
                                        multi-page crawl + site issues
- check_url(url)                        lightweight HTTP status check
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "addons", "seo_suite"))
import crawler  # noqa: E402

SERVER_NAME = "seo-suite"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"
MAX_PAGES_CAP = 150

TOOLS = [
    {
        "name": "audit_page",
        "description": (
            "Full on-page SEO audit of one URL: title, meta description, "
            "headings outline, canonical, robots, Open Graph, schema.org "
            "types, hreflang, links, images without alt, word count, "
            "readability, top keywords, response time, redirects, mixed "
            "content — plus a 0-100 score and a severity-classified list "
            "of issues."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Page URL (scheme optional)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "crawl_site",
        "description": (
            "Crawl a whole site (sitemap.xml + internal links, respects "
            "robots.txt) and audit every page. Returns per-page scores and "
            "issues plus site-level findings: duplicate titles/descriptions, "
            "broken pages, noindex pages, missing favicon, internal "
            "PageRank link scores."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Root URL of the site"},
                "max_pages": {"type": "integer",
                              "description": "Max pages to crawl "
                                             "(default 25, cap 150)"},
                "use_sitemap": {"type": "boolean",
                                "description": "Seed from sitemap.xml "
                                               "(default true)"},
                "check_links": {"type": "boolean",
                                "description": "HEAD-check discovered but "
                                               "not crawled URLs (default "
                                               "false, slower)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "check_url",
        "description": "Lightweight availability check of one URL "
                       "(HEAD with GET fallback): HTTP status only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
]


def _page_summary(page):
    """Compact JSON-friendly view of a crawler page dict."""
    return {
        "url": page["url"],
        "final_url": page["final_url"],
        "status": page["status"],
        "score": page["score"],
        "link_score": page.get("link_score", 0),
        "title": page["title"],
        "title_length": len(page["title"]),
        "meta_description": page["meta_description"],
        "meta_description_length": len(page["meta_description"]),
        "h1": page["h1"],
        "headings": ["H%d %s" % (level, text)
                     for level, text in page.get("headings", [])[:50]],
        "canonical": page["canonical"],
        "meta_robots": page["meta_robots"],
        "lang": page["lang"],
        "viewport": page["viewport"],
        "open_graph": page["og"],
        "schema_types": page["schema_types"],
        "hreflang_count": len(page["hreflangs"]),
        "word_count": page["word_count"],
        "reading_time_min": page.get("reading_time", 0),
        "flesch_score": page["flesch_score"],
        "flesch_label": page["flesch_label"],
        "text_ratio_pct": page["text_ratio"],
        "top_keywords": ["%s (%d)" % (word, count)
                         for word, count in page["top_keywords"]],
        "internal_links": page["internal_links"],
        "external_links": page["external_links"],
        "images": page["images"],
        "images_without_alt": page["images_without_alt"],
        "response_time_s": page["response_time"],
        "page_size_kb": page["page_size_kb"],
        "redirect_count": page["redirect_count"],
        "is_https": page["is_https"],
        "mixed_content": page["mixed_content"],
        "unsafe_blank_links": page["unsafe_blank_links"],
        "error": page["error"],
        "issues": [
            {"severity": issue["severity"], "category": issue["category"],
             "message": issue["message"]}
            for issue in page["issues"]
        ],
    }


def tool_audit_page(arguments):
    url = (arguments.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return _page_summary(crawler.fetch_page(url))


def tool_crawl_site(arguments):
    url = (arguments.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    max_pages = min(int(arguments.get("max_pages") or 25), MAX_PAGES_CAP)
    result = crawler.crawl(
        url,
        max_pages=max_pages,
        use_sitemap=bool(arguments.get("use_sitemap", True)),
        follow_links=True,
        check_links=bool(arguments.get("check_links", False)),
    )
    pages = result["pages"]
    scores = [page["score"] for page in pages]
    site_issues = crawler.analyze_site(
        pages, result.get("favicon_ok", True),
        broken_links=result.get("broken_links"),
        referrers=result.get("referrers"))
    return {
        "site_score": round(sum(scores) / len(scores)) if scores else 0,
        "pages_crawled": len(pages),
        "urls_discovered": result["discovered"],
        "sitemap_urls": result["sitemap_urls"],
        "robots_disallowed": result["disallowed"],
        "links_checked": result.get("checked_links", 0),
        "site_issues": site_issues,
        "pages": [_page_summary(page) for page in pages],
    }


def tool_check_url(arguments):
    url = (arguments.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    status, error = crawler.check_url(url)
    return {"url": url, "status": status, "error": error}


TOOL_HANDLERS = {
    "audit_page": tool_audit_page,
    "crawl_site": tool_crawl_site,
    "check_url": tool_check_url,
}


def handle_request(request):
    """One JSON-RPC request -> response dict (or None for notifications)."""
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _error(request_id, -32602, "Unknown tool: %s" % name)
        try:
            payload = handler(params.get("arguments") or {})
            result = {
                "content": [{"type": "text",
                             "text": json.dumps(payload, ensure_ascii=False,
                                                indent=1)}],
                "isError": False,
            }
        except Exception as e:  # noqa: BLE001 — report to the client
            result = {
                "content": [{"type": "text", "text": "Error: %s" % e}],
                "isError": True,
            }
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return None
    else:
        if request_id is None:
            return None  # unknown notification: ignore
        return _error(request_id, -32601, "Method not found: %s" % method)
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def main():
    # MCP clients speak UTF-8; never rely on the platform default (cp1252
    # on Windows would corrupt accented content).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    stdout = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        response = handle_request(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
