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
