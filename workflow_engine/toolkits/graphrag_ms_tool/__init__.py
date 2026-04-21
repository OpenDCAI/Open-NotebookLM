"""微软 GraphRAG 工具包（索引 / 查询 / 置信度 Judge）。

数据流（与 ``wf_graphrag_kb`` 配合）：
    建索引：``build_index`` ← Step1 的 chunk 列表 → 写 ``input/*.txt`` + ``chunk_meta.json`` → ``graphrag index``
    查询：``query_local`` / ``query_global`` → ``QueryResult``（answer、context_data、子图、chunk 回溯）
    打分：``judge_confidence`` ← 问题 + 答案 + 推理子图边列表 → ``JudgeResult.score``

本包不负责 HTTP；FastAPI 经 ``wa_graphrag_kb`` 调用工作流，工作流再调用上述函数。
"""
from workflow_engine.toolkits.graphrag_ms_tool.indexer import build_index, GraphRAGWorkspace
from workflow_engine.toolkits.graphrag_ms_tool.querier import query_local, query_global, QueryResult
from workflow_engine.toolkits.graphrag_ms_tool.judge import judge_confidence

__all__ = [
    "build_index",
    "GraphRAGWorkspace",
    "query_local",
    "query_global",
    "QueryResult",
    "judge_confidence",
]
