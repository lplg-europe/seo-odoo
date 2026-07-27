# -*- coding: utf-8 -*-
"""IndexNow submission — pure stdlib, no dependency.

IndexNow is the open protocol Bing, Yandex, Seznam and Naver honour: you
push a URL and they queue it for crawling within minutes instead of
waiting for their next visit.

Google does NOT participate. Nothing can force Google to index a page —
the only lever on its side is removing the barriers (sitemap, no
noindex, internal links) and asking manually in Search Console. This
module does the part that is actually automatable, and the rest of the
audit tells you what to do about Google.
"""
import json
import urllib.error
import urllib.request

ENDPOINT = "https://api.indexnow.org/IndexNow"
USER_AGENT = "SEO-Suite-Bot/0.2"
MAX_URLS = 10000  # IndexNow caps a single batch at 10 000 URLs


class IndexNowError(Exception):
    pass


def submit(host, key, urls, key_location=None, timeout=30):
    """Submit URLs for (re)crawling. Returns the HTTP status code.

    `key_location` defaults to https://<host>/<key>.txt, the convention;
    pass it explicitly when the key file lives in a subdirectory.
    """
    urls = [u for u in urls if u][:MAX_URLS]
    if not urls:
        return 0
    if not host or not key:
        raise IndexNowError(
            "IndexNow needs a host and a key. Generate a key, publish it "
            "as a text file at the site root, and fill both in "
            "SEO → Configuration → Settings.")
    payload = json.dumps({
        "host": host,
        "key": key,
        "keyLocation": key_location or "https://%s/%s.txt" % (host, key),
        "urlList": urls,
    }).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # 403 = the key file is unreachable, 422 = URL not on the host
        detail = {
            400: "malformed request",
            403: "key file not found or not matching — check that %s is "
                 "reachable and contains exactly the key"
                 % (key_location or "https://%s/%s.txt" % (host, key)),
            # The key file's directory bounds what may be submitted: a key
            # published at /docs/<key>.txt authorizes /docs/* only. This is
            # the most common IndexNow surprise, so spell it out.
            422: "a URL is outside the key's scope. The key file's folder "
                 "bounds what you may submit: publish the key at the site "
                 "root to cover the whole site, or submit only URLs under "
                 "the folder holding it",
            429: "too many requests, try again later",
        }.get(exc.code, exc.reason)
        raise IndexNowError("IndexNow refused the submission (HTTP %d): %s"
                            % (exc.code, detail))
    except (urllib.error.URLError, OSError) as exc:
        raise IndexNowError("IndexNow unreachable: %s" % exc)
