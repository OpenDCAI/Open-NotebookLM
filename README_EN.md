<div align="center">

<img src="docs/assets/thinkflow/thinkflow-logo.png" alt="ThinkFlow Logo" width="720"/>

# Open-NotebookLM / ThinkFlow

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=111111)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-5-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![License](https://img.shields.io/badge/License-Apache_2.0-2F80ED?style=flat-square&logo=apache&logoColor=white)](LICENSE)
[![GitHub Repo](https://img.shields.io/badge/GitHub-OpenDCAI%2FOpen--NotebookLM-24292F?style=flat-square&logo=github&logoColor=white)](https://github.com/OpenDCAI/Open-NotebookLM)

[中文](README.md) | English

✨ **An AI knowledge workspace for paper reading, product research, course learning, and team presentations: from source ingestion and grounded chat to multimodal retrieval, knowledge assets, reports, mindmaps, PPTs, podcasts, flashcards, and quizzes** ✨

| 📚 **Source-grounded QA** &nbsp;|&nbsp; 🧠 **Multimodal Retrieval** &nbsp;|&nbsp; 📝 **Knowledge Workspace** &nbsp;|&nbsp; 🎬 **Multi-output Generation** |

<br>

<a href="#-quick-start" target="_self">
  <img alt="Quick Start" src="https://img.shields.io/badge/🚀-Quick_Start-2F80ED?style=for-the-badge" />
</a>
<a href="#-showcase" target="_self">
  <img alt="Showcase" src="https://img.shields.io/badge/📸-Showcase-56CCF2?style=for-the-badge" />
</a>
<a href="docs/thinkflow-readme.md" target="_blank">
  <img alt="Walkthrough" src="https://img.shields.io/badge/📚-Walkthrough-2D9CDB?style=for-the-badge" />
</a>
<a href="docs/development-architecture-guide.md" target="_blank">
  <img alt="Architecture" src="https://img.shields.io/badge/🧩-Architecture-27AE60?style=for-the-badge" />
</a>

<br>
<br>

<img src="docs/assets/thinkflow/dashboard.png" alt="ThinkFlow workspace dashboard" width="92%"/>

</div>

## 📑 Table of Contents

- [✨ Core Features](#-core-features)
- [🔁 Workflow](#-workflow)
- [📸 Showcase](#-showcase)
- [🚀 Quick Start](#-quick-start)
- [⚙️ Configuration](#️-configuration)
- [📂 Project Structure](#-project-structure)
- [🧪 Development Commands](#-development-commands)
- [📦 Data and Artifacts](#-data-and-artifacts)
- [🗺️ Roadmap](#️-roadmap)
- [📚 More Docs](#-more-docs)

## ✨ Core Features

> ThinkFlow turns a notebook into a traceable knowledge production loop: sources enter the notebook, conversations refine understanding, confirmed knowledge is saved, and final outputs are generated from locked context.

- **📚 Unified source ingestion**: upload files, paste text, import URLs, run search/deep-research flows, and organize all materials inside one notebook.
- **💬 Source-grounded conversation**: ask questions against selected sources, keep citations and source mappings, and continue in multiple named conversation branches.
- **🧠 VLM multimodal retrieval**: switch between text mode and VLM mode, attach or paste images, retrieve PDF page images/figures, and ground answers in visual evidence.
- **🖼️ PDF image indexing and gallery**: rebuild PDF image indexes, view extracted images, and feed those visual assets into retrieval and downstream outputs.
- **📝 Knowledge workspace**: save useful answers into Summary cards, editable documents, and output guidance instead of losing them in chat history.
- **📌 Stateful conversations**: preserve selected sources, bound documents, active documents, and output context per conversation.
- **📄 Report generation**: produce report drafts from sources, documents, and guidance.
- **🗺️ Mindmap generation**: turn source material into navigable hierarchical maps with preview and export options.
- **🎞️ PPT workflow**: generate outlines first, then review and produce slide-level presentation content.
- **🎧 Podcast generation**: generate scripts and playable audio from source-grounded context.
- **🧩 Learning outputs**: create flashcards and quizzes for course review, onboarding, and knowledge checks.
- **🎬 Video generation**: generate storyboards, narration scripts, and video outputs from source material.

---

## 🔁 Workflow

<div align="center">

| 1. Ingest | 2. Ask | 3. Save | 4. Guide | 5. Generate |
| --- | --- | --- | --- | --- |
| PDF / Word / image / audio / video / text / web | Text RAG or VLM retrieval | Summary, documents, and reusable notes | Output guidance and source snapshots | Report, mindmap, PPT, video, podcast, cards, quiz |

</div>

ThinkFlow is not a one-shot chat window. It is designed for iterative knowledge work:

1. **Create a notebook** for a paper, product investigation, class, or team presentation.
2. **Import sources** and select which ones should participate in each conversation or output.
3. **Ask source-grounded questions** in text mode, or switch to VLM mode for images, screenshots, PDF figures, and visual references.
4. **Save confirmed knowledge** into Summary, documents, and output guidance.
5. **Generate final artifacts** from a locked source/document/guidance context so results remain traceable.

---

## 📸 Showcase

### 📚 Source Workspace and Grounded Chat

<div align="center">

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/来源展示.png" width="100%"/>
      <br><sub>✨ Bring files, text, URLs, search results, and deep-research materials into one notebook</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/thinkflow/workspace-sources.png" width="100%"/>
      <br><sub>✨ Use the three-column workspace to manage sources, chat, documents, and outputs</sub>
    </td>
  </tr>
</table>

</div>

### 🧠 Multimodal Retrieval

<div align="center">

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/文本模式.png" width="100%"/>
      <br><sub>✨ Text mode retrieves source chunks and answers with grounded context</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/VLM模式.png" width="100%"/>
      <br><sub>✨ VLM mode accepts image prompts and retrieves visual evidence from PDFs and image sources</sub>
    </td>
  </tr>
</table>

</div>

### 📝 Knowledge Workspace

<div align="center">

<table>
  <tr>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/沉淀摘要.png" width="100%"/>
      <br><sub>✨ Save distilled conclusions into Summary cards</sub>
    </td>
    <td width="34%" align="center" valign="top">
      <img src="docs/assets/showcase/沉淀文档.png" width="100%"/>
      <br><sub>✨ Maintain editable documents as the main input for reports and PPTs</sub>
    </td>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/沉淀产出指导.png" width="100%"/>
      <br><sub>✨ Save audience, style, and focus constraints as output guidance</sub>
    </td>
  </tr>
</table>

<br>

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/沉淀操作.png" width="100%"/>
      <br><sub>✨ Push valuable chat answers into reusable knowledge assets</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/沉淀为文档之后可以勾选引用了.png" width="100%"/>
      <br><sub>✨ Reuse saved documents as explicit references for later outputs</sub>
    </td>
  </tr>
</table>

</div>

### 📄 Reports and Mindmaps

<div align="center">

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/报告1.png" width="100%"/>
      <br><sub>✨ Generate report drafts from sources, documents, and guidance</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/思维1.png" width="100%"/>
      <br><sub>✨ Turn source material into a structured mindmap for fast review</sub>
    </td>
  </tr>
</table>

</div>

### 🧩 Learning Outputs

<div align="center">

<table>
  <tr>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/卡片1.png" width="100%"/>
      <br><sub>✨ Convert source content into flashcards</sub>
    </td>
    <td width="34%" align="center" valign="top">
      <img src="docs/assets/showcase/学习卡片结果.png" width="100%"/>
      <br><sub>✨ Review and flip cards in the workspace</sub>
    </td>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/问卷1.png" width="100%"/>
      <br><sub>✨ Generate quizzes with answers and explanations</sub>
    </td>
  </tr>
</table>

</div>

### 🎞️ PPT, Video, and Podcast

<div align="center">

<table>
  <tr>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/ppt1.png" width="100%"/>
      <br><sub>✨ Create and refine PPT outlines before slide generation</sub>
    </td>
    <td width="34%" align="center" valign="top">
      <img src="docs/assets/showcase/ppt2.png" width="100%"/>
      <br><sub>✨ Review slide generation progress and page-level content</sub>
    </td>
    <td width="33%" align="center" valign="top">
      <img src="docs/assets/showcase/ppt3.png" width="100%"/>
      <br><sub>✨ Open generated PPT results inside the output workspace</sub>
    </td>
  </tr>
</table>

<br>

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/视频2.png" width="100%"/>
      <br><sub>✨ Confirm narration and storyboard before video rendering</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/assets/showcase/播客1.png" width="100%"/>
      <br><sub>✨ Generate podcast scripts and playable audio from locked sources</sub>
    </td>
  </tr>
</table>

<br>

<a href="docs/assets/showcase/video-demo.mp4">View video generation demo</a>

</div>

---

## 🚀 Quick Start

### Requirements

- Python 3.11 or newer
- Node.js 18 or newer
- npm
- LLM and embedding API configuration for the features you want to run
- Optional: `ffmpeg` for audio/video processing and media outputs

Ubuntu example for common media/runtime packages:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg libxcb-shm0 libxcb-shape0 libxcb-xfixes0
```

### 1. Clone and enter the project

```bash
git clone https://github.com/OpenDCAI/Open-NotebookLM.git
cd Open-NotebookLM
```

### 2. Create environment and install backend dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For tests:

```bash
pip install -r requirements-dev.txt
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 4. Configure environment variables

```bash
cp fastapi_app/.env.example fastapi_app/.env
```

Edit `fastapi_app/.env` with at least LLM and embedding settings. See [Configuration](#️-configuration) for examples.

### 5. Start all services

```bash
./scripts/start.sh
```

The script starts:

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:3001`
- Local embedding service on port `8899` if that port is free
- Monitor script for basic process recovery

Stop services:

```bash
./scripts/stop.sh
```

### 6. Manual startup

If you do not want the script to start the bundled local embedding service, run backend and frontend manually:

```bash
# Terminal 1: backend
python -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000
```

```bash
# Terminal 2: frontend
cd frontend
npm run dev -- --host 0.0.0.0 --port 3001
```

Then open:

```text
http://localhost:3001
```

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

---

## ⚙️ Configuration

All backend configuration lives in `fastapi_app/.env`. The example file uses placeholders only; replace them with your own provider settings.

### LLM

```bash
LLM_API_URL=https://api.example.com/v1
LLM_API_KEY=your_llm_api_key
LLM_MODEL=your_model_name
```

### Embedding

OpenAI-compatible or ApiYi-compatible embedding:

```bash
EMBEDDING_PROVIDER=apiyi
EMBEDDING_API_URL=https://api.example.com/v1
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

Local embedding service:

```bash
EMBEDDING_PROVIDER=local
EMBEDDING_API_URL=http://localhost:8899/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=/path/to/your/embedding-model
EMBEDDING_DIMENSION=1024
```

> [!NOTE]
> `scripts/start.sh` will try to launch `scripts/start_embedding_4b.sh` when port `8899` is free. If the default local model path is not available on your machine, either set `EMBEDDING_MODEL` and `EMBEDDING_PYTHON_BIN`, or use an external embedding provider.

### VLM and visual embedding

These settings enable image attachments, PDF image retrieval, and multimodal answer grounding:

```bash
KB_VLM_MODEL=your_multimodal_chat_model
VISUAL_EMBEDDING_API_URL=https://api.example.com/v1
VISUAL_EMBEDDING_API_KEY=your_visual_embedding_api_key
VISUAL_EMBEDDING_MODEL=your_visual_embedding_model
```

If `VISUAL_EMBEDDING_API_KEY` is empty, the visual embedding client can fall back to the normal embedding key. If VLM or visual embedding is not configured, text RAG, source ingestion, documents, and standard outputs can still run.

### TTS, search, image generation, and video

```bash
TTS_PROVIDER=apiyi
TTS_API_URL=https://api.example.com/v1
TTS_API_KEY=your_tts_api_key
TTS_MODEL=qwen-tts

SEARCH_PROVIDER=serper
SERPER_API_KEY=your_serper_key_here
SERPAPI_KEY=your_serpapi_key_here
BOCHA_API_KEY=your_bocha_key_here

IMAGE_GEN_API_URL=https://api.example.com/v1
IMAGE_GEN_API_KEY=your_image_gen_api_key
IMAGE_GEN_MODEL=your_image_model

GUI_PLUS_API_KEY=your_dashscope_or_bailian_key
LIVEPORTRAIT_KEY=your_liveportrait_key
```

### Supabase authentication

Supabase is optional. If it is not configured, the app can still run with local workspace data under `outputs/`.

```bash
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

---

## 📂 Project Structure

```text
.
├── fastapi_app/              # FastAPI backend: auth, notebooks, sources, documents, outputs, search, TTS
├── frontend/                 # React + Vite frontend for the ThinkFlow workspace
├── workflow_engine/          # Workflow orchestration, multimodal tools, prompt templates, output pipelines
├── docs/                     # Product docs, architecture notes, walkthroughs, and README assets
│   └── assets/               # Screenshots, logo, and showcase video used by README/docs
├── scripts/                  # Start/stop scripts, monitor, and local embedding service launcher
├── static/                   # Static README/product assets
├── requirements.txt          # Standard Python dependency entrypoint
├── requirements-base.txt     # Backend runtime dependency list
└── requirements-dev.txt      # Test/development dependencies
```

---

## 🧪 Development Commands

```bash
# Backend tests
pytest -q

# Backend syntax check
python -m compileall fastapi_app workflow_engine scripts

# Frontend build
cd frontend && npm run build

# Frontend tests
cd frontend && npm test

# Service health
curl http://localhost:8000/health

# Stop script-started services
./scripts/stop.sh
```

---

## 📦 Data and Artifacts

- `outputs/`: notebooks, uploaded sources, generated outputs, vector indexes, and local workspace state.
- `logs/`: backend/frontend/embedding logs when started through `scripts/start.sh`.
- `docs/assets/thinkflow/`: README logo and walkthrough screenshots.
- `docs/assets/showcase/`: feature screenshots and video demo assets.

> [!IMPORTANT]
> Do not commit real `.env` files, provider API keys, model credentials, generated user data, or private notebook outputs.

---

## 🗺️ Roadmap

| Status | Area | Direction |
| --- | --- | --- |
| ✅ | Source-grounded workspace | Notebook, sources, conversations, citations, documents, and outputs |
| ✅ | Multimodal retrieval | VLM mode, image attachments, visual embedding, PDF image gallery |
| ✅ | Knowledge assets | Summary cards, editable documents, output guidance, document references |
| ✅ | Multi-output generation | Report, mindmap, PPT, podcast, flashcards, quiz, video |
| 🚧 | Editable output workflows | More structured review and edit loops for presentation/video/report artifacts |
| 🚧 | Deployment recipes | Clearer Docker/production setup and provider-specific configuration guides |
| 🚧 | Evaluation and tracing | Better generation traces, source coverage checks, and output quality diagnostics |

---

## 📚 More Docs

- [docs/](docs/)

You can use Claude Code / Codex to read `docs/` and understand the project.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).
