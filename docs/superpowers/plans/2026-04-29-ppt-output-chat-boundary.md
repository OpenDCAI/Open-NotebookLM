# PPT Output Chat Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PPT outline chat an output-bound adjustment chat that never writes to or reads from the normal notebook conversation history, and add an explicit discard action for pending outline drafts.

**Architecture:** Keep the existing `OutputV2Service` output manifest model. Store PPT chat messages under `output.outline_chat_sessions`, ignore ordinary notebook `conversation_history` for `/outline-chat`, and add a `/outline-chat/discard` endpoint that resets the active session draft to the confirmed outline.

**Tech Stack:** FastAPI, local JSON output manifests, React/TypeScript, Vitest/build, pytest.

---

### Task 1: Backend History Boundary

**Files:**
- Modify: `fastapi_app/services/output_v2_service.py`
- Test: `fastapi_app/tests/test_output_v2_ppt_outline_chat.py`

- [x] **Step 1: Write failing test**

Create `fastapi_app/tests/test_output_v2_ppt_outline_chat.py` with a test that monkeypatches `_apply_outline_chat` and asserts `conversation_history` is not forwarded when `outline_chat()` is called with ordinary notebook messages.

- [x] **Step 2: Run failing test**

Run: `/opt/conda/bin/python -m pytest fastapi_app/tests/test_output_v2_ppt_outline_chat.py -q`

Expected: fails because `conversation_history` is currently forwarded.

- [x] **Step 3: Implement minimal backend fix**

In `OutputV2Service.outline_chat()`, pass `conversation_history=None` to `_apply_outline_chat`.

- [x] **Step 4: Run test**

Run the same pytest command and confirm it passes.

### Task 2: Discard Pending Draft

**Files:**
- Modify: `fastapi_app/services/output_v2_service.py`
- Modify: `fastapi_app/routers/kb_outputs_v2.py`
- Test: `fastapi_app/tests/test_output_v2_ppt_outline_chat.py`

- [x] **Step 1: Write failing test**

Add a test that creates a PPT output manifest with a pending draft and calls `discard_outline_chat()`. Assert:
- `outline` is unchanged.
- `outline_chat_has_pending_changes` becomes false.
- active session `draft_outline` equals confirmed outline.
- a system message records that the candidate draft was discarded.

- [x] **Step 2: Run failing test**

Run: `/opt/conda/bin/python -m pytest fastapi_app/tests/test_output_v2_ppt_outline_chat.py -q`

Expected: fails because `discard_outline_chat()` does not exist.

- [x] **Step 3: Implement service and route**

Add `OutputV2Service.discard_outline_chat()` and `POST /api/v1/kb/outputs/{output_id}/outline-chat/discard`.

- [x] **Step 4: Run test**

Run the same pytest command and confirm it passes.

### Task 3: Frontend Payload and UI

**Files:**
- Modify: `frontend/src/components/usePptOutlineManager.ts`
- Modify: `frontend/src/components/PptOutlinePanel.tsx`
- Modify: `frontend/src/components/ThinkFlowWorkspace.tsx`

- [x] **Step 1: Remove ordinary chat history from PPT outline requests**

In `handlePptOutlineChatMessage()`, remove `conversation_history: buildConversationHistoryPayload(chatMessages)` from the request body.

- [x] **Step 2: Add discard callback**

Add `discardPptOutlineDraft()` in `usePptOutlineManager.ts`, calling `/outline-chat/discard`, then update `outputs` with the returned output.

- [x] **Step 3: Add right-panel discard button**

In `PptOutlinePanel`, add `onDiscardPptOutlineDraft` prop and show `放弃候选` when `activePptDraftPending` is true.

- [x] **Step 4: Wire prop in workspace**

Pass `discardPptOutlineDraft` from `ThinkFlowWorkspace` to `PptOutlinePanel`.

### Task 4: Verification

**Files:**
- No new files.

- [x] **Step 1: Run backend focused tests**

Run:

```bash
/opt/conda/bin/python -m pytest fastapi_app/tests/test_output_v2_ppt_outline_chat.py fastapi_app/tests/test_kb_chat_request.py -q
```

- [x] **Step 2: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

- [x] **Step 3: Confirm git status**

Run:

```bash
git status --short
```
