"""
Fast Research: 使用搜索引擎获取 top-N 结果，供用户作为「来源」引入。
与 Paper2Any 一致，支持：
- Serper (Google，环境变量 SERPER_API_KEY)
- SerpAPI（Google / 百度，传 search_api_key + search_engine）
- Google CSE、Brave、博查 Bocha（可选）
"""
from __future__ import annotations

import os
from typing import Any, List, Dict, Optional

import httpx

from dataflow_agent.logger import get_logger

from dataflow_agent.toolkits.research_tools import (
    serpapi_search,
    google_cse_search,
    brave_search,
    bocha_web_search,
)

log = get_logger(__name__)

SERPER_API_URL = "https://google.serper.dev/search"


def _serper_search(query: str, top_k: int) -> List[Dict[str, Any]]:
    """Serper (google.serper.dev) 仅支持 Google。"""
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return []
    payload = {"q": query, "num": min(top_k, 20)}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(SERPER_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("[fast_research] Serper request failed: %s", e)
        return []
    organic = data.get("organic") or []
    results: List[Dict[str, Any]] = []
    for i, item in enumerate(organic[:top_k]):
        results.append({
            "title": (item.get("title") or "").strip() or f"Result {i+1}",
            "link": (item.get("link") or "").strip(),
            "snippet": (item.get("snippet") or "").strip(),
        })
    return results


def fast_research_search(
    query: str,
    top_k: int = 10,
    *,
    search_provider: str = "serper",
    search_api_key: Optional[str] = None,
    search_engine: str = "google",
    google_cse_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    统一搜索入口，返回 [{ "title", "link", "snippet" }]。
    - search_provider: "serper" | "serpapi" | "google_cse" | "brave" | "bocha"
    - search_engine: 仅 serpapi 时有效，"google" | "baidu"
    - search_api_key: serpapi / google_cse / brave / bocha 必填；serper 用环境变量 SERPER_API_KEY
    """
    top_k = max(1, min(50, top_k))
    provider = (search_provider or "serper").lower().strip()
    log.info("[fast_research] search: query=%r, top_k=%s, provider=%s", query[:200], top_k, provider)

    if provider == "serper":
        results = _serper_search(query, min(20, top_k))
        log.info("[fast_research] serper 返回 %s 条来源: %s", len(results), [r.get("title", "")[:50] for r in results])
        return results

    api_key = (search_api_key or "").strip()
    if not api_key:
        log.warning("[fast_research] %s 需要 search_api_key", provider)
        return []

    try:
        if provider == "serpapi":
            engine = (search_engine or "google").lower().strip()
            if engine not in ("google", "baidu"):
                engine = "google"
            raw = serpapi_search(query=query, api_key=api_key, engine=engine, num=min(20, top_k))
            log.info("[fast_research] serpapi(%s) 返回 %s 条来源: %s", engine, len(raw), [r.get("title", "")[:50] for r in raw])
            return raw  # 已是 { title, link, snippet }
        if provider == "google_cse":
            if not (google_cse_id or "").strip():
                log.warning("[fast_research] google_cse 需要 google_cse_id (cx)")
                return []
            raw = google_cse_search(
                query=query, api_key=api_key, cx=(google_cse_id or "").strip(), num=min(10, top_k)
            )
            log.info("[fast_research] google_cse 返回 %s 条来源: %s", len(raw), [r.get("title", "")[:50] for r in raw])
            return raw
        if provider == "brave":
            raw = brave_search(query=query, api_key=api_key, count=min(20, top_k))
            log.info("[fast_research] brave 返回 %s 条来源: %s", len(raw), [r.get("title", "")[:50] for r in raw])
            return raw
        if provider == "bocha":
            raw = bocha_web_search(query=query, api_key=api_key, count=top_k)
            log.info("[fast_research] bocha 返回 %s 条来源: %s", len(raw), [r.get("title", "")[:50] for r in raw])
            return raw
    except Exception as e:
        log.warning("[fast_research] %s search failed: %s", provider, e)
        return []

    log.warning("[fast_research] Unsupported provider: %s", provider)
    return []
