"""
RAG storage paths.

Why this exists:
- Many RAG modules used CWD-relative paths like ./chroma_db, ./few_shot_data.
- In practice the process CWD may be repo root or backend/, causing silent "no data" behavior.
- This helper makes persistence location stable across launch directories while keeping backward compatibility.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _repo_root() -> Path:
    # backend/modules/rag/storage.py -> backend/modules/rag -> backend/modules -> backend -> repo_root
    return Path(__file__).resolve().parents[3]


def _backend_root() -> Path:
    # backend/modules/rag/storage.py -> backend/modules/rag -> backend/modules -> backend
    return Path(__file__).resolve().parents[2]


def rag_dir(name: str, base_dir: Optional[str] = None) -> Path:
    """
    Returns a stable persistence directory for a RAG component.

    Precedence:
    1) Explicit base_dir argument
    2) Env var SQLBOT_RAG_DIR
    3) Existing directory under repo root or backend root (backward compatible)
    4) Default to repo root / name
    """
    if base_dir:
        return Path(base_dir) / name

    env_base = os.getenv("SQLBOT_RAG_DIR")
    if env_base:
        return Path(env_base) / name

    repo_root = _repo_root()
    backend_root = _backend_root()

    candidates = [
        repo_root / name,
        backend_root / name,
    ]
    for c in candidates:
        if c.exists():
            return c

    return repo_root / name

