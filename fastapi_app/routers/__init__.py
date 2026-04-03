from __future__ import annotations

"""
Router package for FastAPI backend (Notebook / frontend-v2).
"""

from . import auth, data_extract, files, kb, kb_embedding, kb_notebooks, kb_sources, paper2drawio, paper2ppt

__all__ = ["auth", "data_extract", "kb", "kb_embedding", "kb_notebooks", "kb_sources", "files", "paper2drawio", "paper2ppt"]
