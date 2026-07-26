# -*- coding: utf-8 -*-
"""Public endpoints: the tracking script and the collect API.

Privacy: the visitor identity is computed server-side from a daily
rotating salt + IP + user-agent — the IP itself is never stored, no
cookie is set, nothing identifying is kept client-side.
"""
import json

from odoo import fields, http
from odoo.http import request

from ..analytics_lib import (
    classify_channel, daily_salt, is_bot, parse_device, parse_utm,
    referrer_host, visitor_hash)

# Kept deliberately tiny (~3 KB): auto pageviews (SPA-aware), custom
# events, outbound-link clicks, JS errors, and native Web Vitals
# (LCP / CLS / FCP / TTFB via PerformanceObserver — no library).
SCRIPT_JS = r"""(function(){
var s=document.currentScript;if(!s)return;
var t=s.getAttribute("data-token")||"";
var u=s.src.replace(/\/wa\/script\.js.*$/,"/wa/collect");
function send(type,name,extra){
 var p={token:t,type:type,name:name||"",host:location.hostname,
  path:location.pathname,title:document.title.slice(0,256),
  referrer:document.referrer||"",search:location.search||"",
  lang:(navigator.language||"").slice(0,8)};
 if(extra)for(var k in extra)p[k]=extra[k];
 var b=JSON.stringify(p);
 try{if(!navigator.sendBeacon(u,new Blob([b],{type:"text/plain"})))throw 0;}
 catch(e){var x=new XMLHttpRequest();x.open("POST",u,true);x.send(b);}
}
var last=null;
function pv(){var k=location.pathname+location.search;
 if(k!==last){last=k;send("pageview");}}
var ps=history.pushState;history.pushState=function(){
 ps.apply(this,arguments);pv();};
var rs=history.replaceState;history.replaceState=function(){
 rs.apply(this,arguments);pv();};
addEventListener("popstate",pv);addEventListener("hashchange",pv);
document.addEventListener("click",function(e){
 var a=e.target&&e.target.closest?e.target.closest("a[href]"):null;
 if(a&&a.hostname&&a.hostname!==location.hostname&&/^https?:/.test(a.href))
  send("outbound",a.href.slice(0,256));},true);
var seen={};
addEventListener("error",function(e){
 var m=String((e&&e.message)||"Script error").slice(0,180);
 if(!seen[m]){seen[m]=1;send("error",m);}});
var vit={},vs=false;
try{
 var nav=performance.getEntriesByType("navigation")[0];
 if(nav)vit.ttfb=Math.round(nav.responseStart);
 new PerformanceObserver(function(l){var es=l.getEntries();
  for(var i=0;i<es.length;i++)if(es[i].name==="first-contentful-paint")
   vit.fcp=Math.round(es[i].startTime);
 }).observe({type:"paint",buffered:true});
 new PerformanceObserver(function(l){var es=l.getEntries();
  if(es.length)vit.lcp=Math.round(es[es.length-1].startTime);
 }).observe({type:"largest-contentful-paint",buffered:true});
 var cls=0;
 new PerformanceObserver(function(l){var es=l.getEntries();
  for(var i=0;i<es.length;i++)if(!es[i].hadRecentInput)cls+=es[i].value;
  vit.cls=Math.round(cls*1000);
 }).observe({type:"layout-shift",buffered:true});
}catch(e){}
document.addEventListener("visibilitychange",function(){
 if(document.visibilityState==="hidden"&&!vs&&(vit.lcp||vit.fcp||vit.ttfb)){
  vs=true;send("performance","",{m:vit});}});
window.wa={event:function(n){send("event",String(n||"").slice(0,64))}};
pv();
})();"""


class WebAnalyticsController(http.Controller):

    @http.route("/wa/script.js", type="http", auth="public",
                methods=["GET"], csrf=False, cors="*")
    def script(self):
        return request.make_response(SCRIPT_JS, headers=[
            ("Content-Type", "application/javascript; charset=utf-8"),
            ("Cache-Control", "public, max-age=86400"),
        ])

    @http.route("/wa/collect", type="http", auth="public",
                methods=["POST", "OPTIONS"], csrf=False, cors="*")
    def collect(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True) or ""
        if not raw.strip() and kwargs:
            # Body posted as form-urlencoded: werkzeug consumed the stream
            # and the JSON blob became the first form key.
            raw = next(iter(kwargs.keys()), "")
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            return request.make_response("", status=204)
        if not isinstance(payload, dict):
            return request.make_response("", status=204)
        token = (payload.get("token") or "").strip()
        if not token:
            return request.make_response("", status=204)
        site = request.env["web.analytics.site"].sudo().search(
            [("token", "=", token), ("active", "=", True)], limit=1)
        if not site:
            return request.make_response("", status=204)

        user_agent = request.httprequest.headers.get("User-Agent", "")
        if is_bot(user_agent):
            return request.make_response("", status=204)

        host = (payload.get("host") or "")[:128].lower()
        if site.allowed_hosts:
            allowed = [h.strip().lower()
                       for h in site.allowed_hosts.split(",") if h.strip()]
            if host and allowed and host not in allowed:
                return request.make_response("", status=204)

        secret = request.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or "wa"
        # Daily rotation = max privacy; a stable salt (still cookieless,
        # IP never stored) enables weekly retention when the site opts in.
        salt = daily_salt(
            secret,
            fields.Date.to_string(fields.Date.today())
            if site.daily_salt_rotation else "static")
        ip = request.httprequest.remote_addr or ""

        requested_type = payload.get("type")
        event_type = (requested_type if requested_type in (
            "event", "outbound", "error", "performance") else "pageview")
        utm = parse_utm(payload.get("search"))
        ref_host = referrer_host(payload.get("referrer"), host)
        country = ""
        try:
            country = (request.geoip.country_code or "")[:2]
        except Exception:  # noqa: BLE001 — no GeoIP database configured
            pass
        values = {
            "event_type": event_type,
            "event_name": (payload.get("name") or "")[:256],
            "country": country,
            "path": (payload.get("path") or "/")[:512],
            "page_title": (payload.get("title") or "")[:256],
            "referrer_host": ref_host[:128],
            "channel": classify_channel(
                ref_host, utm["utm_medium"], utm["utm_source"],
                utm["has_paid_ids"]),
            "utm_source": utm["utm_source"],
            "utm_medium": utm["utm_medium"],
            "utm_campaign": utm["utm_campaign"],
            "visitor_hash": visitor_hash(salt, ip, user_agent, site.token),
            "lang": (payload.get("lang") or "")[:8],
        }
        device, browser, os_name = parse_device(user_agent)
        values.update({
            "device_type": device, "browser": browser, "os": os_name})
        metrics = payload.get("m") or {}
        if event_type == "performance" and isinstance(metrics, dict):
            def as_ms(key):
                try:
                    return max(0, min(120000, int(metrics.get(key) or 0)))
                except (TypeError, ValueError):
                    return 0
            values.update({
                "lcp_ms": as_ms("lcp"), "fcp_ms": as_ms("fcp"),
                "ttfb_ms": as_ms("ttfb"), "cls_milli": as_ms("cls"),
            })
        request.env["web.analytics.event"].sudo()._ingest(site, values)
        return request.make_response("", status=204)
