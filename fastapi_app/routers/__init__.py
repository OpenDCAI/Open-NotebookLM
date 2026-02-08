from __future__ import annotations

"""
Router package for FastAPI backend (Notebook / frontend-v2).
"""

from . import kb, kb_embedding, files, paper2drawio, paper2ppt

__all__ = ["kb", "kb_embedding", "files", "paper2drawio", "paper2ppt"]
