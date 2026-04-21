"""Use Wikidata API to look up subgraph entity names and append short reference text.

Search uses ``wbsearchentities`` (no prior entity alignment); labels/descriptions use
``wbgetentities``. Intended to be called via ``asyncio.to_thread`` from GraphRAG workflows.

See https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy — a descriptive User-Agent is required.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, RequestException, Timeout

from workflow_engine.logger import get_logger

log = get_logger(__name__)

_WIKIDATA_UA = "OpenNotebookLM/1.0 (GraphRAG subgraph Wikidata enrich; local research bot)"
_QID_RE = re.compile(r"^Q[1-9]\d*$", re.IGNORECASE)


@dataclass
class _WikidataRuntimeStats:
    network_failures: int = 0
    timeout_failures: int = 0


def _preferred_lang_chain(lang: str) -> Tuple[str, ...]:
    lg = (lang or "").strip().lower()
    if lg.startswith("zh"):
        return ("zh-cn", "zh-hans", "zh", "zh-tw", "zh-hant", "en")
    if lg.startswith("en"):
        return ("en", "zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant")
    return (lg, "en", "zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant")


def _unique_entity_terms(edges: List[Dict[str, Any]], max_terms: int) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        for key in ("source", "target"):
            raw = str(e.get(key) or "").strip()
            if len(raw) < 2 or len(raw) > 200:
                continue
            low = raw.casefold()
            if low in seen:
                continue
            seen.add(low)
            out.append(raw)
            if len(out) >= max_terms:
                return out
    return out


def _wb_get(
    session: requests.Session,
    api_url: str,
    params: Dict[str, Any],
    *,
    connect_timeout: float,
    read_timeout: float,
    http_retries: int = 2,
    stats: Optional[_WikidataRuntimeStats] = None,
) -> Optional[dict]:
    """GET Wikimedia API; retries on read/connect timeout only."""
    timeout_tpl = (float(connect_timeout), float(read_timeout))
    attempts = max(1, int(http_retries) + 1)
    action = params.get("action")
    for attempt in range(attempts):
        try:
            r = session.get(api_url, params=params, timeout=timeout_tpl)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else None
        except (Timeout, RequestsConnectionError) as exc:
            if stats is not None:
                stats.network_failures += 1
                if isinstance(exc, Timeout):
                    stats.timeout_failures += 1
            if attempt + 1 < attempts:
                wait = 0.6 * (attempt + 1)
                log.info(
                    "[Wikidata] retry %d/%d in %.1fs | action=%s | %s",
                    attempt + 1,
                    attempts,
                    wait,
                    action,
                    exc,
                )
                time.sleep(wait)
                continue
            log.warning(
                "[Wikidata] HTTP/API failed after %d tries | action=%s | %s",
                attempts,
                action,
                exc,
            )
            return None
        except HTTPError as exc:
            if stats is not None:
                stats.network_failures += 1
            log.warning("[Wikidata] HTTP error | action=%s | %s", action, exc)
            return None
        except RequestException as exc:
            if stats is not None:
                stats.network_failures += 1
            log.warning("[Wikidata] request error | action=%s | %s", action, exc)
            return None
        except (ValueError, TypeError) as exc:
            log.warning("[Wikidata] invalid JSON | action=%s | %s", action, exc)
            return None
    return None


def _search_qid(
    session: requests.Session,
    api_url: str,
    term: str,
    lang: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    http_retries: int,
    stats: Optional[_WikidataRuntimeStats] = None,
) -> Optional[str]:
    params = {
        "action": "wbsearchentities",
        "format": "json",
        "language": lang,
        "uselang": lang,
        "search": term,
        "limit": 1,
        "type": "item",
    }
    data = _wb_get(
        session,
        api_url,
        params,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        http_retries=http_retries,
        stats=stats,
    )
    if not data:
        return None
    arr = data.get("search")
    if not isinstance(arr, list) or not arr:
        return None
    first = arr[0]
    if not isinstance(first, dict):
        return None
    qid = str(first.get("id") or "").strip().upper()
    return qid if _QID_RE.match(qid) else None


def _pick_lang_value(obj: Any, lang_chain: Tuple[str, ...]) -> str:
    if not isinstance(obj, dict):
        return ""
    for lg in lang_chain:
        block = obj.get(lg)
        if isinstance(block, dict):
            v = str(block.get("value") or "").strip()
            if v:
                return v
    for _k, block in obj.items():
        if isinstance(block, dict):
            v = str(block.get("value") or "").strip()
            if v:
                return v
    return ""


def _batch_get_entities(
    session: requests.Session,
    api_url: str,
    qids: List[str],
    langs: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    http_retries: int,
    stats: Optional[_WikidataRuntimeStats] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return map qid_upper -> entity dict from wbgetentities."""
    out: Dict[str, Dict[str, Any]] = {}
    chunk = 20
    for i in range(0, len(qids), chunk):
        batch = qids[i : i + chunk]
        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(batch),
            "props": "labels|descriptions",
            "languages": langs,
            "languagefallback": 1,
        }
        data = _wb_get(
            session,
            api_url,
            params,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            http_retries=http_retries,
            stats=stats,
        )
        if not data:
            continue
        entities = data.get("entities")
        if not isinstance(entities, dict):
            continue
        for qid, ent in entities.items():
            if isinstance(ent, dict) and qid.upper().startswith("Q"):
                out[qid.upper()] = ent
        time.sleep(0.05)
    return out


def _trunc(s: str, n: int = 120) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def format_wikidata_supplement_for_subgraph(
    edges: List[Dict[str, Any]],
    *,
    lang: str = "zh",
    max_entities: int = 8,
    connect_timeout: float = 10.0,
    read_timeout: float = 45.0,
    http_retries: int = 2,
    api_url: str = "https://www.wikidata.org/w/api.php",
    emit_failure_hint: bool = False,
) -> str:
    """Build a short Markdown block for user-facing answer tail, or empty string."""
    t0 = time.perf_counter()
    if not edges:
        log.info("[Wikidata] skip: empty subgraph (0 edges)")
        return ""

    terms = _unique_entity_terms(edges, max_terms=max(1, max_entities * 2))
    log.info(
        "[Wikidata] start | edges=%d | max_entities=%d | lang=%s | terms=%d | "
        "connect=%.1fs read=%.1fs retries=%d | sample=%s",
        len(edges),
        max_entities,
        lang,
        len(terms),
        connect_timeout,
        read_timeout,
        http_retries,
        [_trunc(t, 80) for t in terms[:8]],
    )
    if not terms:
        log.info("[Wikidata] skip: no source/target strings in subgraph (after length/dedupe filter)")
        return ""

    session = requests.Session()
    session.headers.update({"User-Agent": _WIKIDATA_UA})
    stats = _WikidataRuntimeStats()

    resolved: List[Tuple[str, str]] = []  # (original_term_or_qid, qid)
    seen_q: Set[str] = set()
    lang = (lang or "en").strip() or "en"
    lang_chain = _preferred_lang_chain(lang)

    for term in terms:
        if len(resolved) >= max_entities:
            log.info("[Wikidata] stop: reached max_entities=%d", max_entities)
            break
        if _QID_RE.match(term):
            qid = term.upper()
            log.info("[Wikidata] resolve | term=%r -> %s (literal QID)", _trunc(term, 100), qid)
        else:
            time.sleep(0.08)
            qid = (
                _search_qid(
                    session,
                    api_url,
                    term,
                    lang,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                    http_retries=http_retries,
                    stats=stats,
                )
                or ""
            )
            if qid:
                log.info(
                    "[Wikidata] resolve | term=%r -> %s (wbsearchentities first hit)",
                    _trunc(term, 100),
                    qid,
                )
            else:
                log.info(
                    "[Wikidata] resolve | term=%r -> NO_HIT (empty search or API error, see warnings above)",
                    _trunc(term, 100),
                )
        if not qid or qid in seen_q:
            if qid and qid in seen_q:
                log.info("[Wikidata] skip duplicate QID %s for term=%r", qid, _trunc(term, 80))
            continue
        seen_q.add(qid)
        resolved.append((term, qid))

    if not resolved:
        log.info(
            "[Wikidata] skip: zero QIDs resolved | tried=%d terms | elapsed=%.2fs",
            len(terms),
            time.perf_counter() - t0,
        )
        if emit_failure_hint and stats.network_failures > 0:
            if lang.casefold().startswith("en"):
                return (
                    "---\n"
                    "**Wikidata reference unavailable**\n"
                    "- Connection to Wikidata timed out or failed.\n"
                    "- Please configure outbound proxy for this server "
                    "(e.g. `HTTPS_PROXY`/`HTTP_PROXY`) or increase Wikidata timeout settings."
                )
            return (
                "---\n"
                "**Wikidata 参考暂不可用**\n"
                "- 连接 Wikidata 超时或失败。\n"
                "- 需要为服务端配置代理（如 `HTTPS_PROXY`/`HTTP_PROXY`），"
                "或调大 Wikidata 超时参数。"
            )
        return ""

    qids = [q for _, q in resolved]
    langs_param = "|".join(dict.fromkeys(lang_chain).keys())
    ent_map = _batch_get_entities(
        session,
        api_url,
        qids,
        langs_param,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        http_retries=http_retries,
        stats=stats,
    )
    missing = [q for q in qids if q not in ent_map]
    if missing:
        log.warning(
            "[Wikidata] wbgetentities missing %d/%d ids (will use fallback labels): %s",
            len(missing),
            len(qids),
            missing[:10],
        )

    if lang.casefold().startswith("en"):
        header = "**Wikidata reference** (auto search from subgraph entity names; not entity-aligned)"
    else:
        header = "**Wikidata 参考**（由子图实体名自动检索，未做实体对齐，仅供参考）"
    lines: List[str] = ["---", header]
    for term, qid in resolved:
        ent = ent_map.get(qid) or {}
        label = _pick_lang_value(ent.get("labels"), lang_chain)
        if not label:
            label = term if not _QID_RE.match(term) else qid
        desc = _pick_lang_value(ent.get("descriptions"), lang_chain)
        url = f"https://www.wikidata.org/wiki/{qid}"
        if desc:
            lines.append(f"- [{label}]({url}) — {desc}")
        else:
            lines.append(f"- [{label}]({url})")

    elapsed = time.perf_counter() - t0
    log.info(
        "[Wikidata] supplement built | qids=%s | markdown_lines=%d | elapsed=%.2fs",
        qids,
        len(lines),
        elapsed,
    )
    return "\n".join(lines)
