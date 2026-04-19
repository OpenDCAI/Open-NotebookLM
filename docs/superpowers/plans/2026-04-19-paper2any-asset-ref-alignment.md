# Paper2Any Asset Ref Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Open-NotebookLM generate and preserve `asset_ref` in PPT pagecontent the same way as Paper2Any so PPT generation can reliably consume extracted PDF images from MinerU.

**Architecture:** Keep the existing Open-NotebookLM PPT rendering workflow intact and align the upstream pagecontent path to Paper2Any. The change is limited to prompt rules, outline/refine state merging, and a deterministic fallback that backfills missing `asset_ref` from MinerU markdown image references.

**Tech Stack:** Python 3, FastAPI service layer, workflow_engine agents/prompts, pytest

---

### Task 1: Lock Current `asset_ref` Gaps With Failing Tests

**Files:**
- Create: `tests/test_ppt_asset_ref_alignment.py`
- Modify: `tests/test_settings_mineru_env.py` (none expected; read for pattern only)
- Test: `tests/test_ppt_asset_ref_alignment.py`

- [ ] **Step 1: Write the failing test for refine-stage asset preservation**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_engine.workflow.wf_kb_page_content import create_kb_page_content_graph


def test_outline_refine_flow_preserves_asset_ref_from_original_pagecontent():
    graph = create_kb_page_content_graph()
    assert "outline_refine_agent" in graph.nodes

    original = [
        {
            "title": "Method",
            "layout_description": "left text right figure",
            "key_points": ["pipeline"],
            "asset_ref": "images/pipeline.png",
        }
    ]

    # RED target: the refine flow in Open should preserve existing asset_ref
    # but there is no explicit merge helper for this path yet.
    ...
```

- [ ] **Step 2: Write the failing test for MinerU markdown asset backfill**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_engine.workflow.wf_kb_page_content import _backfill_asset_refs_from_mineru_markdown


def test_backfill_asset_refs_from_mineru_markdown_assigns_image_refs_in_order(tmp_path):
    mineru_root = tmp_path / "auto"
    mineru_root.mkdir(parents=True, exist_ok=True)
    (mineru_root / "paper.md").write_text(
        "# paper\n\n"
        "![](images/fig1.png)\n\n"
        "text\n\n"
        "![](images/fig2.png)\n",
        encoding="utf-8",
    )

    pagecontent = [
        {"title": "Intro", "layout_description": "a", "key_points": ["x"], "asset_ref": None},
        {"title": "Method", "layout_description": "b", "key_points": ["y"], "asset_ref": None},
        {"title": "Conclusion", "layout_description": "c", "key_points": ["z"], "asset_ref": None},
    ]

    result = _backfill_asset_refs_from_mineru_markdown(pagecontent, mineru_root)

    assert result[0]["asset_ref"] == "images/fig1.png"
    assert result[1]["asset_ref"] == "images/fig2.png"
    assert result[2]["asset_ref"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/opt/conda/bin/python -m pytest -q tests/test_ppt_asset_ref_alignment.py`
Expected: FAIL because the refine path in `wf_kb_page_content` does not yet provide explicit `asset_ref` preservation behavior, and `wf_kb_page_content` does not yet expose `_backfill_asset_refs_from_mineru_markdown`.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/test_ppt_asset_ref_alignment.py
git commit -m "test: lock ppt asset ref alignment behavior"
```

### Task 2: Preserve `asset_ref` During Outline Refinement

**Files:**
- Modify: `workflow_engine/workflow/wf_kb_page_content.py`
- Test: `tests/test_ppt_asset_ref_alignment.py`

- [ ] **Step 1: Add a merge helper that keeps non-content asset fields from original pagecontent**

```python
def _merge_outline_asset_fields(original_pages, refined_pages):
    preserved_keys = [
        "asset_ref",
        "asset_refs",
        "table_img_path",
        "table_png_path",
        "source_img_path",
        "reference_image_path",
        "img_path",
        "image_path",
        "path",
        "ppt_img_path",
    ]
    merged_pages = []
    for idx, item in enumerate(refined_pages):
        next_item = dict(item) if isinstance(item, dict) else {}
        original_item = original_pages[idx] if idx < len(original_pages) and isinstance(original_pages[idx], dict) else {}
        for key in preserved_keys:
            if not next_item.get(key) and original_item.get(key):
                next_item[key] = original_item.get(key)
        merged_pages.append(next_item)
    return merged_pages
```

- [ ] **Step 2: Use the merge helper inside the `outline_refine_agent` workflow path in `wf_kb_page_content.py`**

```python
        state.pagecontent = _merge_outline_asset_fields(
            original_pages=state.pagecontent or [],
            refined_pages=state.pagecontent or [],
        )
```

- [ ] **Step 3: Run the targeted test**

Run: `/opt/conda/bin/python -m pytest -q tests/test_ppt_asset_ref_alignment.py::test_outline_refine_agent_preserves_asset_ref_from_original_pagecontent`
Expected: PASS

- [ ] **Step 4: Commit the refinement fix**

```bash
git add workflow_engine/workflow/wf_kb_page_content.py tests/test_ppt_asset_ref_alignment.py
git commit -m "fix: preserve ppt asset refs during outline refine"
```

### Task 3: Backfill Missing `asset_ref` From MinerU Markdown Images

**Files:**
- Modify: `workflow_engine/workflow/wf_kb_page_content.py`
- Test: `tests/test_ppt_asset_ref_alignment.py`

- [ ] **Step 1: Add a helper that extracts image refs from MinerU markdown**

```python
import re


def _extract_mineru_image_refs(markdown_text: str) -> list[str]:
    refs = []
    for match in re.finditer(r"!\\[\\]\\((images/[^)]+)\\)", markdown_text or ""):
        ref = str(match.group(1) or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs
```

- [ ] **Step 2: Add a helper that assigns those refs to pages lacking assets**

```python
def _backfill_asset_refs_from_mineru_markdown(pagecontent: list[dict], mineru_root: Path) -> list[dict]:
    if not pagecontent or not mineru_root.exists():
        return pagecontent

    md_files = sorted(mineru_root.glob("*.md"))
    if not md_files:
        return pagecontent

    markdown_text = md_files[0].read_text(encoding="utf-8", errors="replace")
    image_refs = _extract_mineru_image_refs(markdown_text)
    if not image_refs:
        return pagecontent

    result = []
    image_index = 0
    for item in pagecontent:
        next_item = dict(item)
        if not next_item.get("asset_ref") and image_index < len(image_refs):
            next_item["asset_ref"] = image_refs[image_index]
            image_index += 1
        result.append(next_item)
    return result
```

- [ ] **Step 3: Apply the backfill after outline generation and after refine in KB pagecontent workflow**

```python
        if state.pagecontent and getattr(state, "mineru_root", ""):
            state.pagecontent = _backfill_asset_refs_from_mineru_markdown(
                state.pagecontent,
                Path(state.mineru_root),
            )
```

- [ ] **Step 4: Run the targeted tests**

Run: `/opt/conda/bin/python -m pytest -q tests/test_ppt_asset_ref_alignment.py::test_backfill_asset_refs_from_mineru_markdown_assigns_image_refs_in_order tests/test_ppt_asset_ref_alignment.py::test_outline_refine_agent_preserves_asset_ref_from_original_pagecontent`
Expected: PASS

- [ ] **Step 5: Commit the backfill logic**

```bash
git add workflow_engine/workflow/wf_kb_page_content.py tests/test_ppt_asset_ref_alignment.py
git commit -m "fix: backfill ppt asset refs from mineru markdown"
```

### Task 4: Align Prompt Rules With Paper2Any `asset_ref` Semantics

**Files:**
- Modify: `workflow_engine/promptstemplates/resources/pt_kb_ppt_repo.py`
- Test: `tests/test_ppt_asset_ref_alignment.py`

- [ ] **Step 1: Add a prompt regression test that checks stricter `asset_ref` instructions are present**

```python
from workflow_engine.promptstemplates.resources.pt_kb_ppt_repo import KBPPTPrompts


def test_kb_ppt_prompt_requires_explicit_asset_ref_examples():
    prompt = KBPPTPrompts.task_prompt_for_kb_outline_agent
    assert "images/architecture.png" in prompt
    assert "Table_2" in prompt
    assert "并且只能1 个 asset" in prompt
```

- [ ] **Step 2: Update `task_prompt_for_kb_outline_agent` to mirror Paper2Any’s `asset_ref` guidance**

```python
8) 每页必须包含字段：title, layout_description, key_points(list), asset_ref。
...
13) `asset_ref`: 如果该页需要展示来源中的原图或表格，请填写其文件或表格标识（例如 "Table_2", "images/architecture.png"），并且只能 1 个 asset；如果不需要引用原图，请填 null。
```

- [ ] **Step 3: Update the image insert prompt to keep `asset_ref` semantics consistent**

```python
2) 每个图片页必须包含字段：title, layout_description, key_points(list), asset_ref。
3) asset_ref 必须直接指向该图片素材路径，例如 "images/xxx.png"。
```

- [ ] **Step 4: Run the prompt regression test**

Run: `/opt/conda/bin/python -m pytest -q tests/test_ppt_asset_ref_alignment.py::test_kb_ppt_prompt_requires_explicit_asset_ref_examples`
Expected: PASS

- [ ] **Step 5: Commit the prompt alignment**

```bash
git add workflow_engine/promptstemplates/resources/pt_kb_ppt_repo.py tests/test_ppt_asset_ref_alignment.py
git commit -m "feat: align kb ppt prompts with paper2any asset refs"
```

### Task 5: Verify End-to-End Asset Consumption In PPT Generation

**Files:**
- Modify: `tests/test_ppt_asset_context.py`
- Test: `tests/test_ppt_asset_context.py`

- [ ] **Step 1: Add an end-to-end test that `run_paper2ppt_wf_api` loads MinerU markdown with image refs and preserved pagecontent asset_ref**

```python
def test_run_paper2ppt_wf_api_keeps_asset_ref_bound_to_mineru_images(...):
    ...
    assert final_state.pagecontent[0]["asset_ref"] == "images/fig1.png"
    assert "images/fig1.png" in final_state.mineru_output
```

- [ ] **Step 2: Run the focused verification suite**

Run: `/opt/conda/bin/python -m pytest -q tests/test_ppt_asset_ref_alignment.py tests/test_ppt_asset_context.py tests/test_mineru_http_alignment.py`
Expected: PASS

- [ ] **Step 3: Run one live re-embed and verify output tree**

Run:

```bash
curl -s -X POST http://127.0.0.1:18213/api/v1/kb/reembed-source \
  -H 'X-API-Key: df-internal-2024-workflow-key' \
  -H 'Content-Type: application/json' \
  -d '{"file_path":"/outputs/local/hello_local_1776511167192_14ab2e9d/sources/test_figure/original/test_figure.pdf","email":"local","user_id":"local","notebook_id":"local_1776511167192_14ab2e9d","notebook_title":"hello"}'
```

Expected: `{"success":true,"filename":"test_figure.pdf"}`

Then verify:

```bash
rg -n "!\\[\\]|images/" /root/user/ldh/Open-NotebookLM/outputs/local/hello_local_1776511167192_14ab2e9d/sources/test_figure/mineru/test_figure/auto/test_figure.md
```

Expected: at least one `![](images/...)` hit

- [ ] **Step 4: Commit final verification adjustments**

```bash
git add tests/test_ppt_asset_context.py tests/test_ppt_asset_ref_alignment.py
git commit -m "test: verify ppt asset refs flow from mineru to generation"
```
