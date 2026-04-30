# ThinkFlow Editable PPT Design

## Goal

Add a first-version editable PPT output path in ThinkFlow by integrating PresentAgent as a separate output type. The existing image-oriented `ppt` workflow remains unchanged; the new workflow appears as a separate frontend option named `可编辑PPT`.

## Architecture

ThinkFlow vendors the stable PresentAgent CLI/runtime under `vendor/presentagent` and wraps it with a focused backend service. The wrapper prepares ThinkFlow context into a temporary input document, runs the vendored `vendor/presentagent/cli.py`, then records the resulting editable `.pptx` and PresentAgent IR artifacts under the existing notebook output directory. `PRESENT_AGENT_ROOT` remains an explicit override for development, but the default runtime no longer depends on `/mnt/paper2any/dingcheng/PresentAgent`.

The frontend adds `editable_ppt` beside `ppt`. It uses the existing outputs-v2 list/open/generate pattern but renders a separate workspace focused on model/mode selection, deck/slide IR editing, generation status, and PPTX download.

## Backend

- Add `EditablePPTService` in `fastapi_app/services/editable_ppt_service.py`.
- Extend `OutputV2Service` with target type `editable_ppt`.
- Reuse output manifests instead of creating a second persistence system.
- Convert source paths, selected document content, bound documents, and guidance text into `presentagent_input.md`.
- Run PresentAgent CLI with:
  - React enabled by default.
  - ReAct iteration count left at PresentAgent default of 3.
  - `general` profile with `direct` or `library`.
  - `claude` profile with `direct` or `library`.
  - `qwen` profile with `direct` or `library`; omitted mode defaults to `library`.
- Return artifact URLs for `pptx`, planned/final/refined deck IR, slide IR directory, token usage, and run log.

## Model Configuration

Non-Qwen models use API configuration via environment variables or explicit request fields. Qwen uses a local OpenAI-compatible server and does not commit model files. Deployers provide:

- `PRESENT_AGENT_ROOT` only when intentionally overriding the vendored runtime
- `PRESENT_AGENT_PYTHON`
- `PRESENT_AGENT_LOCAL_LLM_API_BASE`
- `PRESENT_AGENT_LOCAL_LLM_MODEL`
- `LOCAL_QWEN35_C500_MODEL_DIR` when running the local server

The repository commits the Qwen server wrapper but not model weights. By default, deployers download `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled` to `vendor/presentagent/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled/`; local testing can also point `LOCAL_QWEN35_C500_MODEL_DIR` at an already downloaded model.

## Frontend

- Add `editable_ppt` to `OutputType`.
- Add a toolbar button labeled `可编辑PPT`.
- Use an output-immersive workspace, not the existing PPT stage rail.
- Show generation controls for model profile, coder mode, language, complexity, and target slide count.
- Show an optional `在线编辑 PPTX` action that embeds ONLYOFFICE when `ONLYOFFICE_DOCUMENT_SERVER_URL` is configured.
- Show editable IR fields after generation:
  - deck title/subtitle/theme basics
  - per-slide title, core message, points, and speaker notes
- Save IR edits into the output manifest result as `editable_ir`.
- Provide direct links to the editable PPTX and JSON IR artifacts.

## First-Version Constraints

- ONLYOFFICE is optional and must be deployed separately as a Document Server.
- Qwen library mode is enabled and remains the default when the user selects Qwen without choosing a generation mode.
- Frontend IR edits are persisted in ThinkFlow metadata; regeneration from edited IR should call the vendored PresentAgent chain.
- PPTX edits made in ONLYOFFICE save back to the PPTX file; v1 does not reverse-sync PPTX edits into IR.
- PresentAgent execution is synchronous in the first version, matching current outputs-v2 generation behavior.

## Testing

- Unit tests cover command construction, Qwen library/direct selection, artifact discovery, and output-v2 `editable_ppt` dispatch.
- Frontend verification uses TypeScript build.
- Full PresentAgent generation is not run in unit tests; command execution is mocked.
