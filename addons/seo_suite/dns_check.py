# -*- coding: utf-8 -*-
"""Domain-level diagnosis: DNS, registrar, and reachability of both hosts.

Answers the questions an agency asks before touching a site it does not
host: where does the domain live (registrar, DNS, mail), does the naked
domain work in HTTPS, do both variants redirect to one canonical host,
and is email deliverability protected (SPF/DMARC)?

Real case that motivated this module: a client site whose www worked
perfectly while https://<bare-domain> refused connections — the registrar's
HTTP-only redirect service listened on port 80 only, so every modern
browser (HTTPS-first) showed an error page. Nothing in a page-by-page
crawl can see that class of problem; it lives around the site, not in it.

Pure stdlib, same rule as crawler.py. Network I/O is isolated in three
small functions (doh_query, rdap_lookup, probe) so that the analysis
(`evaluate`) and the merge helper are testable without any network.

DNS goes through DNS-over-HTTPS (dns.google) rather than the OS resolver:
the stdlib cannot query NS/MX/TXT records, parsing nslookup output is
locale-dependent, and DoH also reports DNSSEC validation (the AD flag).
"""
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

USER_AGENT = "Mozilla/5.0 (compatible; SEO-Suite-DomainCheck/1.0)"
DOH_ENDPOINT = "https://dns.google/resolve"
RDAP_ENDPOINT = "https://rdap.org/domain/"
TIMEOUT = 10

# DNS record types as returned by DoH (RFC 1035 numbers).
TYPE_A, TYPE_NS, TYPE_CNAME, TYPE_MX, TYPE_TXT, TYPE_AAAA = 1, 2, 5, 15, 16, 28

# Hostname fragments -> human name of the operator. Checked against NS and
# MX targets. Deliberately small: unknown providers stay as the raw
# hostname, which is still actionable ("ns1.example-hosting.fr").
PROVIDERS = [
    ("ovh", "OVH"),
    ("cloudflare", "Cloudflare"),
    ("combell", "Combell"),
    ("gandi", "Gandi"),
    ("one.com", "one.com"),
    ("openprovider", "Openprovider"),
    ("registrar.eu", "Openprovider"),
    ("transip", "TransIP"),
    ("infomaniak", "Infomaniak"),
    ("googledomains", "Google"),
    ("google", "Google"),
    ("aspmx", "Google Workspace"),
    ("awsdns", "AWS Route 53"),
    ("azure-dns", "Microsoft Azure"),
    ("protection.outlook", "Microsoft 365"),
    ("ionos", "IONOS"),
    ("ui-dns", "IONOS"),
    ("easyhost", "Easyhost"),
    ("hostinger", "Hostinger"),
    ("namecheap", "Namecheap"),
    ("registrar-servers", "Namecheap"),
    ("proximus", "Proximus"),
    ("telenet", "Telenet"),
    ("versio", "Versio"),
    ("mijndomein", "Mijndomein"),
]


class DomainCheckError(Exception):
    """The check could not run at all (no network, bad site URL)."""


# --------------------------------------------------------------- network --
def _fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def doh_query(name, rtype, timeout=TIMEOUT):
    """One DNS-over-HTTPS lookup -> (answers, dnssec_validated).

    `answers` is the raw DoH Answer list: dicts with "type" and "data".
    Errors bubble up: the caller decides what is best-effort.
    """
    data = _fetch_json(
        "%s?name=%s&type=%s" % (DOH_ENDPOINT, name, rtype), timeout=timeout)
    return data.get("Answer") or [], bool(data.get("AD"))


def rdap_lookup(domain, timeout=TIMEOUT):
    """Registrar and lifecycle dates via RDAP, {} when unavailable.

    rdap.org redirects to the registry's own RDAP server (urllib follows).
    Registries differ wildly in what they publish, so every field is
    optional. DNS Belgium does not serve RDAP at all, so .be domains fall
    back to their public registration API (dates only — the registrar is
    not in that JSON).
    """
    if domain.endswith(".be"):
        try:
            data = _fetch_json(
                "https://api.dnsbelgium.be/whois/registration/" + domain,
                timeout=timeout)
            info = data.get("domainInfo") or {}
            return {k: v for k, v in {
                "created": (info.get("created") or "")[:10],
            }.items() if v}
        except Exception:  # noqa: BLE001 — enrichment only
            return {}
    try:
        data = _fetch_json(RDAP_ENDPOINT + domain, timeout=timeout)
    except Exception:  # noqa: BLE001 — RDAP is enrichment, never a blocker
        return {}
    out = {}
    for entity in data.get("entities") or []:
        if "registrar" not in (entity.get("roles") or []):
            continue
        for item in (entity.get("vcardArray") or [None, []])[1]:
            if item and item[0] == "fn" and item[3]:
                out["registrar"] = item[3]
                break
        if "registrar" not in out:
            for pid in entity.get("publicIds") or []:
                if pid.get("identifier"):
                    out["registrar"] = pid["identifier"]
                    break
    for event in data.get("events") or []:
        action = event.get("eventAction")
        date = (event.get("eventDate") or "")[:10]
        if action == "registration":
            out["created"] = date
        elif action == "expiration":
            out["expires"] = date
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def probe(url, timeout=TIMEOUT):
    """GET without following redirects -> {status, location, error}.

    The error *class* is what matters downstream: a refused connection on
    the naked domain tells a different story (redirect service without
    HTTPS) than a certificate error (wrong vhost) or a DNS failure (no
    record at all).
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return {"status": resp.getcode(), "location": "", "error": ""}
    except urllib.error.HTTPError as e:
        return {"status": e.code,
                "location": e.headers.get("Location", ""), "error": ""}
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            kind = "dns"
        elif isinstance(reason, ConnectionRefusedError):
            kind = "refused"
        elif isinstance(reason, ConnectionResetError):
            # Some redirect services (OVH among them) alternate between
            # refusing and resetting on port 443 — same meaning for us.
            kind = "reset"
        elif isinstance(reason, socket.timeout) or isinstance(e, TimeoutError):
            kind = "timeout"
        elif isinstance(reason, ssl.SSLCertVerificationError):
            kind = "tls-cert"
        elif isinstance(reason, ssl.SSLError):
            kind = "tls"
        else:
            kind = str(reason)[:60]
        return {"status": 0, "location": "", "error": kind}
    except socket.timeout:
        return {"status": 0, "location": "", "error": "timeout"}
    except ConnectionResetError:
        return {"status": 0, "location": "", "error": "reset"}
    except ssl.SSLError:
        return {"status": 0, "location": "", "error": "tls"}
    except Exception as e:  # noqa: BLE001 — classify, never crash the check
        return {"status": 0, "location": "", "error": str(e)[:60]}


# ---------------------------------------------------------------- helpers --
def registrable_domain(host):
    """Naive eTLD+1: last two labels, or last three for co.uk-style TLDs.

    Good enough for the European ccTLDs this tool audits; a full public
    suffix list would be the stdlib-unfriendly alternative.
    """
    labels = host.lower().strip(".").split(".")
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "gov", "ac"):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def provider_name(hosts):
    """Best-known operator behind a list of NS/MX hostnames."""
    joined = " ".join(h.lower() for h in hosts)
    for fragment, name in PROVIDERS:
        if fragment in joined:
            return name
    return hosts[0].rstrip(".") if hosts else ""


def _txt_values(answers):
    return [a.get("data", "").strip('"').replace('" "', "")
            for a in answers if a.get("type") == TYPE_TXT]


def collect(site_url, timeout=TIMEOUT):
    """Gather DNS records, RDAP data and HTTP probes for a site URL."""
    host = urlsplit(
        site_url if "://" in site_url else "https://" + site_url
    ).netloc.lower().strip(".")
    if not host:
        raise DomainCheckError("No host in site URL %r" % site_url)
    bare = registrable_domain(host)
    www_host = "www." + bare
    canonical = host

    def safe_doh(name, rtype):
        try:
            return doh_query(name, rtype, timeout=timeout)
        except Exception:  # noqa: BLE001 — a dead resolver: empty answers
            return [], False

    ns_answers, dnssec = safe_doh(bare, "NS")
    mx_answers, _ = safe_doh(bare, "MX")
    apex_answers, _ = safe_doh(bare, "A")
    www_answers, _ = safe_doh(www_host, "A")
    spf_answers, _ = safe_doh(bare, "TXT")
    dmarc_answers, _ = safe_doh("_dmarc." + bare, "TXT")

    probes = {}
    for scheme in ("http", "https"):
        for h in {bare, www_host, canonical}:
            url = "%s://%s/" % (scheme, h)
            probes[url] = probe(url, timeout=timeout)

    return {
        "canonical": canonical,
        "bare": bare,
        "www_host": www_host,
        "ns": sorted(a.get("data", "").rstrip(".")
                     for a in ns_answers if a.get("type") == TYPE_NS),
        "mx": sorted(a.get("data", "").split()[-1].rstrip(".")
                     for a in mx_answers if a.get("type") == TYPE_MX),
        "apex_a": [a.get("data", "") for a in apex_answers
                   if a.get("type") == TYPE_A],
        "www_cname": next((a.get("data", "").rstrip(".")
                           for a in www_answers
                           if a.get("type") == TYPE_CNAME), ""),
        "spf": next((v for v in _txt_values(spf_answers)
                     if v.lower().startswith("v=spf1")), ""),
        "dmarc": next((v for v in _txt_values(dmarc_answers)
                       if v.lower().startswith("v=dmarc1")), ""),
        "dnssec": dnssec,
        "rdap": rdap_lookup(bare, timeout=timeout),
        "probes": probes,
    }


# --------------------------------------------------------------- analysis --
def _redirects_to(result, host):
    loc = (result.get("location") or "").lower()
    return bool(loc) and 300 <= (result.get("status") or 0) < 400 \
        and host.lower() in loc


def evaluate(snapshot):
    """Findings + summary from a collect() snapshot. Pure, no network.

    Returns {"fields": {...}, "issues": [message, ...], "summary": text}.
    Messages are full sentences ordered most-severe first, ready to merge
    into the site-level issues (and therefore into the client reports).
    """
    bare = snapshot["bare"]
    canonical = snapshot["canonical"]
    www_host = snapshot["www_host"]
    other = www_host if canonical == bare else bare
    probes = snapshot["probes"]
    issues = []

    https_canon = probes.get("https://%s/" % canonical, {})
    https_other = probes.get("https://%s/" % other, {})
    http_canon = probes.get("http://%s/" % canonical, {})
    http_other = probes.get("http://%s/" % other, {})

    dns_provider = provider_name(snapshot["ns"])

    if https_canon.get("error"):
        issues.append(
            "The site itself is unreachable over HTTPS (https://%s: %s) — "
            "this is the first thing to fix, nothing else matters until "
            "browsers can load the site securely."
            % (canonical, https_canon["error"]))

    if not snapshot["apex_a"] and canonical != bare and not snapshot.get(
            "www_cname", "").startswith(bare):
        apex_dead = (http_other.get("error") == "dns"
                     and https_other.get("error") == "dns")
        if apex_dead:
            issues.append(
                "The naked domain %s has no DNS record at all — anyone "
                "typing the address without www gets a browser error. Add "
                "an A record or a redirect at the DNS provider (%s)."
                % (bare, dns_provider or "unknown"))

    other_error = https_other.get("error")
    if (not https_canon.get("error") and other_error
            and other_error != "dns"):
        detail = {
            "refused": "the server refuses HTTPS connections",
            "reset": "the server drops HTTPS connections",
            "timeout": "the server does not answer on HTTPS",
            "tls": "the TLS handshake fails",
            "tls-cert": "the certificate does not cover this host",
        }.get(other_error, "the connection fails: %s" % other_error)
        hint = ""
        if _redirects_to(http_other, canonical):
            hint = (" The HTTP redirect to %s exists, but browsers try "
                    "HTTPS first, so most visitors never reach it — enable "
                    "HTTPS on the redirect at %s." % (
                        canonical, dns_provider or "the DNS provider"))
        issues.append(
            "https://%s does not work (%s) while https://%s does.%s"
            % (other, detail, canonical, hint or " Redirect it to the "
               "canonical host with HTTPS enabled."))

    if (not https_other.get("error")
            and (https_other.get("status") or 0) < 300
            and not https_canon.get("error")):
        issues.append(
            "Both %s and %s answer with content instead of one "
            "redirecting to the other — search engines see two copies "
            "of the site. Pick %s as canonical and 301 the other."
            % (canonical, other, canonical))
    elif (300 <= (https_other.get("status") or 0) < 400
          and not _redirects_to(https_other, canonical)
          and https_other.get("location")):
        issues.append(
            "https://%s redirects to %s instead of the canonical host %s."
            % (other, https_other["location"], canonical))

    if (http_canon.get("status") == 200 and not http_canon.get("error")
            and not _redirects_to(http_canon, canonical)):
        issues.append(
            "http://%s serves the page instead of redirecting to HTTPS — "
            "force the https:// version with a 301." % canonical)

    if snapshot["mx"] and not snapshot["spf"]:
        issues.append(
            "No SPF record on %s — emails from this domain are easier to "
            "spoof and more likely to land in spam. Add a TXT record "
            "\"v=spf1 ...\" at the DNS provider." % bare)
    if snapshot["mx"] and not snapshot["dmarc"]:
        issues.append(
            "No DMARC record (_dmarc.%s) — mailbox providers have no "
            "policy to apply when a message fails authentication. Start "
            "with \"v=DMARC1; p=none; rua=mailto:...\"." % bare)

    expires = snapshot["rdap"].get("expires", "")

    fields = {
        "registrar": snapshot["rdap"].get("registrar", ""),
        "dns_provider": dns_provider,
        "mail_provider": provider_name(snapshot["mx"]),
        "created": snapshot["rdap"].get("created", ""),
        "expires": expires,
        "dnssec": snapshot["dnssec"],
    }

    lines = [
        "Domain: %s (registered %s%s)" % (
            bare, fields["created"] or "?",
            ", expires " + expires if expires else ""),
        "Registrar: %s" % (fields["registrar"] or "unknown"),
        "DNS: %s (%s)" % (dns_provider or "?", ", ".join(snapshot["ns"])),
        "Mail: %s (%s)" % (fields["mail_provider"] or "no MX",
                           ", ".join(snapshot["mx"]) or "none"),
        "DNSSEC: %s" % ("validated" if snapshot["dnssec"] else "not enabled"),
        "SPF: %s" % (snapshot["spf"] or "none"),
        "DMARC: %s" % (snapshot["dmarc"] or "none"),
        "Naked domain A: %s" % (", ".join(snapshot["apex_a"]) or "none"),
        "www CNAME: %s" % (snapshot["www_cname"] or "none"),
    ]
    for url in sorted(probes):
        r = probes[url]
        state = r["error"] or str(r["status"])
        if r.get("location"):
            state += " -> " + r["location"]
        lines.append("%s : %s" % (url, state))

    return {"fields": fields, "issues": issues, "summary": "\n".join(lines)}


def check_domain(site_url, timeout=TIMEOUT):
    """collect() + evaluate() — the one-call entry point for the model."""
    return evaluate(collect(site_url, timeout=timeout))


DOMAIN_PREFIX = "Domain: "


def merge_domain_lines(existing_text, messages):
    """Replace previous domain findings inside the site-issues text.

    Crawl-produced lines are kept untouched; lines starting with the
    domain prefix are replaced by the new findings. Pure function so the
    merge logic is testable without a database.
    """
    kept = [line for line in (existing_text or "").splitlines()
            if line.strip()
            and not line.startswith(DOMAIN_PREFIX)
            and line.strip() != "No site-level issues"]
    merged = kept + [DOMAIN_PREFIX + m for m in messages]
    return "\n".join(merged) or "No site-level issues", len(merged)
