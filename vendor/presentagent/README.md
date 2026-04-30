# PresentAgent

## ThinkFlow Vendored Runtime

This copy is vendored for ThinkFlow editable PPT generation. It includes the stable CLI chain for:

- `general` profile with `direct` or `library`
- `claude` profile with `direct` or `library`
- `qwen` profile with `direct` or `library`

For Qwen, `library` is the default when no coder mode is specified. Internally this uses the Qwen recipe library pipeline. Model weights are not committed. For local Qwen deployment, download `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled` to:

```text
vendor/presentagent/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled/
```

The directory must contain `config.json`, tokenizer files, and model weight files. The built-in server script defaults to `http://127.0.0.1:18081/v1`, matching ThinkFlow's `PRESENT_AGENT_LOCAL_LLM_API_BASE`. You can also set `LOCAL_QWEN35_C500_MODEL_DIR` or point `PRESENT_AGENT_LOCAL_LLM_API_BASE` at an existing OpenAI-compatible local server.

PresentAgent 用于把 PDF 自动转换为结构化演示文稿，当前主链路为 5 个阶段：

```text
Step 1: Parse + Brief
Step 2: Deck IR + Slide IR
Step 3: Material Resolution
Step 4: PPT Code Generation
Step 5: ReAct Refinement（可选）
```

当前项目重点是稳定 `library` 代码生成模式，并兼容远程模型与本地部署模型两种 LLM 后端。

## 环境要求

- Python 3.10+
- LibreOffice
- Poppler
- 项目内虚拟环境建议使用 `.venv`

Linux 安装示例：

```bash
sudo apt-get update
sudo apt-get install -y libreoffice poppler-utils
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 关键命令

基础运行：

```bash
.venv/bin/python cli.py your_document.pdf
```

跳过 ReAct，仅生成初版 PPT：

```bash
.venv/bin/python cli.py your_document.pdf --no-react
```

从已有输出目录恢复：

```bash
.venv/bin/python cli.py your_document.pdf --resume-output-dir outputs/your_output_dir
```

## CLI 关键参数

### `--coder-mode`

- 默认值：`library`
- 可选值：`library`、`direct`
- 当前推荐始终使用 `library`，它会优先走项目内 helper/scaffold，而不是让 LLM 直接自由拼接低层 `python-pptx` 代码。

### `--target-slides`

- 语义：目标页数
- 默认值：`0`
- `0` 表示不指定目标页数，由 Step 1 自由规划
- 指定后会传入 Step 1 的 `slide_briefs` 规划，并影响 Step 2 的单页 IR 生成策略

### `--max-slides`

- 语义：临时截断上限
- 默认值：`0`
- 仅用于本次运行截断页数，不等价于“希望生成多少页”
- 如果同时指定 `--target-slides` 和 `--max-slides`：
  - `--target-slides` 决定规划目标
  - `--max-slides` 只负责最终临时截断

### `--llm-backend`

- 可选值：`remote`、`local`
- 默认值：
  - 若设置了 `PRESENT_AGENT_USE_LOCAL_LLM=1`，默认走 `local`
  - 否则默认走 `remote`

配合本地部署模型使用：

```bash
.venv/bin/python cli.py your_document.pdf \
  --llm-backend local \
  --local-llm-api-base http://127.0.0.1:18000/v1 \
  --local-llm-model Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled
```

## Step 2 页数策略

Step 2 当前支持两种单页 IR 生成方式：

- 单次生成：一次输出完整 slide IR
- 双阶段生成：先生成内容骨架，再生成 `visuals/material_requests`，最后程序合并

自动切换规则：

- 未指定 `--target-slides`：默认走 `auto`，优先按目标页数推断，推断不到时走双阶段
- 指定 `--target-slides <= 9`：走单次生成
- 指定 `--target-slides > 9`：走双阶段生成

这样做的目的：

- 页数少时减少单页往返次数
- 页数多时降低一次性长 JSON 输出导致 `visuals/material_requests` 缺失的风险

## 目录结构

```text
PresentAgent/
├── cli.py
├── src/
│   ├── coder/
│   ├── llm/
│   ├── materials/
│   ├── parser/
│   ├── planner/
│   ├── refiner/
│   └── utils/
├── tests/
├── docs/
└── outputs/
```

## 主要产物

- `outputs/<doc>/markdown/full.md`：解析后的全文 markdown
- `outputs/<doc>/materials/material_manifest.json`：素材清单
- `outputs/<doc>/ir/planned/final_ir.json`：Step 2 规划产物
- `outputs/<doc>/ir/final/final_ir.json`：Step 3 回填后的 IR
- `outputs/<doc>/code/generated/`：Step 4 代码与中间脚本
- `outputs/<doc>/initial.pptx`：初版 PPT
- `outputs/<doc>/refined_final.pptx`：ReAct 优化后的最终 PPT

## 说明

- 真实 smoke 与正式测试以远程环境为准
- `library` 模式只针对 Step 4 和 Step 5 的代码生成，不改变上游 IR 的表达自由
- 当本地部署模型在长 schema 上遵循性不足时，推荐优先通过 `--target-slides` 触发合适的 Step 2 策略，而不是简单继续拉长单次 prompt

## 详细输出目录

```text
outputs/<doc_name>/
├── initial.pptx
├── refined_final.pptx
├── markdown/
│   └── full.md
├── materials/
│   ├── material_manifest.json
│   ├── asset_catalog.json
│   ├── asset_descriptions.json
│   └── asset_request_contexts.json
├── ir/
│   ├── planned/
│   │   ├── slide_briefs.json
│   │   ├── deck_stage.json
│   │   ├── final_ir.json
│   │   └── slides/
│   ├── final/
│   │   └── final_ir.json
│   └── refined/
│       └── final_ir.json
├── code/
│   ├── generated/
│   │   ├── build_deck.py
│   │   └── slides/
│   └── refined/
│       ├── build_deck.py
│       └── slides/
└── refine/
    ├── checkpoints/
    └── round_*/
```

目录含义：

- `markdown/`：PDF 解析后的全文内容
- `materials/`：self 素材、描述结果、请求上下文与最终素材清单
- `ir/planned/`：Step 1 和 Step 2 的中间规划产物
- `ir/final/`：Step 3 完成素材解析和回填后的 IR
- `ir/refined/`：Step 5 优化后的最终 IR
- `code/generated/`：Step 4 的 library/direct 生成代码与组装脚本
- `code/refined/`：Step 5 每轮修正后的最终代码
- `refine/`：ReAct 过程中的分轮产物、评估结果与断点恢复信息
