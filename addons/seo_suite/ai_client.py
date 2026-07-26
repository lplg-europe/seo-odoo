# -*- coding: utf-8 -*-
"""Minimal AI completion client (Claude / Gemini) — stdlib only, BYO key.

Raw HTTP on purpose: the module must install on any Odoo without extra
Python dependencies, so we cannot require the official anthropic /
google-genai SDKs. Only imported when an AI action is triggered.

Claude notes (Messages API, anthropic-version 2023-06-01):
- default model claude-opus-4-8; do NOT send temperature/top_p/top_k
  (removed on Opus 4.7+ — the API returns a 400)
- responses may end with stop_reason "refusal"; surfaced as an AiError
"""
import json
import urllib.error
import urllib.request

USER_AGENT = "SEO-Suite-Bot/0.2"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODELS = {
    "claude": "claude-opus-4-8",
    "gemini": "gemini-2.5-flash",
}


class AiError(Exception):
    """Raised with a user-presentable message on any AI failure."""


def _post_json(url, payload, headers, timeout):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers, **{"User-Agent": USER_AGENT,
                                 "Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8"))
            detail = (body.get("error") or {}).get("message", "")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise AiError("AI provider HTTP %d%s" % (
            e.code, ": %s" % detail if detail else ""))
    except Exception as e:
        raise AiError("AI call failed: %s" % e)


def _complete_claude(api_key, prompt, system, model, max_tokens, timeout):
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    data = _post_json(ANTHROPIC_API, payload, {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }, timeout)
    if data.get("stop_reason") == "refusal":
        raise AiError("Claude declined this request (safety refusal).")
    text = "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text")
    if not text:
        raise AiError("Claude returned no text (stop_reason: %s)."
                      % data.get("stop_reason"))
    return text


def _complete_gemini(api_key, prompt, system, model, max_tokens, timeout):
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    data = _post_json(
        "%s/%s:generateContent?key=%s" % (GEMINI_API, model, api_key),
        payload, {}, timeout)
    candidates = data.get("candidates") or []
    if not candidates:
        raise AiError("Gemini returned no candidates (%s)."
                      % ((data.get("promptFeedback") or {})
                         .get("blockReason", "unknown reason")))
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        raise AiError("Gemini returned no text.")
    return text


def complete(provider, api_key, prompt, system=None, model=None,
             max_tokens=2048, timeout=120):
    """One-shot completion. Returns the response text or raises AiError."""
    model = (model or "").strip() or DEFAULT_MODELS.get(provider)
    if provider == "claude":
        return _complete_claude(
            api_key, prompt, system, model, max_tokens, timeout)
    if provider == "gemini":
        return _complete_gemini(
            api_key, prompt, system, model, max_tokens, timeout)
    raise AiError("Unknown AI provider: %s" % provider)


def extract_json(text):
    """Parse a JSON object out of a model response (tolerates fences and
    surrounding prose). Raises AiError if no object can be parsed."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if "```" in stripped:
            stripped = stripped[:stripped.rindex("```")]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise AiError("The AI response contained no JSON object:\n%s"
                      % text[:400])
    try:
        return json.loads(stripped[start:end + 1])
    except ValueError as e:
        raise AiError("Could not parse the AI JSON response (%s):\n%s"
                      % (e, text[:400]))
