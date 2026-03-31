"""KGGen-based KG extraction — currently unused; kept for optional integration."""
# from __future__ import annotations

# import os
# from typing import Any, Dict, List, Optional

# from workflow_engine.logger import get_logger

# log = get_logger(__name__)


# def normalize_model_for_litellm(model: str) -> str:
#     """dspy/kg-gen routes calls through LiteLLM, which requires ``provider/model``.

#     Bare names like ``deepseek-v3.2`` raise *LLM Provider NOT provided*.  This project
#     defaults to OpenAI-compatible gateways (``api_base`` + deployment id), so we
#     prefix ``openai/`` when no provider is present.  If you use another LiteLLM
#     provider, set the full id in config (e.g. ``deepseek/deepseek-chat``).
#     """
#     m = (model or "").strip()
#     if not m or "/" in m:
#         return m
#     return f"openai/{m}"


# def kggen_init_extras(litellm_model: str) -> Dict[str, Any]:
#     """Extra ``KGGen(...)`` kwargs required by kg-gen's own validators.

#     For GPT-5–family ids, ``kg_gen.KGGen`` enforces ``temperature == 1.0`` and
#     ``max_tokens >= 16000`` (see ``validate_temperature`` / ``validate_max_tokens``).
#     """
#     m = (litellm_model or "").lower()
#     if "gpt-5" in m:
#         return {"temperature": 1.0, "max_tokens": 16000}
#     return {}


# def _get_kggen(model: str, api_base: str, api_key: str):
#     """Import KGGen and return a configured instance.

#     Raises ImportError if kg_gen is not installed.
#     """
#     try:
#         from kg_gen import KGGen  # type: ignore[import]
#     except ImportError as exc:
#         raise ImportError(
#             "kg-gen is not installed. Run: pip install kg-gen"
#         ) from exc

#     litellm_model = normalize_model_for_litellm(model)
#     if litellm_model != model.strip():
#         log.debug("[KGGen] LiteLLM model id: %r → %r", model, litellm_model)

#     extras = kggen_init_extras(litellm_model)
#     return KGGen(
#         model=litellm_model,
#         api_base=api_base,
#         api_key=api_key,
#         **extras,
#     )


# def _default_settings():
#     from fastapi_app.config.settings import settings
#     return settings


# def extract_kg(
#     text: str,
#     source_chunk_ids: Optional[List[str]] = None,
#     *,
#     model: Optional[str] = None,
#     api_base: Optional[str] = None,
#     api_key: Optional[str] = None,
# ) -> Dict[str, Any]:
#     """Extract a knowledge graph from *text* and annotate with chunk IDs.

#     Parameters
#     ----------
#     text:
#         The raw text to extract triples from.
#     source_chunk_ids:
#         List of chunk_id values the text originated from.  Stored on every
#         relation in the result under ``source_chunk_ids``.
#     model / api_base / api_key:
#         LLM settings; fall back to ``settings.KGGEN_MODEL`` / ``DEFAULT_LLM_API_URL``.

#     Returns
#     -------
#     dict with keys:
#         ``entities`` (list[str])
#         ``relations`` (list[dict]) — each dict has keys:
#             ``subject``, ``predicate``, ``object``, ``source_chunk_ids``
#         ``raw_graph`` — the original ``kg_gen.Graph`` object
#     """
#     cfg = _default_settings()
#     model = model or cfg.KGGEN_MODEL
#     api_base = api_base or cfg.DEFAULT_LLM_API_URL.rstrip("/")
#     api_key = api_key or os.getenv("DF_API_KEY", "")

#     kggen = _get_kggen(model, api_base, api_key)
#     # kg-gen 0.3.x / 0.4.x: first argument is *input_data* (str or message list), not input_text.
#     graph = kggen.generate(text)

#     chunk_ids = source_chunk_ids or []

#     relations = []
#     # Triples live on graph.relations (set of (s, p, o)). graph.edges is only predicate labels.
#     for edge in (graph.relations or []):
#         # KGGen edge can be a tuple (subj, pred, obj) or a dict
#         if isinstance(edge, (list, tuple)) and len(edge) >= 3:
#             subj, pred, obj = edge[0], edge[1], edge[2]
#         elif isinstance(edge, dict):
#             subj = edge.get("source") or edge.get("subject", "")
#             pred = edge.get("relation") or edge.get("predicate", "")
#             obj = edge.get("target") or edge.get("object", "")
#         else:
#             continue
#         relations.append(
#             {
#                 "subject": str(subj),
#                 "predicate": str(pred),
#                 "object": str(obj),
#                 "source_chunk_ids": chunk_ids,
#             }
#         )

#     return {
#         "entities": list(graph.entities or []),
#         "relations": relations,
#         "raw_graph": graph,
#     }


# def extract_kg_from_chunks(
#     chunks: List[Dict[str, Any]],
#     *,
#     model: Optional[str] = None,
#     api_base: Optional[str] = None,
#     api_key: Optional[str] = None,
# ) -> Dict[str, Any]:
#     """Extract and merge KGs from a list of chunk dicts.

#     Each item in *chunks* must have at least ``chunk_id`` and ``text`` keys
#     (as produced by ``SourceManager.get_chunks_with_meta``).

#     Returns the same shape as ``extract_kg`` but with relations carrying
#     ``source_chunk_ids`` from their respective chunk.
#     """
#     cfg = _default_settings()
#     per_chunk: bool = cfg.KGGEN_PER_CHUNK
#     log_iv = int(getattr(cfg, "KGGEN_LOG_CHUNK_INTERVAL", 10) or 0)

#     if per_chunk:
#         all_entities: List[str] = []
#         all_relations: List[Dict[str, Any]] = []
#         raw_graphs = []

#         to_process = [c for c in chunks if (c.get("text") or "").strip()]
#         total = len(to_process)
#         if log_iv == 0:
#             log.info("[KGGen] per-chunk: starting %d chunks (progress logs off)", total)
#         else:
#             log.info(
#                 "[KGGen] per-chunk: starting %d chunks (interval=%d, set KGGEN_LOG_CHUNK_INTERVAL=1 for each)",
#                 total,
#                 log_iv,
#             )

#         def _log_chunk_progress(i: int, cid: str) -> None:
#             if log_iv == 0:
#                 return
#             if log_iv == 1:
#                 log.info("[KGGen] chunk %d/%d id=%s", i, total, cid)
#                 return
#             if i == 1 or i == total or (i % log_iv) == 0:
#                 log.info("[KGGen] chunk %d/%d id=%s", i, total, cid)

#         for i, chunk in enumerate(to_process, start=1):
#             cid = chunk.get("chunk_id", "")
#             text = (chunk.get("text") or "").strip()
#             _log_chunk_progress(i, cid or "?")
#             try:
#                 result = extract_kg(
#                     text,
#                     source_chunk_ids=[cid],
#                     model=model,
#                     api_base=api_base,
#                     api_key=api_key,
#                 )
#                 all_entities.extend(result["entities"])
#                 all_relations.extend(result["relations"])
#                 raw_graphs.append(result["raw_graph"])
#             except Exception as exc:
#                 log.warning("[KGGen] chunk %s extraction failed: %s", cid, exc)

#         if log_iv == 0:
#             log.info("[KGGen] per-chunk: finished %d chunks", total)
#         else:
#             log.info("[KGGen] per-chunk: finished %d chunks", total)

#         return {
#             "entities": list(set(all_entities)),
#             "relations": all_relations,
#             "raw_graphs": raw_graphs,
#         }

#     # Whole-document mode: concatenate text, collect all chunk_ids
#     n = len([c for c in chunks if (c.get("text") or "").strip()])
#     log.info("[KGGen] whole-document mode: 1 LLM call over %d chunks (text merged)", n)
#     full_text = "\n\n".join(c.get("text", "") for c in chunks if c.get("text"))
#     all_ids = [c["chunk_id"] for c in chunks if c.get("chunk_id")]
#     return extract_kg(
#         full_text,
#         source_chunk_ids=all_ids,
#         model=model,
#         api_base=api_base,
#         api_key=api_key,
#     )
