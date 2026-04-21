"""KGGen 工具包：从文本块抽取三元组，以及合并两个 ``kg_gen.Graph``。

【数据流】
    ``extract_kg`` / ``extract_kg_from_chunks``：输出带 ``source_chunk_ids`` 的关系列表，便于回溯；
    ``merge_two_kgs``：对两个图做集合合并（可选 ``dedupe`` 占位）。

默认用户路径为 ``skip_kggen=True``，GraphRAG 索引不依赖本包；仅 ``skip_kggen=False`` 时由 ``wf_graphrag_kb`` 调用。
"""
from workflow_engine.toolkits.kggen_tool.kg_extractor import extract_kg, extract_kg_from_chunks
from workflow_engine.toolkits.kggen_tool.kg_merger import merge_two_kgs

__all__ = ["extract_kg", "extract_kg_from_chunks", "merge_two_kgs"]
