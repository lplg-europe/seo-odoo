# -*- coding: utf-8 -*-
"""Minimal Google API client for service accounts (no google-* libraries).

Signs the OAuth2 JWT assertion with `cryptography` (already shipped with
Odoo) and talks to the Search Console and Analytics Data APIs over urllib.
The crawl engine (crawler.py) stays stdlib-only; this module is only
imported when a Google action is triggered.

Setup (BYO service account, free):
1. Google Cloud Console -> create/select a project
2. Enable "Google Search Console API" and "Google Analytics Data API"
3. Create a service account + JSON key, paste the JSON in Odoo settings
4. Add the service account email as a user in the Search Console property
   (full or restricted) and as a viewer of the GA4 property
"""
import json
import time
import urllib.error
import urllib.request
from base64 import urlsafe_b64encode
from datetime import date, timedelta
from urllib.parse import quote, urlencode

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

USER_AGENT = "SEO-Suite-Bot/0.2"
SCOPE_GSC = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_GA = "https://www.googleapis.com/auth/analytics.readonly"
GSC_API = "https://www.googleapis.com/webmasters/v3"
GSC_INSPECT_API = ("https://searchconsole.googleapis.com/v1"
                   "/urlInspection/index:inspect")
GA4_API = "https://analyticsdata.googleapis.com/v1beta"


class GoogleApiError(Exception):
    """Raised with a user-presentable message on any Google API failure."""


def _b64url(raw):
    return urlsafe_b64encode(raw).rstrip(b"=")


def _post_form(url, fields, timeout=30):
    req = urllib.request.Request(
        url, data=urlencode(fields).encode("ascii"),
        headers={"User-Agent": USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_access_token(service_account_info, scopes):
    """OAuth2 access token from a service-account JSON dict."""
    if not HAS_CRYPTO:
        raise GoogleApiError(
            "The python 'cryptography' package is required for Google "
            "integrations (it ships with standard Odoo installs).")
    try:
        email = service_account_info["client_email"]
        key_pem = service_account_info["private_key"]
        token_uri = service_account_info.get(
            "token_uri", "https://oauth2.googleapis.com/token")
    except (KeyError, TypeError):
        raise GoogleApiError(
            "Invalid service account JSON: client_email/private_key missing. "
            "Paste the full JSON key file downloaded from Google Cloud.")
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(json.dumps({
        "iss": email,
        "scope": " ".join(scopes),
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }).encode())
    signing_input = header + b"." + claims
    try:
        key = serialization.load_pem_private_key(
            key_pem.encode(), password=None)
        signature = key.sign(
            signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        raise GoogleApiError("Could not sign with the private key: %s" % e)
    assertion = (signing_input + b"." + _b64url(signature)).decode("ascii")
    try:
        data = _post_form(token_uri, {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        })
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8"))
            detail = body.get("error_description") or body.get("error") or ""
        except Exception:  # noqa: BLE001
            pass
        raise GoogleApiError(
            "Google authentication failed (HTTP %d): %s" % (e.code, detail))
    except Exception as e:
        raise GoogleApiError("Google authentication failed: %s" % e)
    token = data.get("access_token")
    if not token:
        raise GoogleApiError("Google returned no access token.")
    return token


def _api_request(token, url, payload=None, timeout=60):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": USER_AGENT,
                 "Authorization": "Bearer %s" % token,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8"))[
                "error"]["message"][:300]
        except Exception:  # noqa: BLE001
            pass
        raise GoogleApiError("Google API HTTP %d%s" % (
            e.code, ": %s" % detail if detail else ""))
    except Exception as e:
        raise GoogleApiError("Google API call failed: %s" % e)


def gsc_list_sites(token):
    """Search Console properties this service account can read."""
    data = _api_request(token, GSC_API + "/sites")
    return [(entry.get("siteUrl", ""), entry.get("permissionLevel", ""))
            for entry in data.get("siteEntry", [])]


def gsc_search_analytics(token, site_url, dimension="page", days=28,
                         row_limit=500):
    """Search Analytics rows: [{key, clicks, impressions, ctr, position}]."""
    end = date.today()
    start = end - timedelta(days=days)
    data = _api_request(
        token,
        "%s/sites/%s/searchAnalytics/query" % (GSC_API, quote(site_url, safe="")),
        {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": [dimension],
            "rowLimit": row_limit,
        })
    rows = []
    for row in data.get("rows", []):
        rows.append({
            "key": (row.get("keys") or [""])[0],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "ctr": round(row.get("ctr", 0.0) * 100, 2),
            "position": round(row.get("position", 0.0), 1),
        })
    return rows


def gsc_inspect_url(token, site_url, page_url):
    """URL Inspection result for one page.

    Returns {verdict, coverage_state, indexing_state, robots_state,
    last_crawl, google_canonical}. Daily quota: 2000 calls per property.
    """
    data = _api_request(token, GSC_INSPECT_API, {
        "inspectionUrl": page_url,
        "siteUrl": site_url,
    })
    result = (data.get("inspectionResult") or {}).get(
        "indexStatusResult") or {}
    return {
        "verdict": result.get("verdict", ""),
        "coverage_state": result.get("coverageState", ""),
        "indexing_state": result.get("indexingState", ""),
        "robots_state": result.get("robotsTxtState", ""),
        "last_crawl": result.get("lastCrawlTime", ""),
        "google_canonical": result.get("googleCanonical", ""),
    }


def ga4_run_report(token, property_id, days=28, limit=1000):
    """GA4 per-page metrics: {page_path: {views, sessions, users,
    engagement_rate}}."""
    data = _api_request(
        token, "%s/properties/%s:runReport" % (GA4_API, property_id),
        {
            "dateRanges": [{"startDate": "%ddaysAgo" % days,
                            "endDate": "today"}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "sessions"},
                        {"name": "activeUsers"}, {"name": "engagementRate"}],
            "limit": limit,
        })
    result = {}
    for row in data.get("rows", []):
        path = (row.get("dimensionValues") or [{}])[0].get("value") or "/"
        metrics = [m.get("value", "0") for m in row.get("metricValues", [])]
        metrics += ["0"] * (4 - len(metrics))
        result[path] = {
            "views": int(float(metrics[0])),
            "sessions": int(float(metrics[1])),
            "users": int(float(metrics[2])),
            "engagement_rate": round(float(metrics[3]) * 100, 1),
        }
    return result
