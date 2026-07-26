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

# Kept deliberately tiny (~1.5 KB): auto pageviews (SPA-aware via history
# patching), custom events via window.wa.event("name").
SCRIPT_JS = r"""(function(){
var s=document.currentScript;if(!s)return;
var t=s.getAttribute("data-token")||"";
var u=s.src.replace(/\/wa\/script\.js.*$/,"/wa/collect");
function send(type,name){
 var p={token:t,type:type,name:name||"",host:location.hostname,
  path:location.pathname,title:document.title.slice(0,256),
  referrer:document.referrer||"",search:location.search||"",
  lang:(navigator.language||"").slice(0,8)};
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
        salt = daily_salt(
            secret, fields.Date.to_string(fields.Date.today()))
        ip = request.httprequest.remote_addr or ""

        event_type = ("event" if payload.get("type") == "event"
                      else "pageview")
        utm = parse_utm(payload.get("search"))
        ref_host = referrer_host(payload.get("referrer"), host)
        values = {
            "event_type": event_type,
            "event_name": (payload.get("name") or "")[:64],
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
        request.env["web.analytics.event"].sudo()._ingest(site, values)
        return request.make_response("", status=204)
