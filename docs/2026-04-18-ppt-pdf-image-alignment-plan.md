# PPT PDF Image Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align ThinkFlow's PPT generation path with Paper2Any so PDF-parsed source images remain available during PPT generation and can be inserted or fused into slides.

**Architecture:** Persist the real PPT outline generation context produced by `kb_page_content`, especially `mineru_root` and image-bearing pagecontent, into `ppt_pipeline/context.json`. Then teach the PPT generation adapter to restore that context before running the paper2ppt workflow, preferring the persisted asset paths over the synthetic `result_path/input/auto` guess.

**Tech Stack:** FastAPI service layer, workflow adapter glue code, pytest

---

### Task 1: Add failing tests for persisted PPT asset context

**Files:**
- Create: `tests/test_ppt_asset_context.py`
- Modify: `fastapi_app/services/output_v2_service.py`
- Modify: `fastapi_app/services/wa_paper2ppt.py`
- Test: `tests/test_ppt_asset_context.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from fastapi_app.services.output_v2_service import OutputV2Service
from fastapi_app.services.wa_paper2ppt import _load_persisted_ppt_context


def test_build_ppt_context_payload_keeps_mineru_root_and_asset_fields(tmp_path: Path):
    service = OutputV2Service()
    outline = [{"id": "slide_1", "title": "T", "bullets": ["a"]}]
    raw_pagecontent = [{
        "id": "slide_1",
        "title": "T",
        "bullets": ["a"],
        "asset_ref": "images/figure_1.png",
        "image_path": "/tmp/source/figure_1.png",
    }]

    payload = service._build_ppt_context_payload(
        outline=outline,
        raw_pagecontent=raw_pagecontent,
        mineru_root="/tmp/mineru/auto",
        query="q",
        source_paths=["/tmp/a.pdf"],
        source_names=["a.pdf"],
        page_count=1,
        enable_images=True,
    )

    assert payload["mineru_root"] == "/tmp/mineru/auto"
    assert payload["raw_pagecontent"][0]["asset_ref"] == "images/figure_1.png"
    assert payload["raw_pagecontent"][0]["image_path"] == "/tmp/source/figure_1.png"


def test_load_persisted_ppt_context_restores_mineru_root_and_missing_asset_fields(tmp_path: Path):
    pipeline_dir = tmp_path / "ppt_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "context.json").write_text(
        """
        {
          "mineru_root": "/tmp/mineru/auto",
          "raw_pagecontent": [
            {
              "id": "slide_1",
              "title": "T",
              "asset_ref": "images/figure_1.png",
              "image_path": "/tmp/source/figure_1.png"
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    pagecontent = [{"id": "slide_1", "title": "T", "bullets": ["a"]}]
    mineru_root, merged_pagecontent = _load_persisted_ppt_context(pipeline_dir, pagecontent)

    assert mineru_root == "/tmp/mineru/auto"
    assert merged_pagecontent[0]["asset_ref"] == "images/figure_1.png"
    assert merged_pagecontent[0]["image_path"] == "/tmp/source/figure_1.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: FAIL because `_build_ppt_context_payload` and `_load_persisted_ppt_context` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# output_v2_service.py
def _build_ppt_context_payload(...):
    return {
        "source_paths": source_paths,
        "source_names": source_names,
        "query": query,
        "page_count": page_count,
        "enable_images": enable_images,
        "mineru_root": mineru_root,
        "raw_pagecontent": raw_pagecontent,
    }

# wa_paper2ppt.py
def _load_persisted_ppt_context(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_ppt_asset_context.py fastapi_app/services/output_v2_service.py fastapi_app/services/wa_paper2ppt.py
git commit -m "fix: preserve pdf image context for ppt generation"
```

### Task 2: Persist real outline-generation context into `context.json`

**Files:**
- Modify: `fastapi_app/services/output_v2_service.py`
- Test: `tests/test_ppt_asset_context.py`

- [ ] **Step 1: Extend the failing test with a file-writing assertion**

```python
def test_build_ppt_context_payload_keeps_mineru_root_and_asset_fields(...):
    ...
```

- [ ] **Step 2: Run test to verify it fails for the new assertion**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: FAIL on missing persisted context content.

- [ ] **Step 3: Save the richer context payload during outline creation**

```python
self._write_json(
    pipeline_dir / "context.json",
    self._build_ppt_context_payload(
        outline=outline,
        raw_pagecontent=getattr(state_pc, "pagecontent", []) or [],
        mineru_root=str(getattr(state_pc, "mineru_root", "") or ""),
        ...
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/output_v2_service.py tests/test_ppt_asset_context.py
git commit -m "fix: persist mineru asset context for ppt outlines"
```

### Task 3: Restore persisted context before PPT generation

**Files:**
- Modify: `fastapi_app/services/wa_paper2ppt.py`
- Test: `tests/test_ppt_asset_context.py`

- [ ] **Step 1: Extend the failing test to require asset-field merge**

```python
def test_load_persisted_ppt_context_restores_mineru_root_and_missing_asset_fields(...):
    ...
```

- [ ] **Step 2: Run test to verify it fails for missing merge logic**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: FAIL because merged pagecontent still lacks `asset_ref` / `image_path`.

- [ ] **Step 3: Restore mineru_root and merge missing per-slide asset fields**

```python
persisted_mineru_root, pagecontent = _load_persisted_ppt_context(base_dir, state.pagecontent or [])
if persisted_mineru_root:
    state.mineru_root = persisted_mineru_root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/wa_paper2ppt.py tests/test_ppt_asset_context.py
git commit -m "fix: restore persisted pdf image assets for ppt generation"
```

### Task 4: Verify the targeted behavior

**Files:**
- Modify: `fastapi_app/services/output_v2_service.py`
- Modify: `fastapi_app/services/wa_paper2ppt.py`
- Test: `tests/test_ppt_asset_context.py`

- [ ] **Step 1: Run the focused regression test**

Run: `pytest -q tests/test_ppt_asset_context.py`
Expected: PASS

- [ ] **Step 2: Run existing nearby regression test**

Run: `pytest -q tests/test_req_img.py`
Expected: PASS

- [ ] **Step 3: Byte-compile touched service files**

Run: `python -m py_compile fastapi_app/services/output_v2_service.py fastapi_app/services/wa_paper2ppt.py`
Expected: no output

- [ ] **Step 4: Record any runtime-only residual risk**

```text
Manual verification still needed with a real PDF source to confirm the downstream agent chooses image edit/fusion for at least one slide.
```

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/output_v2_service.py fastapi_app/services/wa_paper2ppt.py tests/test_ppt_asset_context.py docs/2026-04-18-ppt-pdf-image-alignment-plan.md
git commit -m "docs: add plan for ppt pdf image alignment"
```
