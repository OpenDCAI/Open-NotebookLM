# ThinkFlow 开发前置说明

本文件用于 ThinkFlow 分支的日常开发初始化。每次开始开发前，先按本文检查环境、文档和分支状态。

## 1. 仓库与分支

- 本地仓库路径：`/mnt/paper2any/dingcheng/thinkflow`
- 上游分支：`thinkflow`
- 本地开发分支：`dingcheng-dev`

建议每次开始开发先执行：

```bash
cd /mnt/paper2any/dingcheng/thinkflow
git branch --show-current
```

如果不在 `dingcheng-dev`，先切换：

```bash
git checkout dingcheng-dev
```

## 2. 开发前先读文档

仓库中的 `docs/` 目录包含当前开发规范、架构说明和 ThinkFlow workflow 文档。开始任何开发前，至少先阅读：

- `docs/CLAUDE.md`
- `docs/development-architecture-guide.md`
- `docs/thinkflow-workflow-source-document-summary-guidance.md`
- `docs/thinkflow-summary-document-guidance-output-prompts.md`
- `docs/thinkflow-upload-file-processing-flow.md`

如果后续功能开发新增了文档，开工前继续补读新增文档，避免脱离当前 workflow 约定。

## 3. 环境约定

- muxi 开发机的 `base` 环境可以直接运行项目。
- 如需隔离环境，可以复制一个新的 conda 环境后再开发。
- 如果需要 muxi 开发机权限或已有环境信息，直接向你确认。

ENV 文件位置：

- 本地保留文件：`/mnt/paper2any/dingcheng/thinkflow/env`

为了方便配置环境，可优先参考或复用该文件中的后端配置。

## 4. 启动方式

推荐启动脚本：

```bash
cd /mnt/paper2any/dingcheng/thinkflow
./scripts/bash.sh
```

如果在 muxi 机器上启动，需要手动确认端口，不要覆盖在线服务端口：

- 前端端口：`3001`
- 后端端口：`8213`

## 5. 开发边界约束

### 5.1 新增 API / 新增模型能力

如果开发过程中需要新增 API、模型服务或外部能力，必须遵守下面的边界：

- 先在 env 配置中补充变量。
- 再在 `fastapi_app/providers/` 中增加对应 provider 调用逻辑。
- 不要在 workflow 中直接读取零散 env 变量。
- 不要在 workflow 中堆很重的外部调用逻辑。

建议遵循的落点顺序：

1. `env` / 配置定义
2. `fastapi_app/config/settings.py`
3. `fastapi_app/providers/`
4. `fastapi_app/services/`
5. `fastapi_app/routers/` 或 `workflow_engine/`

当前可编辑 PPT 使用仓库内 `vendor/presentagent` 作为默认 PresentAgent 运行时。开发调试外部 PresentAgent 分支时，才设置 `PRESENT_AGENT_ROOT` 覆盖默认路径。Qwen direct/library 都依赖本地 OpenAI-compatible 服务，默认配置在 `fastapi_app/config/settings.py`：

- `PRESENT_AGENT_PYTHON`
- `PRESENT_AGENT_LOCAL_LLM_API_BASE`
- `PRESENT_AGENT_LOCAL_LLM_MODEL`
- `THINKFLOW_EDITABLE_PPT_TIMEOUT_SECONDS`

不要提交 Qwen 模型权重。内置本地 Qwen server 的默认模型目录是：

```text
vendor/presentagent/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled/
```

部署时把 `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled` 下载到上面的目录，确保目录内包含 `config.json`、tokenizer 文件和模型权重文件，然后从 `vendor/presentagent` 启动：

```bash
./run_local_qwen35_c500_server.sh
```

脚本默认监听 `http://127.0.0.1:18081/v1`，与 `PRESENT_AGENT_LOCAL_LLM_API_BASE` 默认值一致。若模型放在别处，设置 `LOCAL_QWEN35_C500_MODEL_DIR`；若已有 OpenAI-compatible Qwen 服务，直接设置 `PRESENT_AGENT_LOCAL_LLM_API_BASE` 和 `PRESENT_AGENT_LOCAL_LLM_MODEL`。

可编辑 PPT 的最终手工精修使用可选 ONLYOFFICE Document Server。未配置时前端保留 PPTX 下载；配置后会在可编辑 PPT 工作区显示“在线编辑 PPTX”。相关配置：

完整部署说明见 `docs/onlyoffice-editable-ppt.md`。

- `ONLYOFFICE_DOCUMENT_SERVER_URL`：浏览器侧 ONLYOFFICE 入口。本地 Vite 开发推荐使用 `/onlyoffice` 代理，避免浏览器直接访问 Document Server 的 8082 端口。
- `ONLYOFFICE_THINKFLOW_PUBLIC_URL`：ONLYOFFICE 容器可访问的 ThinkFlow 后端公网/内网地址，例如 `https://thinkflow.nas.cpolar.cn`
- `ONLYOFFICE_JWT_SECRET`：如果 Document Server 开启 JWT，则填同一个 secret

ONLYOFFICE 需要能访问 ThinkFlow 的 `/outputs/...` 文件 URL 和 `/api/v1/kb/outputs/{output_id}/onlyoffice/callback` 保存回调。

本地 Docker 部署时，如果 `ONLYOFFICE_THINKFLOW_PUBLIC_URL` 指向宿主机内网地址，需要允许 Document Server 访问私有 IP：

```bash
docker run -d --name thinkflow-onlyoffice \
  -p 8082:80 \
  --add-host=host.docker.internal:host-gateway \
  -e JWT_ENABLED=false \
  -e ALLOW_PRIVATE_IP_ADDRESS=true \
  onlyoffice/documentserver:latest
```

如果前端通过 Vite `/onlyoffice` 代理加载 Document Server，还需要让 ONLYOFFICE 生成的缓存文件 URL 也走同一个 3003 origin，否则浏览器可能访问 `localhost:8082/cache/.../Editor.bin` 失败并显示“错误码 -4：下载失败”。容器启动后执行：

```bash
docker cp thinkflow-onlyoffice:/etc/onlyoffice/documentserver/local.json /tmp/thinkflow-onlyoffice-local.json
python - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/thinkflow-onlyoffice-local.json")
data = json.loads(path.read_text())
storage = data.setdefault("storage", {})
storage["externalHost"] = "http://localhost:3003/onlyoffice"
storage["useDirectStorageUrls"] = False
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
PY
docker cp /tmp/thinkflow-onlyoffice-local.json thinkflow-onlyoffice:/etc/onlyoffice/documentserver/local.json
docker exec thinkflow-onlyoffice supervisorctl restart ds:docservice ds:converter
```

生产部署建议开启 JWT，并将 `ONLYOFFICE_JWT_SECRET` 配成与 Document Server 相同的 secret；本地开发为了避免随机 secret 与后端配置不一致，默认关闭 JWT。

### 5.2 ThinkFlow 整体开发逻辑

整体开发逻辑遵循：

`来源引入 -> 基于 RAG 的 chat -> 产出消费`

当前 ThinkFlow 的主联通对象是：

- 梳理文档
- 产出指导

开发时优先保证这条链路的清晰性，不要把来源、聊天、产出强耦合在一个模块里。

### 5.3 工作流理解

根据当前仓库文档，ThinkFlow 的正式上下文结构可概括为：

- 来源：事实主源
- 梳理文档：核心中间产物
- 产出指导：高权重产出约束
- 摘要：偏阅读笔记，不是当前正式产出主输入

因此开发新功能时，优先考虑：

- 来源如何进入系统
- 是否需要先沉淀成梳理文档
- 是否需要产出指导参与最终生成

## 6. 当前本地 SSH 约定

当前目录专用 SSH 文件：

- 私钥：`/mnt/paper2any/dingcheng/thinkflow_dingcheng_ed25519`
- 公钥：`/mnt/paper2any/dingcheng/thinkflow_dingcheng_ed25519.pub`
- SSH 配置：`/mnt/paper2any/dingcheng/thinkflow_ssh_config`

后续如果需要显式使用当前目录专用密钥拉取或推送，使用：

```bash
GIT_SSH_COMMAND='ssh -F /mnt/paper2any/dingcheng/thinkflow_ssh_config' git <command>
```

不要依赖全局 `~/.ssh/config` 或机器上的其他 ssh-agent 身份。

## 7. 每次开发前的最小检查清单

- 当前目录在 `/mnt/paper2any/dingcheng/thinkflow`
- 当前分支是 `dingcheng-dev`
- 已阅读 `docs/` 中相关开发规范
- 已确认本次开发涉及的 workflow 文档
- 已确认 ENV 是否齐全
- 已确认端口不会覆盖在线服务
- 若涉及新增外部能力，已规划 `env -> provider -> service -> router/workflow` 的接入路径
