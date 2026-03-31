"""KGGen-based KG merging — currently unused; kept for optional integration."""
# from __future__ import annotations

# from typing import Any, Optional

# from workflow_engine.logger import get_logger
# from workflow_engine.toolkits.kggen_tool.kg_extractor import (
#     kggen_init_extras,
#     normalize_model_for_litellm,
# )

# log = get_logger(__name__)


# def _deduplicate_merged_graph(merged: Any, kggen: Any) -> Any:
#     """Semantic deduplication after aggregate. Placeholder for next release.

#     Parameters are reserved for a future implementation (e.g. ``kggen`` or custom LLM).
#     """
#     pass

#     return merged


# def merge_two_kgs(
#     graph_a: Any,
#     graph_b: Any,
#     *,
#     dedupe: bool = False,
#     model: Optional[str] = None,
#     api_base: Optional[str] = None,
#     api_key: Optional[str] = None,
# ) -> Any:
#     """合并两个 ``kg_gen.Graph`` 为一张图（实体/关系/边集合并）。

#     ``graph_a`` / ``graph_b`` 通常来自 ``extract_kg`` 的 ``raw_graph``；
#     ``dedupe=True`` 时在聚合后调用占位去重（当前无实际逻辑）；
#     若未安装 kg-gen 则 ``ImportError``。
#     """
#     try:
#         from kg_gen import KGGen  # type: ignore[import]
#     except ImportError as exc:
#         raise ImportError("kg-gen is not installed. Run: pip install kg-gen") from exc

#     import os

#     from kg_gen.models import Graph as KGGraph  # type: ignore[import]

#     # kg-gen exposes aggregate as an instance method; mirror its set-union logic so we
#     # do not rely on KGGen.aggregate([...]) (invalid call) or a dummy KGGen instance.
#     def _union_graphs(graphs: list[Any]) -> Any:
#         all_entities: set = set()
#         all_relations: set = set()
#         all_edges: set = set()
#         for g in graphs:
#             all_entities.update(g.entities)
#             all_relations.update(g.relations)
#             all_edges.update(g.edges)
#         return KGGraph(entities=all_entities, relations=all_relations, edges=all_edges)

#     merged = _union_graphs([graph_a, graph_b])
#     log.info(
#         "[KGMerger] aggregate → %d entities, %d edges",
#         len(merged.entities or []),
#         len(merged.edges or []),
#     )

#     if dedupe:
#         cfg_model = model
#         cfg_base = api_base
#         cfg_key = api_key
#         if not cfg_model:
#             from fastapi_app.config.settings import settings
#             cfg_model = settings.KGGEN_MODEL
#             cfg_base = cfg_base or settings.DEFAULT_LLM_API_URL.rstrip("/")
#             cfg_key = cfg_key or os.getenv("DF_API_KEY", "")

#         lm_model = normalize_model_for_litellm(cfg_model)
#         kggen = KGGen(
#             model=lm_model,
#             api_base=cfg_base,
#             api_key=cfg_key,
#             **kggen_init_extras(lm_model),
#         )
#         merged = _deduplicate_merged_graph(merged, kggen)

#     return merged
