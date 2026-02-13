# Chat 上下文优化方案

本文档基于当前 `intelligent_qa` 工作流的实现，分析上下文使用中的问题，并给出可落地的优化思路与模块建议。

---

## 一、当前实现中的问题（为什么说「直接塞入」）

### 1. 上下文构建方式

- **选档策略**：用户勾选的所有文件都会参与，没有「按问题筛选」。
- **单文件处理**：每个文件整篇抽取（PDF/Word/PPT 全文），再截断到约 50k 字符后，整块送给 LLM 做「单文件分析」。
- **汇总阶段**：把所有文件的 `analysis` 字符串简单拼接成 `analyses_str`，和 `history_str`、`query` 一起塞进**一条** HumanMessage，没有长度或 token 控制。

相关代码位置：

- 上下文聚合：`dataflow_agent/workflow/wf_intelligent_qa.py` 中 `chat_node`（约 262–284 行）
- 单文件截断：同文件 `process_file` 内 `raw_content[:50000]`
- Prompt 模板：`dataflow_agent/promptstemplates/resources/pt_qa_agent_repo.py` 中 `final_qa_prompt`

### 2. 对话历史

- 历史被拼成字符串：`role: content\n`，而不是多轮 `System/Human/AI` 消息。
- 没有长度/轮数限制，长对话会无限撑大 prompt，易超长、易丢近期重点。

### 3. 与检索能力脱节

- 项目里已有 `VectorStoreManager`（`toolkits/ragtool/vector_store_tool.py`）和 `/api/v1/kb/embedding` 的建索引、检索接口。
- 当前 QA 流程**没有**走检索：不按 query 做语义检索，而是「选中的文件全部解析 + 全部分析 + 全部塞入」。

---

## 二、优化方向概览

| 方向 | 目的 | 难度 |
|------|------|------|
| 1. 检索增强（RAG） | 按问题只取相关片段，控制上下文长度 | 中 |
| 2. 上下文窗口管理 | 限制 token/字符、滑动窗口或摘要 | 中 |
| 3. 多轮消息结构 | 用真实多轮消息 + 历史裁剪/摘要 | 低～中 |
| 4. 分块与索引策略 | 更合理的 chunk 与索引，便于检索 | 中 |
| 5. 查询路由 / 选档 | 先判断问题再选文件或检索范围 | 可选 |

下面按「可直接用的模块/库」和「改工作流/状态」两部分给出具体思路。

---

## 三、推荐模块与思路

### 3.1 检索增强（RAG）—— 用现有 VectorStore，按 query 取 Top-K

**思路**：  
在 `intelligent_qa` 中增加「检索分支」：若当前 notebook 已建好 embedding（有 vector store），则用 **query + 当前选中的 file 列表** 做语义检索，只把 **Top-K 个 chunk**（及所属文件信息）作为「文档上下文」送给最终 QA；未建索引或未选文件时再回退到现有「全量解析 + 全量分析」。

这样上下文从「所有选中文件的全部分析」变为「与问题最相关的 K 段」，长度可控、相关性更好。

**可用的项目内模块**：

- `dataflow_agent.toolkits.ragtool.vector_store_tool.VectorStoreManager`
  - `search(query, top_k=5, file_ids=None)`：已支持按 `file_ids` 过滤（与当前「选中文件」对应）。
- 后端已有 `kb_embedding` 路由和按 notebook 的 vector store 路径约定（如 `outputs/kb_data/{email}/{notebook_id}/vector_store`），只需在 QA 请求里带上 `notebook_id` / `email`，后端解析出 `vector_store` 路径并调用 `VectorStoreManager.search`。

**实现要点**：

- 在 `IntelligentQARequest`（或等价请求体）中增加可选字段：`notebook_id`、`email`（或直接传 `vector_store_base_dir`）。
- 在 `parallel_parse_node` 之前或之后增加一步：
  - 若存在 vector store 且能根据请求找到对应 index：  
    `retrieved = manager.search(query, top_k=10, file_ids=selected_file_ids)`  
    将 `retrieved` 中的 `content`、`source_file_id`、`score` 拼成「检索上下文」。
  - 若没有索引或未选文件：走现有「按文件解析 + 每文件 LLM 分析」逻辑；此时可以只对「与 query 更相关」的文件做分析（见下「查询感知的选档」）。
- 最终 `chat_node` 的 prompt 中：用「检索到的片段」替代或补充「全部 file_analyses」，并明确标注来源文件，便于引用。

**可选第三方**：  
若后续要换或加强检索（如多向量、过滤条件），可考虑 **LangChain** 的 `VectorStoreRetriever` / `ContextualCompressionRetriever`，或 **LlamaIndex** 的 `VectorStoreIndex.as_retriever(similarity_top_k=...)`，与现有 FAISS 可对接（封装成 Retriever 接口即可）。

---

### 3.2 上下文长度与 token 管理

**问题**：  
当前没有对「最终 prompt」做 token 或字符数上限，容易超模型上下文窗。

**思路**：

1. **为「文档上下文」设上限**  
   例如：只保留前 N 个 token（或前 M 个字符，用简单比例估 token），超出部分：
   - 丢弃末尾，或  
   - 用「滑动窗口」保留最近几段，或  
   - 对超出部分做一次「摘要」再拼回去（成本较高，可作为后续增强）。

2. **为「对话历史」设上限**  
   - 方案 A：只保留最近 K 轮（例如 6 轮），更早的丢弃或做一轮 summarization 成一条 system/user 消息。  
   - 方案 B：对历史做「 summarization」：超过一定轮数后，用 LLM 把更早的对话压缩成一段「背景摘要」，再拼上最近几轮原始消息。

**可用的库**：

- **tiktoken**（OpenAI）：按模型名算 token 数，便于在拼接前截断或计数。
- **LangChain** 的 `get_num_tokens` / `trim_messages`（如 `ConversationTokenBufferMemory` 的 trim 逻辑）：可参考其「按 token 截断历史」的实现，在服务端对 `history` 做同样逻辑后再拼成多轮消息或摘要。

建议在 `chat_node` 里：  
先算 `query + 文档上下文 + 历史` 的 token 数，若超过设定阈值，则优先截断或压缩「文档上下文」和「历史」（保留最近几轮 + 摘要）。

---

### 3.3 多轮消息结构（而不是一大段字符串）

**现状**：  
`history_str` 是 `"user: xxx\nassistant: xxx\n"` 的拼接，最终和 `file_analyses`、`query` 一起放进**一条** HumanMessage，模型看到的是「一整段文字」而不是标准多轮对话。

**思路**：  
在调用最终 QA 的 LLM 时，构建 **真正的多轮消息**：

- `SystemMessage`：系统说明（可包含「请基于以下文档片段与对话历史回答」等）。
- 若使用 RAG：一条或若干条 `HumanMessage` 表示「文档上下文」（例如：`以下是与问题相关的文档片段：\n...`），或按片段拆成多条带 `role` 的文档消息（视模型与实现而定）。
- 然后追加 **历史多轮**：`HumanMessage` / `AIMessage` 交替，条数由「历史裁剪」控制（见上）。
- 最后一条 `HumanMessage`：当前 `query`（可带「请结合上述文档与对话回答」）。

这样既符合常见 Chat API 的用法，也便于后续做「仅最近几轮 + 摘要」的裁剪。

**实现要点**：

- 在 `chat_node` 中不再组 `history_str`，而是把 `state.request.history` 转成 `List[BaseMessage]`（HumanMessage/AIMessage），再和「文档上下文」「当前 query」按顺序组成 `messages`。
- 若继续用 `kb_prompt_agent`，需要支持「传入多轮 messages」而不是单一 `prompt` 字符串；一种做法是给 agent 增加一种执行路径：当 `pre_tool_results` 中含有 `messages` 时，直接使用该列表调用 LLM，而不是通过 `build_messages` 生成单条 HumanMessage。

---

### 3.4 分块与索引策略（与 RAG 配套）

当前 RAG 侧（MinerU + 按 `\n\n` 分块）已经存在；若希望检索质量更好，可以：

- **分块**：按语义段落或固定 token 数（如 256/512）chunk，重叠可加 50–100 token，减少断句。
- **元数据**：在 `meta_data` 里保留 `source_file_id`、`chunk_index`、`start_char` 等，便于展示引用和去重。
- **可选**：用 **LlamaIndex** 的 `SentenceSplitter`、`NodeParser` 或 LangChain 的 `RecursiveCharacterTextSplitter` 做统一分块，再写入现有 FAISS 索引（仅改写入端，检索接口可不变）。

---

### 3.4.1 RAG - LangChain 分块处理

RAG 的本质是「一个来源分成多块 → 每块做 embedding → 检索时从所有块里取 Top-K」。分块质量直接影响检索是否漏信息、是否断句。LangChain 提供多种 **Text Splitter**，可替代或补充当前按 `\n\n` 的简单分块，统一在写入向量库前做切分。

#### 常用 Text Splitter（`langchain_text_splitters`）

| 类名 | 适用场景 | 特点 |
|------|----------|------|
| `RecursiveCharacterTextSplitter` | 通用长文本（PDF 导出文本、Markdown、代码等） | 按分隔符层级切（如 `\n\n` → `\n` → 空格），尽量在自然边界断句；可设 `chunk_size`、`chunk_overlap`。 |
| `CharacterTextSplitter` | 简单按字符/固定长度切 | 只按单一分隔符（如 `\n`）切，可控但易把一句拆两半。 |
| `TokenTextSplitter` | 需要按 token 数控制长度时 | 依赖 tiktoken 等，按 token 数切，便于和模型上下文对齐。 |
| `MarkdownHeaderTextSplitter` | Markdown 文档 | 按标题层级分块，块内带 header 元数据，便于保留结构。 |

推荐默认用 **`RecursiveCharacterTextSplitter`**：兼顾段落边界和长度上限，且支持重叠，减少「关键句被一刀切断」导致的信息缺失。

#### 核心参数

- **chunk_size**：每块最大长度（字符数或 token 数，视 splitter 而定）。常见 256～1024 字符，或 200～500 token。
- **chunk_overlap**：相邻块重叠长度。例如 50～100 字符，避免关键信息刚好在块边界被截断。
- **separators**（仅部分 splitter）：切分优先级，如 `["\n\n", "\n", " ", ""]`，先按段落再按行再按空格。

#### 示例：与现有 VectorStore 对接

下面示例用 LangChain 分块后，得到「文本列表 + 元数据」，再交给现有 embedding 与 FAISS 写入逻辑（不改变 `VectorStoreManager.search` 接口，只改「写入前的分块」）：

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 按字符数分块，带重叠
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,           # 每块约 500 字符
    chunk_overlap=80,         # 相邻块重叠 80 字符
    length_function=len,
    separators=["\n\n", "\n", "。", "；", " ", ""],  # 中文句号、分号
)

# 对已抽取的文本分块（例如 MinerU 输出的 MD 或 PDF 全文）
raw_text = "..."  # 从 PDF/Word/MinerU 得到的全文
chunks = splitter.split_text(raw_text)

# 带元数据时可用 create_documents，便于后续写向量库
# docs = splitter.create_documents([raw_text], metadatas=[{"source_file_id": file_id}])
```

若希望**按 token 数**控制（便于和模型上下文一致），可用 `TokenTextSplitter`（需安装 `tiktoken`）：

```python
from langchain_text_splitters import TokenTextSplitter

splitter = TokenTextSplitter(
    chunk_size=256,
    chunk_overlap=50,
    encoding_name="cl100k_base",  # 与多数 OpenAI 模型一致
)
chunks = splitter.split_text(raw_text)
```

#### 与项目内流程的衔接

- **写入端**：在 `vector_store_tool.py` 的 `_process_pdf` / 其他 `_process_*` 中，对「抽取后的文本」先用上述 splitter 得到 `chunks`，再对每个 chunk 调 `_call_embedding_api`，并把 `source_file_id`、`chunk_index` 等写入 `meta_data`。这样检索阶段仍用现有 `VectorStoreManager.search(query, top_k, file_ids)`，只是底层块更小、更均匀、带重叠。
- **依赖**：在 `requirements-base.txt` 或单独 RAG 依赖中增加 `langchain-text-splitters`（及按需的 `tiktoken`）。

这样既保留「每个来源被分成多块、检索从多块里取」的 RAG 流程，又用 LangChain 统一、可调的分块策略降低信息缺失和断句问题。

---

### 3.5 查询感知的选档（可选）

若暂时不做 RAG，也可以在做「全量分析」前做一层粗筛：

- 用 **query** 与「文件名 / 路径」做简单匹配（当前已有 `_infer_target_files`），只对匹配到的文件做 LLM 分析；若无匹配则仍对所有选中文件分析。
- 或：用 query 的 embedding 与「每个文件已有摘要或首段」做相似度，只分析 Top-K 个文件，减少调用次数与上下文长度。

---

## 四、建议的落地顺序

1. **短期（低成本）**  
   - 为最终 prompt 增加**字符或 token 上限**（例如 8k token 的文档上下文 + 4k 历史），超出的截断或丢弃。  
   - 将**对话历史**改为**多轮消息**并只保留最近 N 轮，避免无限增长。

2. **中期（高收益）**  
   - 接入**现有 VectorStore 检索**：在 QA 请求中带上 notebook/用户维度，用 `VectorStoreManager.search(query, top_k, file_ids)` 得到片段，替换或补充「全量 file_analyses」。  
   - 统一「文档上下文」的格式（例如带文件名与 score），并在 prompt 中要求模型引用来源。

3. **后续增强**  
   - 历史 summarization（超过 K 轮压缩为一段）。  
   - 更细的分块与索引策略（重叠、语义分块）。  
   - 若有多数据源，可考虑 **LangChain/LlamaIndex 的 Retriever 抽象**，便于切换或组合多种检索方式。

---

## 五、小结

| 问题 | 优化思路 | 可复用模块/库 |
|------|----------|-------------------------------|
| 上下文全量塞入 | RAG：按 query 检索 Top-K 片段 | 现有 `VectorStoreManager.search` |
| 无长度控制 | 为文档上下文与历史设 token/条数上限并截断或摘要 | tiktoken、LangChain trim_messages |
| 历史是字符串 | 改为多轮 Human/AI Message，并只保留最近 N 轮 | 请求中已有 `history` 列表，后端组 `BaseMessage[]` |
| 检索未接入 QA | 在 intelligent_qa 中根据 notebook 调 vector store | `kb_embedding` 路由与路径约定 |
| 分块较粗 | 语义/长度分块、重叠、元数据 | LangChain `RecursiveCharacterTextSplitter` / `TokenTextSplitter`（见 3.4.1） |

按上述顺序迭代，可以在不大改产品形态的前提下，明显改善「chat 上下文」的相关性和长度可控性，并和现有知识库、embedding 能力对齐。
