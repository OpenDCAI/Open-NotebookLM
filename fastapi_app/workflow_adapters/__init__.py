from __future__ import annotations

"""
Workflow adapters for Notebook (frontend-v2) KB generate-ppt.
"""

from .wa_paper2ppt import (
    run_paper2page_content_wf_api,
    run_paper2page_content_refine_wf_api,
    run_paper2ppt_wf_api,
    run_paper2ppt_full_pipeline,
)

__all__ = [
    "run_paper2page_content_wf_api",
    "run_paper2page_content_refine_wf_api",
    "run_paper2ppt_wf_api",
    "run_paper2ppt_full_pipeline",
]
