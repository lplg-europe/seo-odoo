# -*- coding: utf-8 -*-
"""Minimal DataForSEO v3 client (stdlib only, BYO paid credentials).

Used for the features Google's own APIs cannot provide: search volumes /
CPC / competition, and live SERP snapshots (legal alternative to scraping
Google). Every response carries its cost; callers surface it to the user.
"""
import json
import urllib.error
import urllib.request
from base64 import b64encode

USER_AGENT = "SEO-Suite-Bot/0.2"
API_BASE = "https://api.dataforseo.com/v3"


class DataForSeoError(Exception):
    """Raised with a user-presentable message on any DataForSEO failure."""


def _post(login, password, path, payload, timeout=90):
    auth = b64encode(("%s:%s" % (login, password)).encode()).decode("ascii")
    req = urllib.request.Request(
        API_BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT,
                 "Authorization": "Basic %s" % auth,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise DataForSeoError(
                "DataForSEO refused the credentials (HTTP 401). Check the "
                "API login/password in SEO → Configuration → Settings.")
        raise DataForSeoError("DataForSEO HTTP %d" % e.code)
    except Exception as e:
        raise DataForSeoError("DataForSEO call failed: %s" % e)
    if data.get("status_code") != 20000:
        raise DataForSeoError("DataForSEO error %s: %s" % (
            data.get("status_code"), data.get("status_message")))
    tasks = data.get("tasks") or []
    if not tasks:
        raise DataForSeoError("DataForSEO returned no task result.")
    task = tasks[0]
    if task.get("status_code") not in (20000, 20100):
        raise DataForSeoError("DataForSEO task error %s: %s" % (
            task.get("status_code"), task.get("status_message")))
    return task, float(data.get("cost") or 0.0)


def parse_search_volume(task):
    """{keyword_lower: {volume, cpc, competition}} from a task payload."""
    rows = {}
    for result in task.get("result") or []:
        keyword = (result.get("keyword") or "").lower()
        if not keyword:
            continue
        rows[keyword] = {
            "volume": int(result.get("search_volume") or 0),
            "cpc": float(result.get("cpc") or 0.0),
            "competition": int(result.get("competition_index") or 0),
        }
    return rows


def search_volume(login, password, keywords, location="Belgium",
                  language="fr"):
    """Monthly volumes / CPC / competition for up to 1000 keywords.

    Returns ({keyword_lower: {...}}, cost).
    """
    task, cost = _post(login, password,
                       "/keywords_data/google_ads/search_volume/live", [{
                           "keywords": list(keywords)[:1000],
                           "location_name": location,
                           "language_code": language,
                       }])
    return parse_search_volume(task), cost


def parse_backlinks_summary(task):
    """Key metrics from a backlinks summary task payload."""
    result = (task.get("result") or [{}])[0] or {}
    return {
        "rank": int(result.get("rank") or 0),
        "backlinks": int(result.get("backlinks") or 0),
        "referring_domains": int(result.get("referring_domains") or 0),
        "referring_pages": int(result.get("referring_pages") or 0),
        "broken_backlinks": int(result.get("broken_backlinks") or 0),
        "broken_pages": int(result.get("broken_pages") or 0),
        "spam_score": int(result.get("target_spam_score") or 0),
        "dofollow": int((result.get("referring_links_attributes") or {})
                        .get("dofollow") or 0),
        "first_seen": (result.get("first_seen") or "")[:10],
    }


def backlinks_summary(login, password, target):
    """Backlink profile overview of a domain (DataForSEO Backlinks API).

    Returns ({rank, backlinks, referring_domains, ...}, cost).
    """
    task, cost = _post(login, password, "/backlinks/summary/live", [{
        "target": target,
        "include_subdomains": True,
        "internal_list_limit": 10,
    }])
    return parse_backlinks_summary(task), cost


# --- AI Visibility (DataForSEO AI Optimization API) ------------------------

# platform key -> (endpoint segment, default model asked by real users)
LLM_PLATFORMS = {
    "chatgpt": ("chat_gpt", "gpt-5"),
    "claude": ("claude", "claude-sonnet-4-5"),
    "gemini": ("gemini", "gemini-2.5-pro"),
    "perplexity": ("perplexity", "sonar-reasoning-pro"),
}
US_LOCATION = 2840  # LLM Mentions data is US/en today


def parse_llm_response(task):
    """{text, citations: [urls], model} from an llm_responses task."""
    result = (task.get("result") or [{}])[0] or {}
    texts, citations = [], []
    for item in result.get("items") or []:
        for section in item.get("sections") or []:
            if section.get("text"):
                texts.append(section["text"])
            for annotation in section.get("annotations") or []:
                url = annotation.get("url")
                if url and url not in citations:
                    citations.append(url)
    return {
        "text": "\n".join(texts).strip(),
        "citations": citations,
        "model": result.get("model_name") or "",
    }


def llm_response(login, password, platform, prompt, web_search=True,
                 model=None):
    """Ask one LLM platform a prompt (as a real user would).

    Returns ({text, citations, model}, cost).
    """
    segment, default_model = LLM_PLATFORMS[platform]
    task, cost = _post(login, password,
                       "/ai_optimization/%s/llm_responses/live" % segment, [{
                           "user_prompt": prompt,
                           "model_name": model or default_model,
                           "web_search": bool(web_search),
                       }], timeout=180)
    return parse_llm_response(task), cost


def parse_llm_mentions(task):
    """[{question, volume}] from an llm_mentions/search task."""
    result = (task.get("result") or [{}])[0] or {}
    rows = []
    for item in result.get("items") or []:
        if item.get("question"):
            rows.append({
                "question": item["question"],
                "volume": int(item.get("ai_search_volume") or 0),
            })
    return rows


def llm_mentions_search(login, password, domain, platform="chat_gpt",
                        limit=20):
    """Prompts where AI assistants mention/cite this domain (US/en data).

    platform: "chat_gpt" or "google" (AI Overview).
    Returns ([{question, volume}], cost).
    """
    task, cost = _post(login, password,
                       "/ai_optimization/llm_mentions/search/live", [{
                           "target": [{"domain": domain}],
                           "platform": platform,
                           "location_code": US_LOCATION,
                           "language_code": "en",
                           "limit": limit,
                       }])
    return parse_llm_mentions(task), cost


def parse_share_of_voice(task):
    """[{brand, mentions}] from a cross_aggregated_metrics task."""
    result = (task.get("result") or [{}])[0] or {}
    rows = []
    for item in result.get("items") or []:
        total = 0
        for group in item.get("platform") or []:
            if isinstance(group, dict):
                value = (group.get("count") if group.get("count") is not None
                         else group.get("value"))
                total += int(value or 0)
        rows.append({"brand": item.get("key") or "?", "mentions": total})
    rows.sort(key=lambda r: -r["mentions"])
    return rows


def llm_share_of_voice(login, password, brands, platform="chat_gpt"):
    """Brand-vs-competitor mention counts in AI answers (US/en data).

    Returns ([{brand, mentions}] sorted desc, cost).
    """
    task, cost = _post(
        login, password,
        "/ai_optimization/llm_mentions/cross_aggregated_metrics/live", [{
            "target": [{"keyword": brand, "aggregation_key": brand}
                       for brand in brands],
            "platform": platform,
            "location_code": US_LOCATION,
            "language_code": "en",
        }])
    return parse_share_of_voice(task), cost


def parse_serp_items(task):
    """Organic items [{position, domain, url, title}] from a task payload."""
    items = []
    for result in task.get("result") or []:
        for item in result.get("items") or []:
            if item.get("type") != "organic":
                continue
            items.append({
                "position": int(item.get("rank_group") or 0),
                "domain": item.get("domain") or "",
                "url": item.get("url") or "",
                "title": item.get("title") or "",
            })
    return items


def serp_organic(login, password, keyword, location="Belgium", language="fr",
                 depth=20):
    """Live Google SERP snapshot for one keyword.

    Returns {"items": [...], "cost": float}.
    """
    task, cost = _post(login, password, "/serp/google/organic/live/regular", [{
        "keyword": keyword,
        "location_name": location,
        "language_code": language,
        "depth": depth,
    }])
    return {"items": parse_serp_items(task), "cost": cost}
