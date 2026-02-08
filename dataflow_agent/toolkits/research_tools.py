"""
网页搜索工具，与 Paper2Any 一致。
支持 SerpAPI（engine=google 或 engine=baidu）、Google CSE、Brave、博查 Bocha。
并提供 fetch_page_text 抓取网页正文供来源详情展示。
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import httpx


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    text = parser.get_text()
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_page_text(url: str, max_chars: int = 50000) -> str:
    """
    抓取 URL 对应页面的 HTML 并提取正文文本，用于来源详情展示。
    """
    if not url or not url.strip().startswith(("http://", "https://")):
        return ""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OpenNotebook/1.0; +https://opennotebook.ai)"
    }
    try:
        with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
            resp = client.get(url.strip())
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            if "text/html" not in content_type:
                return "[非 HTML 页面，无法解析正文]"
            html = resp.text
    except Exception as e:
        return f"[抓取失败: {e}]"
    text = _strip_html(html)
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "\n\n... (已截断)"
    return text or "[页面无正文内容]"

BOCHA_WEB_SEARCH_URL = "https://api.bocha.cn/v1/web-search"


def _safe_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def serpapi_search(query: str, api_key: str, engine: str = "google", num: int = 10) -> List[Dict[str, Any]]:
    """
    SerpAPI 搜索，支持 Google 与百度（engine="google" | "baidu"）。
    返回与 Fast Research 一致的格式: [{ "title", "link", "snippet" }]。
    """
    params = {
        "engine": engine,
        "q": query,
        "api_key": api_key,
        "num": num,
    }
    with httpx.Client(timeout=20) as client:
        resp = client.get("https://serpapi.com/search.json", params=params)
        resp.raise_for_status()
        data = resp.json()

    results: List[Dict[str, Any]] = []
    for item in data.get("organic_results", [])[:num]:
        url = (item.get("link") or item.get("url") or "").strip()
        snippet = item.get("snippet") or item.get("snippet_highlighted_words") or ""
        if isinstance(snippet, list):
            snippet = " ".join(str(s) for s in snippet)
        results.append({
            "title": (item.get("title") or snippet or "Untitled").strip(),
            "link": url,
            "snippet": (snippet or "").strip(),
            "source": _safe_domain(url),
        })
    return results


def google_cse_search(
    query: str, api_key: str, cx: str, num: int = 10, start: int = 1
) -> List[Dict[str, Any]]:
    """Google Custom Search Engine."""
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": max(1, min(10, num)),
        "start": max(1, start),
    }
    with httpx.Client(timeout=20) as client:
        resp = client.get("https://www.googleapis.com/customsearch/v1", params=params)
        resp.raise_for_status()
        data = resp.json()

    results: List[Dict[str, Any]] = []
    for item in data.get("items", [])[:num]:
        url = (item.get("link") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        results.append({
            "title": (item.get("title") or snippet or "Untitled").strip(),
            "link": url,
            "snippet": snippet,
            "source": _safe_domain(url),
        })
    return results


def brave_search(query: str, api_key: str, count: int = 10) -> List[Dict[str, Any]]:
    """Brave Search API."""
    headers = {"X-Subscription-Token": api_key}
    params = {"q": query, "count": max(1, min(20, count))}
    with httpx.Client(timeout=20, headers=headers) as client:
        resp = client.get("https://api.search.brave.com/res/v1/web/search", params=params)
        resp.raise_for_status()
        data = resp.json()

    results: List[Dict[str, Any]] = []
    for item in data.get("web", {}).get("results", [])[:count]:
        url = (item.get("url") or "").strip()
        results.append({
            "title": (item.get("title") or item.get("description") or "Untitled").strip(),
            "link": url,
            "snippet": (item.get("description") or "").strip(),
            "source": _safe_domain(url),
        })
    return results


def bocha_web_search(
    query: str,
    api_key: str,
    count: int = 10,
    *,
    summary: bool = True,
    freshness: str = "noLimit",
) -> List[Dict[str, Any]]:
    """
    博查 AI 网页搜索 API（https://api.bocha.cn/v1/web-search）。
    鉴权：Authorization: Bearer {API KEY}。
    返回统一格式: [{ "title", "link", "snippet" }]，snippet 优先用 summary 字段。
    """
    payload: Dict[str, Any] = {
        "query": query,
        "count": max(1, min(50, count)),
        "summary": summary,
        "freshness": freshness,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=25) as client:
        resp = client.post(BOCHA_WEB_SEARCH_URL, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    if body.get("code") != 200:
        raise RuntimeError(body.get("msg") or body.get("message") or f"博查 API 返回 code={body.get('code')}")

    data = body.get("data") or {}
    web_pages = data.get("webPages") or {}
    items = web_pages.get("value") or []

    results: List[Dict[str, Any]] = []
    for item in items[:count]:
        url = (item.get("url") or "").strip()
        name = (item.get("name") or "").strip() or "Untitled"
        snippet = (item.get("summary") or item.get("snippet") or "").strip()
        results.append({
            "title": name,
            "link": url,
            "snippet": snippet,
            "source": _safe_domain(url),
        })
    return results
