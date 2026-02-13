# 知识库「来源」从上传到存储的完整流程

本文说明：**上传一个来源**会经历什么，以及**按类型**分别有什么样的存储方式。

---

## 一、整体流程：两阶段

来源的完整链路是 **两阶段**，不是「上传即向量化」：

| 阶段 | 接口 | 做什么 |
|------|------|--------|
| **1. 上传** | `POST /api/v1/kb/upload` | 只把文件**落盘**到该 notebook 目录，**不做**分块、不做 embedding。 |
| **2. 建索引（向量化）** | `POST /api/v1/kb/embedding` | 对**已上传**的文件做：解析 → 分块（文本）或生成描述（图/视频）→ 调用 embedding 模型 → 写入 FAISS + manifest。 |

也就是说：**上传**只负责「存文件」；**建索引**才负责「分块 + 向量 + 检索库」。前端一般会在用户点击「生成向量 / 建索引」时调 `/embedding`，传入当前选中的、已上传的文件列表（path 列表）。

---

## 二、阶段 1：上传时经历什么

- 请求：`POST /api/v1/kb/upload`，带 `file`、`email`、`user_id`、`notebook_id`。
- 校验：后缀必须在允许列表：`.pdf`, `.docx`, `.pptx`, `.png`, `.jpg`, `.jpeg`, `.mp4`, `.md`。
- 落盘路径（按 notebook 隔离）：
  - `outputs/kb_data/{email}/{notebook_id}/{filename}`
  - 例如：`outputs/kb_data/user@example.com/nb_abc/report.pdf`
- 返回：`storage_path`、`static_url`（用于前端展示/下载）等；**此时还没有任何向量或分块**。

---

## 三、阶段 2：建索引时经历什么（按类型）

建索引由 **VectorStoreManager**（`dataflow_agent/toolkits/ragtool/vector_store_tool.py`）完成，入口是 `process_file`。  
向量库根目录（每个 notebook 一个）：`outputs/kb_data/{email}/{notebook_id}/vector_store`。  
其下会有：

- `processed/`：中间产物（MinerU 输出、描述文本等）
- `vector_store/`：FAISS 索引 `kb_project.index` + 元数据 `kb_project.meta`
- `knowledge_manifest.json`：文件列表及每个文件的 id、路径、chunks_count 等

下面按**类型**说每个来源会怎样被处理、怎样存储。

---

### 1. PDF（`.pdf`）

| 步骤 | 说明 |
|------|------|
| 解析 | 用 **MinerU** 抽成 Markdown（保留结构、公式等）。 |
| 存储（中间） | MinerU 全量结果写入 **`outputs/kb_mineru/{email}/{notebook_id}/{file_id}/`**，结构同 [MinerU 输出](https://opendatalab.github.io/MinerU/zh/reference/output_files/)：`{pdf_stem}/auto/*.md`、`images/`、`*_content_list.json`（文本+caption）、`*_model.json`、`*_middle.json` 等，图片全部保留。 |
| 分块 | 对 MD 全文用 **LangChain RecursiveCharacterTextSplitter**（chunk_size=500、overlap=80，分隔符含 `\n\n`、`。`、`；` 等）；若无则回退到按 `\n\n` 分段，过滤掉过短块。 |
| 向量化 | 每个 **chunk** 调一次 **embedding API**（本地 Octen 或配置的远程），得到向量。 |
| 写入检索库 | 向量写入 **FAISS**（IndexFlatIP）；每条对应一条 **meta**：`source_file_id`、`type: "text_chunk"`、`content`（原文）、`chunk_index`。 |
| manifest | 该文件一条记录：`id`、`original_path`、`file_type`、**`chunks_count`**、`processed_md_path`、`images_dir`、**`mineru_output_path`**、**`mineru_content_list_path`**、**`chunks_info_path`**（若有分块则写入）。 |

**如何确认是否做了 chunk**：
- 看该来源在 **manifest** 里的 **`chunks_count`**：大于 0 表示已分块并写入向量库。
- 看 **MinerU 输出目录**（`outputs/kb_mineru/{email}/{notebook_id}/{file_id}/`）下是否有 **`chunks_info.json`**：内有 `chunks_count` 和每个 chunk 的 `chunk_index`、`length`、`preview`（前 300 字），便于核对分块结果。

**总结**：一个 PDF → 一个 `file_id`，对应 **多块** 文本 → **多条** 向量；检索时按 query 从这些块里做相似度搜索。MinerU 的完整解析结果（含图片、文本与 caption）统一在 **`outputs/kb_mineru/`** 下，每个来源一个子目录，与 Paper2Any 类似保留全量结果。

---

### 2. Word（`.docx` / `.doc`）

| 步骤 | 说明 |
|------|------|
| 转换 | 用 **LibreOffice 无头** 转成 PDF，临时放在 `processed/temp/{file_id}/`。 |
| 后续 | 与 **PDF 完全一致**：MinerU 抽 MD → 分块 → 每块 embedding → 写入 FAISS，manifest 里仍是 `original_path` 指向原始 Word 路径。 |

**总结**：存储方式等同 PDF（中间多一步「Word → PDF」），也是 **多 chunk → 多向量**。

---

### 3. PPT（`.pptx` / `.ppt`）

| 步骤 | 说明 |
|------|------|
| 转换 | 同样用 **LibreOffice** 转成 PDF，存 `processed/temp/{file_id}/`。 |
| 后续 | 与 **PDF 一致**：MinerU → MD → 分块 → embedding → FAISS。 |

**总结**：和 Word 一样，**先转 PDF 再走同一套**，存储形态同 PDF。

---

### 4. 图片（`.png` / `.jpg` / `.jpeg`）

| 步骤 | 说明 |
|------|------|
| 描述 | 不分块。用 **多模态 API**（如 image understanding）生成**一段**文字描述（用于检索）。 |
| 存储（中间） | 描述写入 `processed/{file_id}/description.txt`。 |
| 向量化 | 把这一段描述当作 **1 条文本**，调 **1 次** embedding API，得到 **1 个** 向量。 |
| 写入检索库 | 1 条向量 + meta：`source_file_id`、`type: "media_desc"`、`content`（描述）、`path`（原图路径）。 |
| manifest | 该文件一条记录：`media_desc_count: 1`、`description_text_path` 等。 |

**总结**：一个图片 = **1 段描述 = 1 个 chunk = 1 条向量**；检索时用这段描述做语义检索。

---

### 5. 视频（`.mp4` / `.avi` / `.mov`）

| 步骤 | 说明 |
|------|------|
| 描述 | 用 **视频理解 API** 生成**一段**文字描述。 |
| 存储（中间） | 同上：`processed/{file_id}/description.txt`。 |
| 向量化与写入 | 与图片相同：**1 段描述 → 1 次 embedding → 1 条向量**，meta 类型 `media_desc`。 |

**总结**：和图片一样，**一个视频 = 1 个描述 = 1 条向量**。

---

### 6. 其他（如 `.md` 或未在 embedding 里实现的类型）

- **上传**：`.md` 在 ALLOWED_EXTENSIONS 里，可以上传并落盘到 `outputs/kb_data/{email}/{notebook_id}/xxx.md`。
- **建索引**：当前 `process_file` 里只显式处理 `.pdf`、`.docx`/`.doc`、`.pptx`/`.ppt`、图片、视频；其他后缀会走 `else`，`status` 记为 **skipped**，**不会**写入向量库。

若要支持 `.md` 建索引，需要在 `vector_store_tool` 里增加分支：读文本 → 分块 → embedding → 写入 FAISS（逻辑可复用 PDF 的分块与写入）。

---

## 四、按类型汇总表

| 类型 | 上传落盘 | 建索引：中间产物 | 分块 / 描述 | 向量条数 | 检索库中的形态 |
|------|----------|------------------|-------------|----------|----------------|
| **PDF** | `kb_data/{email}/{nb_id}/xxx.pdf` | `processed/{file_id}/`（MinerU 的 MD + images） | 多块（LangChain/段落） | N 条（N = chunk 数） | 每块 1 条，meta 含 content、chunk_index |
| **Word** | 同上 `.docx` | 先转 PDF 再同 PDF | 同 PDF | N 条 | 同 PDF |
| **PPT** | 同上 `.pptx` | 先转 PDF 再同 PDF | 同 PDF | N 条 | 同 PDF |
| **图片** | 同上 `.png`/`.jpg` | `processed/{file_id}/description.txt` | 1 段 VLM 描述 | 1 条 | 1 条 media_desc |
| **视频** | 同上 `.mp4` 等 | 同上 description.txt | 1 段视频理解描述 | 1 条 | 1 条 media_desc |
| **.md 等** | 可上传 | 当前未实现建索引 | - | 0 | 不写入 |

---

## 五、小结

- **上传**：只做「按 notebook 存文件」到 `outputs/kb_data/{email}/{notebook_id}/`，**不**做分块、**不**做 embedding。
- **建索引**：对已上传的文件按类型处理：  
  - **文本类**（PDF/Word/PPT）→ MinerU 全量输出到 **`outputs/kb_mineru/{email}/{notebook_id}/{file_id}/`**（含 md、images、content_list.json 等）→ 用 MD 分块 → 每块 embedding → 多向量进 FAISS；  
  - **图/视频** → VLM 描述 → 1 段文本 → 1 次 embedding → 1 向量进 FAISS。  
- **存储位置**：  
  - 向量与 manifest：`outputs/kb_data/{email}/{notebook_id}/vector_store/`（FAISS + manifest）；  
  - MinerU 全量结果（每个来源一个目录）：`outputs/kb_mineru/{email}/{notebook_id}/{file_id}/`，与 Paper2Any 类似保留完整解析结果和图片。

这样「上传」和「建索引」分离，便于：先上传多个来源，再统一或按需选择部分来源做向量化；且按类型统一了分块/描述与向量存储方式，便于 RAG 检索时行为一致。

---

## 六、补充约定（当前实现）

- **Embedding 入库**：建索引时**只使用本地 embedding**（项目引入的 Octen-Embedding-0.6B，由 `EMBEDDING_API_URL` 配置），不传请求里的 `api_url`，避免使用远程 embedding API。
- **URL / 网页来源**：  
  - 「网站」引入（`import-url-as-source`）与「搜索/链接」批量引入（`import-link-sources`）时，使用 **Playwright** 将 URL 打印为 **PDF** 并保存到笔记本目录。  
  - 建索引时该 PDF 与其它 PDF 一样走 **MinerU → MD → 分块 → 本地 embedding → FAISS**，即**所有来源（含 search 到的 URL、直接爬的 HTML）都过一遍 MinerU**。  
  - 需已安装 Playwright 并执行 `playwright install chromium`。
- **前端展示来源内容**：  
  - 来源详情优先展示 **MinerU 产出的 MD**（`get-source-display-content` 根据 path 查 manifest 中的 `processed_md_path` 并返回内容）。  
  - 若该来源尚未建索引或无 MinerU 结果，则回退到 `parse-local-file` / `fetch-page-content`。
