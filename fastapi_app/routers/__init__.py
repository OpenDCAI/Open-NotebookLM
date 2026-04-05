from __future__ import annotations

"""
Router package for FastAPI backend (Notebook / frontend-v2).
"""

from . import auth, data_extract, files, kb, kb_embedding, paper2drawio, paper2ppt, table_processing

__all__ = ["auth", "data_extract", "kb", "kb_embedding", "files", "paper2drawio", "paper2ppt", "table_processing"]
