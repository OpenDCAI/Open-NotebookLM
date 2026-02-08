<div align="center">

<img src="static/readme/logo.jpg" alt="OpenNotebook Logo" width="200"/>

# OpenNotebookLM

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-2F80ED?style=flat-square&logo=apache&logoColor=white)](LICENSE)

中文 | [English](README_EN.md)

✨ **NotebookLM 风格的知识库工作流平台：上传文档、智能问答、一键生成 PPT / 思维导图 / 播客 / DrawIO 图表** ✨

| 📚 **知识库管理** &nbsp;|&nbsp; 💬 **智能问答** &nbsp;|&nbsp; 🎨 **多模态生成** &nbsp;|&nbsp; 🔍 **语义检索** |

<br>

<a href="#-quick-start" target="_self">
  <img alt="Quickstart" src="https://img.shields.io/badge/🚀-Quick_Start-2F80ED?style=for-the-badge" />
</a>
<a href="docs/" target="_blank">
  <img alt="Docs" src="https://img.shields.io/badge/📚-Docs-2D9CDB?style=for-the-badge" />
</a>
<a href="docs/contributing.md" target="_blank">
  <img alt="Contributing" src="https://img.shields.io/badge/🤝-Contributing-27AE60?style=for-the-badge" />
</a>

<br>
<br>

<img src="static/readme/首页预览.png" alt="OpenNotebook 首页" width="80%"/>

</div>

---

## 📑 目录

- [✨ 核心功能](#-核心功能)
- [📸 展示](#-展示)
- [🚀 快速开始](#-快速开始)
- [📂 项目结构](#-项目结构)
- [🤝 参与贡献](#-参与贡献)

---

## ✨ 核心功能

> 以「笔记本 + 知识库」为核心，基于 DataFlow-Agent 工作流引擎，从上传的文档/论文出发，支持智能问答与多种一键生成能力。

- **📚 知识库管理**：文件上传、列表查看、多选源文档，支持 PDF 等格式。
- **💬 智能问答**：基于选中文档的上下文进行问答，对话历史本地持久化。
- **🎨 PPT 生成**：从知识库内容或论文生成可编辑演示文稿（对接 Paper2PPT 工作流）。
- **🧠 思维导图**：基于选中文档生成 Mermaid 思维导图，支持预览与导出。
- **🎙️ 知识播客**：将知识库内容转为播客脚本与讲解素材。
- **🎬 视频讲解**：生成视频脚本与讲解内容。
- **🧩 Paper2Drawio**：从论文/文本或图片生成可编辑 DrawIO 图表，支持内嵌编辑与导出。
- **🔍 语义检索**：基于嵌入的语义检索，支持 Top-K 与多模型选择。

---

## 📸 展示

### 首页

<div align="center">

<img src="static/readme/首页预览.png" alt="首页预览" width="90%"/>

</div>

### 二级界面（知识库与问答）

<div align="center">

<img src="static/readme/二级界面预览.png" alt="二级界面预览" width="90%"/>

</div>

### PPT 生成

<div align="center">

<img src="static/readme/ppt.png" alt="PPT 生成" width="90%"/>

</div>

### 思维导图

<div align="center">

<img src="static/readme/思维导图.png" alt="思维导图" width="90%"/>

</div>

### DrawIO 图表

<div align="center">

<img src="static/readme/drawio.png" alt="DrawIO 图表" width="90%"/>

</div>

---

## 🚀 快速开始

### 环境要求

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-18+-339933?style=flat-square&logo=node.js&logoColor=white)

- **Python**: 3.10+
- **Node.js**: 18+（前端构建）
- **操作系统**: Linux（推荐）/ Windows / macOS

### 后端安装与启动

```bash
# 1. 克隆仓库
git clone <your-repo-url>
cd opennoteboolLM

# 2. 创建并激活虚拟环境（推荐 Conda）
conda create -n opennotebook python=3.11 -y
conda activate opennotebook

# 3. 安装依赖
pip install -r requirements-base.txt
pip install -e .

# 4. 配置环境变量（可选）
cp fastapi_app/.env.example fastapi_app/.env
# 编辑 fastapi_app/.env，配置 DF_API_KEY、DF_API_URL、Supabase 等

# 5. 启动后端
cd fastapi_app
uvicorn main:app --host 0.0.0.0 --port 8000
```

后端健康检查：<http://localhost:8000/health>，API 文档：<http://localhost:8000/docs>。

### 前端安装与启动

提供中英双前端，任选其一即可。

**英文前端（frontend_en，NotebookLM 风格）**

```bash
cd frontend_en
npm install
cp .env.example .env   # 可选，配置 VITE_API_KEY、VITE_DEFAULT_LLM_API_URL、Supabase 等
npm run dev
```

**中文前端（frontend_zh）**

```bash
cd frontend_zh
npm install
npm run dev
```

访问 **http://localhost:3000**（或终端提示的端口，如 3001）。

### 环境变量说明

- **后端 `fastapi_app/.env`**  
  - `DF_API_KEY`、`DF_API_URL`：LLM 调用。  
  - `SUPABASE_URL`、`SUPABASE_ANON_KEY` 等：可选，用于用户认证与云存储。
- **前端 `frontend_en/.env`**  
  - `VITE_API_KEY`：请求后端 API 的密钥（需与后端一致）。  
  - `VITE_DEFAULT_LLM_API_URL`：默认 LLM 提供商地址。  
  - `VITE_SUPABASE_*`：可选，与后端 Supabase 配置对应。

不配置 Supabase 时，前端可使用本地模拟用户进行开发与体验。

---

## 📂 项目结构

```
opennoteboolLM/
├── dataflow_agent/          # 工作流引擎
│   ├── agentroles/          # Agent 角色定义
│   ├── workflow/            # 工作流（Paper2PPT、PDF2PPT、Image2Drawio、KB 等）
│   ├── promptstemplates/    # 提示模板
│   └── toolkits/            # 工具集
├── fastapi_app/             # 后端 API
│   ├── routers/             # 知识库、文件、Paper2Drawio、Paper2PPT 等
│   └── workflow_adapters/   # 工作流适配
├── frontend_en/             # 英文前端（NotebookLM 风格）
├── frontend_zh/             # 中文前端
├── database/                # 数据库脚本
├── docs/                    # 文档
├── script/                  # CLI 与脚本
├── static/                  # 静态资源与 README 配图
└── outputs/                 # 生成文件输出目录
```

---

## 🤝 参与贡献

欢迎提交 Issue、Pull Request 以及文档改进。

[![Issues](https://img.shields.io/badge/Issues-Submit_Bug-red?style=for-the-badge&logo=github)](https://github.com/your-org/opennoteboolLM/issues)
[![PR](https://img.shields.io/badge/PR-Submit_Code-green?style=for-the-badge&logo=github)](https://github.com/your-org/opennoteboolLM/pulls)

详见 [贡献指南](docs/contributing.md)。

---

## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE)。

---

<div align="center">

**若本项目对你有帮助，欢迎 ⭐ Star**

</div>
