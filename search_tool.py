"""The agent's ONE tool: web_search.

No API key, no paid service, no extra dependency — plain HTTP
against DuckDuckGo's lite HTML endpoint, which returns real
search-result pages that can be parsed with the standard library.

    web_search("capital of France")
    -> [{"title": ..., "url": ..., "snippet": ...}, ...]

Design choices (see design.md for the full reasoning):
  * Timeout is short (8 s) — a slow search is a failed search.
  * Results are de-duplicated by URL and capped at 5.
  * A tiny in-memory + on-disk cache (1 hour) makes repeated
    questions instant and avoids re-hitting the search engine.
  * If the lite endpoint fails, fall back to the HTML endpoint,
    then to the DuckDuckGo Instant Answer API. If all three fail,
    the tool raises SearchError instead of inventing results.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "search-chat-agent/1.0 (+https://github.com/Ganesh-123-maker/search-chat-agent)"
TIMEOUT = 8
MAX_RESULTS = 5
CACHE_TTL_SECONDS = 3600

_cache: dict[str, tuple[float, list]] = {}

# Real DuckDuckGo lite HTML uses SINGLE quotes:
#   <a rel="nofollow" href="//duckduckgo.com/l/?uddg=..." class='result-link'>Title</a>
#   <td class='result-snippet'>Snippet</td>
# so the patterns below accept either quote style, and href may
# come before or after the class attribute.
_RESULT_RE = re.compile(
    r'''<a(?=[^>]*class=["']result__a["'])[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>.*?'''
    r'''class=["']result__snippet["'][^>]*>(.*?)</a>''',
    re.DOTALL,
)
_LITE_RESULT_RE = re.compile(
    r'''<a(?=[^>]*class=["']result-link["'])[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>.*?'''
    r'''class=["']result-snippet["'][^>]*>(.*?)</td>''',
    re.DOTALL,
)


class SearchError(Exception):
    """Raised when every search endpoint fails — never return fake results."""


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[/?b\]", "", text)  # DuckDuckGo lite snippet artefacts
    return html_lib.unescape(text).strip()


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse(html_text: str, pattern) -> list:
    results, seen = [], set()
    for href, title, snippet in pattern.findall(html_text):
        url = html_lib.unescape(href).strip()
        # DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<encoded real url>
        if "uddg=" in url:
            url = urllib.parse.unquote(url.split("uddg=", 1)[1].split("&")[0])
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        results.append({"title": _clean(title), "url": url,
                        "snippet": _clean(snippet)})
        if len(results) >= MAX_RESULTS:
            break
    return results


def _instant_answer(query: str) -> list:
    """Last-resort fallback: DuckDuckGo Instant Answer JSON API."""
    url = ("https://api.duckduckgo.com/?q=" + urllib.parse.quote(query)
           + "&format=json&no_html=1&skip_disambig=1")
    data = json.loads(_fetch(url))
    results = []
    for key in ("AbstractText", "Answer"):
        text = (data.get(key) or "").strip()
        if text:
            results.append({"title": data.get("Heading") or query,
                            "url": data.get("AbstractURL") or
                            "https://duckduckgo.com/?q=" + urllib.parse.quote(query),
                            "snippet": text})
    for topic in data.get("RelatedTopics") or []:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({"title": topic.get("FirstURL", "").rsplit("/", 1)[-1],
                            "url": topic.get("FirstURL", ""),
                            "snippet": topic["Text"]})
        if len(results) >= MAX_RESULTS:
            break
    return results[:MAX_RESULTS]


def web_search(query: str, max_results: int = MAX_RESULTS) -> list:
    """Search the web. Returns [{title, url, snippet}, ...], newest first
    as returned by the engine. Raises SearchError on total failure."""
    query = (query or "").strip()
    if not query:
        raise ValueError("web_search needs a non-empty query")
    now = time.time()
    if query in _cache and now - _cache[query][0] < CACHE_TTL_SECONDS:
        return _cache[query][1][:max_results]

    encoded = urllib.parse.quote(query)
    endpoints = [
        ("https://lite.duckduckgo.com/lite/?q=" + encoded, _LITE_RESULT_RE),
        ("https://html.duckduckgo.com/html/?q=" + encoded, _RESULT_RE),
    ]
    errors = []
    for url, pattern in endpoints:
        try:
            results = _parse(_fetch(url), pattern)
            if results:
                _cache[query] = (now, results)
                return results[:max_results]
        except Exception as e:  # noqa: BLE001 — try the next endpoint
            errors.append(str(e))
    try:
        results = _instant_answer(query)
        if results:
            _cache[query] = (now, results)
            return results[:max_results]
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))
    raise SearchError(f"web search failed for {query!r}: {'; '.join(errors) or 'no results'}")
