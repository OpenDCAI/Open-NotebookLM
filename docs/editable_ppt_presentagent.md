# Editable PPT PresentAgent Options

ThinkFlow exposes a small PresentAgent option surface for editable PPT generation.

For optional online PPTX editing through ONLYOFFICE, see `docs/onlyoffice-editable-ppt.md`.

## User-Facing Options

- `model_profile`: `general`, `claude`, or `qwen`.
- `coder_mode`: `library` or `direct`. If omitted, ThinkFlow defaults to `library`.
- `language`: `chinese` or `english`.
- `complexity`: `simple`, `balanced`, or `complex`.
- `target_slides`: positive integer page target.

## Qwen Behavior

- `model_profile=qwen` uses the local LLM backend.
- `model_profile=qwen` with omitted `coder_mode` defaults to `library`.
- `model_profile=qwen,coder_mode=library` is mapped inside the vendored PresentAgent CLI to the Qwen recipe library pipeline: `QwenRecipeCoder`, `QwenRecipeRenderer`, harness, audit, and `QwenRecipeRefiner`.
- `model_profile=qwen,coder_mode=direct` remains available and uses the direct generation path with the local Qwen backend.

## Local Qwen Model Files

Model weights are not committed. For the built-in local Qwen server, download:

`Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled`

to:

`vendor/presentagent/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled/`

The directory must contain `config.json`, tokenizer files, and model weight files. Then start the local server from `vendor/presentagent`:

```bash
./run_local_qwen35_c500_server.sh
```

The script defaults to `http://127.0.0.1:18081/v1`, matching ThinkFlow's default `PRESENT_AGENT_LOCAL_LLM_API_BASE`. To use another local model directory, set `LOCAL_QWEN35_C500_MODEL_DIR`. To use an already running OpenAI-compatible Qwen service, set `PRESENT_AGENT_LOCAL_LLM_API_BASE` and `PRESENT_AGENT_LOCAL_LLM_MODEL`.

## Option Boundary

Qwen mode selection is represented only by the public pair `model_profile=qwen` and `coder_mode=library|direct`.
