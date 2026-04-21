# ThinkFlow Flashcard Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement flashcard generation controls, structured citations, persisted generation settings, and synced CN/EN flashcard UX.

**Architecture:** Extend the backend flashcard schema and persistence first so both direct API generation and outputs-v2 generation emit the same `generation_config` and card-level `citations`. Then update the Chinese workspace flow and English flashcard modal to consume the same structure and reuse existing source preview logic.

**Tech Stack:** FastAPI, Pydantic, React, TypeScript, CSS, Framer Motion

---

### Task 1: Backend flashcard schema and generation metadata

**Files:**
- Modify: `fastapi_app/schemas.py`
- Modify: `fastapi_app/services/flashcard_service.py`
- Modify: `fastapi_app/routers/kb.py`

- [x] **Step 1: Extend flashcard models with citation and generation config fields**

- [x] **Step 2: Update LLM prompt and response parser to preserve `[1][2]` answers plus structured `citations`**

- [x] **Step 3: Persist `generation_config` in `flashcards.json` and API response payload**

### Task 2: outputs-v2 flashcard config threading

**Files:**
- Modify: `fastapi_app/routers/kb_outputs_v2.py`
- Modify: `fastapi_app/services/output_v2_service.py`

- [x] **Step 1: Let outputs-v2 outline requests accept `flashcard_config`**

- [x] **Step 2: Save `flashcard_config` in output items and forward it into flashcard generation**

- [x] **Step 3: Preserve legacy flashcard `generation_config` when scanning old outputs**

### Task 3: Chinese flashcard study UX

**Files:**
- Modify: `frontend_zh/src/components/ThinkFlowFlashcardStudy.tsx`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- Modify: `frontend_zh/src/components/ThinkFlowWorkspace.css`
- Modify: `frontend_zh/src/components/thinkflow-types.ts`

- [x] **Step 1: Parse flashcard citations and generation config from output results**

- [x] **Step 2: Add generation controls to the flashcard direct-output confirmation flow**

- [x] **Step 3: Render interactive citations, citation preview panel, open-full-source action, and upgraded card visuals**

### Task 4: English flashcard sync

**Files:**
- Modify: `frontend_en/src/pages/NotebookView.tsx`
- Modify: `frontend_en/src/components/flashcards/FlashcardViewer.tsx`

- [x] **Step 1: Extend flashcard settings panel with difficulty, card count, topic, and test focus**

- [x] **Step 2: Forward new settings to `/generate-flashcards` and load persisted `generation_config`**

- [x] **Step 3: Render interactive citations and generation settings in the English flashcard viewer**

### Task 5: Verification

**Files:**
- Verify: `fastapi_app/schemas.py`
- Verify: `fastapi_app/services/flashcard_service.py`
- Verify: `fastapi_app/routers/kb.py`
- Verify: `fastapi_app/routers/kb_outputs_v2.py`
- Verify: `fastapi_app/services/output_v2_service.py`
- Verify: `frontend_zh/src/components/ThinkFlowFlashcardStudy.tsx`
- Verify: `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- Verify: `frontend_en/src/pages/NotebookView.tsx`
- Verify: `frontend_en/src/components/flashcards/FlashcardViewer.tsx`

- [ ] **Step 1: Run focused Python compile checks**

- [ ] **Step 2: Run frontend TypeScript/build checks where available**

- [ ] **Step 3: Review diff for CN/EN parity and remaining compatibility risks**
