# ThinkFlow Editable PPT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable `可编辑PPT` output path by vendoring the stable PresentAgent CLI/runtime into ThinkFlow and exposing its editable PPTX plus IR artifacts in the Chinese frontend.

**Architecture:** Add a backend service that prepares ThinkFlow context, invokes the vendored PresentAgent CLI, discovers artifacts, and stores them in outputs-v2. Extend the existing output manifest model with `editable_ppt` and add a frontend workspace that is independent from the old image-based PPT stage rail.

**Tech Stack:** FastAPI, Python subprocess/pathlib/json, pytest, React 18, TypeScript, Vite, lucide-react.

---

### Task 0: Vendor PresentAgent Runtime

**Files:**
- Create: `vendor/presentagent/`
- Modify: `fastapi_app/config/settings.py`
- Modify: `fastapi_app/services/editable_ppt_service.py`
- Test: `tests/test_editable_ppt_service.py`

- [x] Vendor PresentAgent CLI/runtime files needed by Step1-Step5 for `general`/`claude` direct/library and `qwen` direct/library.
- [x] Exclude generated outputs, caches, sample PDFs/PPTX, and model weights; include qwen recipe library/harness source.
- [x] Remove the internal `qwen_lib` CLI entry from the vendored runtime; expose Qwen library through `model_profile=qwen,coder_mode=library`.
- [x] Default `EditablePPTService` to `<project_root>/vendor/presentagent`; keep `PRESENT_AGENT_ROOT` as explicit override.
- [x] Move PresentAgent runtime defaults into `fastapi_app/config/settings.py`.

### Task 1: Backend PresentAgent Wrapper

**Files:**
- Create: `fastapi_app/services/editable_ppt_service.py`
- Test: `tests/test_editable_ppt_service.py`

- [x] Write tests for command construction, Qwen library/direct mode selection, artifact URL payloads, and local Qwen defaults.
- [x] Run `pytest -q tests/test_editable_ppt_service.py` and verify failures are about missing service.
- [x] Implement `EditablePPTService` with `build_context_markdown`, `normalize_request`, `run_presentagent`, and `discover_artifacts`.
- [x] Run `pytest -q tests/test_editable_ppt_service.py` and verify it passes.

### Task 2: OutputV2 Integration

**Files:**
- Modify: `fastapi_app/services/output_v2_service.py`
- Test: `tests/test_output_v2_editable_ppt.py`

- [x] Write tests proving `editable_ppt` is supported, creates a lightweight output record, and dispatches generation to `EditablePPTService`.
- [x] Run `pytest -q tests/test_output_v2_editable_ppt.py` and verify failures are about unsupported output type or missing dispatch.
- [x] Extend `SUPPORTED_TYPES`, `create_outline`, and `generate_output` for `editable_ppt`.
- [x] Run `pytest -q tests/test_output_v2_editable_ppt.py` and verify it passes.

### Task 3: Frontend Type And Entry

**Files:**
- Modify: `frontend_zh/src/components/thinkflow-types.ts`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.tsx`

- [x] Add `editable_ppt` to local and shared output types.
- [x] Add a `可编辑PPT` output button and icon.
- [x] Ensure `resolveOutputCreationInputs` treats `editable_ppt` like `ppt` for source/document requirements.
- [x] Ensure `createOutline` routes `editable_ppt` into the output workspace and can auto-generate.

### Task 4: Frontend Editable PPT Workspace

**Files:**
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.css`

- [x] Add state for editable PPT options: model profile, coder mode, language, complexity, and target slide count.
- [x] Render a separate workspace for `editable_ppt`.
- [x] Render generation controls before result exists.
- [x] Render PPTX download links and IR JSON links after generation.
- [x] Render editable deck/slide IR fields and persist edits in component state.

### Task 5: Verification

**Files:**
- Verify: backend tests
- Verify: frontend build

- [x] Run `pytest -q tests/test_editable_ppt_service.py tests/test_output_v2_editable_ppt.py`.
- [x] Run `npm run build` from `frontend_zh`.
- [x] Check `git status --short` and confirm only intended files were changed, aside from pre-existing unrelated files.

### Task 6: ONLYOFFICE PPTX Editor

**Files:**
- Modify: `fastapi_app/config/settings.py`
- Modify: `fastapi_app/services/output_v2_service.py`
- Modify: `fastapi_app/routers/kb_outputs_v2.py`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.css`
- Test: `tests/test_output_v2_editable_ppt.py`

- [x] Add ONLYOFFICE settings for Document Server URL, ThinkFlow public URL, and optional JWT secret.
- [x] Add backend config endpoint for editable PPTX ONLYOFFICE editor config.
- [x] Add backend callback endpoint that saves ONLYOFFICE-returned PPTX back to output storage.
- [x] Add frontend `在线编辑 PPTX` action and embedded editor panel.
- [x] Keep PPTX download fallback when ONLYOFFICE is not configured.
- [x] Route Document Server browser assets through the Vite `/onlyoffice` proxy and configure `storage.externalHost` so editor cache files stay on the frontend origin.
- [x] Use a real same-origin `/online-editor-frame.html` iframe, per-open `editor_session_id`, and PPTX LibreOffice normalization to avoid stale sessions and ONLYOFFICE PPTX parser failures.
