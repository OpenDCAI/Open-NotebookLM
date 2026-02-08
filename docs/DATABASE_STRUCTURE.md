# 当前数据库里会存什么 / 能存什么（按现有表结构）

以**当前代码 + 现有 SQL 表结构**为准，说明：创建新笔记本时库里会多什么、以及库里都有哪些表、分别存什么。

---

## 一、创建新笔记本时，数据库里会多什么？

- **配置了 Supabase 且后端能连上时**  
  会往 **`knowledge_bases`** 表里插入**一行**，例如：

  | 字段 | 含义 | 示例 |
  |------|------|------|
  | `id` | 笔记本唯一 ID（UUID） | 自动生成 |
  | `user_id` | 所属用户（Supabase auth.users.id） | 前端传的 user_id |
  | `name` | 笔记本名称 | 用户输入的「笔记本名称」 |
  | `description` | 描述 | 可为空，当前前端一般传 `""` |
  | `created_at` | 创建时间 | 自动 |
  | `updated_at` | 更新时间 | 自动 |

  也就是说：**创建新笔记本 = 只在 `knowledge_bases` 里新增一条记录**，不会自动在别的表里写东西。

- **未配置 Supabase 或连不上时**  
  不会写数据库，会走本地回退：在 `outputs/kb_data/_notebooks/{user_id}.json` 里追加一条笔记本（id 为 `local_xxx` 这种）。

---

## 二、当前数据库里「有什么表」「能存什么」（按现有数据结构）

下面都是**按现有 SQL 建表脚本**来的，执行了哪些脚本，就有哪些表。

### 1. `knowledge_bases`（笔记本/目录）

- **能存什么**：每个「笔记本」一条记录。
- **主要字段**：
  - `id` (UUID)，`user_id` (谁创建的)，`name`（名称），`description`（描述），`created_at` / `updated_at`。
- **谁在写**：前端点「新建笔记本」→ 后端 `POST /api/v1/kb/notebooks` → 有 Supabase 时插入这里。

---

### 2. `knowledge_base_files`（知识库文件元数据）

- **能存什么**：每个上传到知识库的文件的**元数据**（文件名、类型、大小、存储路径、属于哪个笔记本等）。**不存文件内容**，文件本体在本地或 Storage。
- **主要字段**：
  - `id`, `user_id`, `user_email`, `file_name`, `file_type`, `file_size`, `storage_path`（路径或 URL）, `is_embedded`, `kb_file_id`（向量库里的 id）, **`kb_id`**（属于哪个笔记本，对应 `knowledge_bases.id`）, `description`, `created_at`.
- **谁在写**：用户上传文件时，前端在 Supabase 里 insert 一行（并带上当前 `notebook.id` 作 `kb_id`）；embedding 写回时可能更新 `kb_file_id`、`is_embedded` 等。

---

### 3. `kb_conversations`（对话会话）

- **能存什么**：每个「对话」一条记录，可关联到某个笔记本（也可不关联，全局对话）。
- **主要字段**：
  - `id`, `user_id`, `user_email`, **`notebook_id`**（关联到 `knowledge_bases.id`，可为空）, `title`, `created_at`, `updated_at`.
- **谁在写**：用户打开某个笔记本并发第一条消息时，后端「获取或创建」该用户+该笔记本的一条会话，插入或更新这里。

---

### 4. `kb_chat_messages`（对话里的每条消息）

- **能存什么**：某次对话下的**每条**用户/助手消息。
- **主要字段**：
  - `id`, **`conversation_id`**（属于哪条 `kb_conversations`）, `role`（'user'/'assistant'/'system'）, `content`（文本）, `created_at`.
- **谁在写**：用户在该笔记本里发消息、后端返回回复后，后端往对应 `conversation_id` 下 append 两条：一条 user，一条 assistant。

---

### 5. `kb_output_records`（生成记录：PPT/思维导图/播客）

- **能存什么**：每次用知识库生成 PPT、思维导图、播客的**一条记录**（类型、路径、下载地址等）。
- **主要字段**：
  - `id`, `user_id`, `user_email`, **`notebook_id`**（可选，当前代码多传 null）, `output_type`（'ppt'/'mindmap'/'podcast'）, `file_name`, `file_path`, `result_path`, `download_url`, `extra` (JSONB), `created_at`.
- **谁在写**：后端在 `generate_ppt_from_kb` / `generate_podcast_from_kb` / `generate_mindmap_from_kb` 成功返回前调用 `_save_output_record(...)` 插入这里。

---

### 6. 其他表（01_init_schema 等里的，和「笔记本」无直接绑定）

- **`usage_records`**：按用户、按 workflow 类型的调用记录（可做用量/配额）。
- **`user_files`**：生成的文件的元数据（通用，不限于知识库）。
- **`profiles`**：用户资料（如邀请码等）。
- **`referrals`**：邀请关系。
- **`points_ledger`**：积分流水；**`points_balance`** 为视图，算当前余额。

这些表**不会**在「创建新笔记本」时被写入；和当前「笔记本 + 知识库」逻辑直接相关的是上面 1～5。

---

## 三、小结（按当前逻辑 + 现有数据结构）

- **创建新笔记本**：  
  数据库里**只会**在 **`knowledge_bases`** 里多一条记录（id、user_id、name、description、时间戳）。  
  其他表不会因为「点一下创建笔记本」而自动有数据。

- **当前数据库里会/能存的东西**（和笔记本/知识库相关的）：
  1. **笔记本本身**：`knowledge_bases`
  2. **每个笔记本里的文件元数据**：`knowledge_base_files`（通过 `kb_id` 关联笔记本）
  3. **每个笔记本的对话会话**：`kb_conversations`（通过 `notebook_id` 关联笔记本）
  4. **每条对话里的消息**：`kb_chat_messages`（通过 `conversation_id` 关联会话）
  5. **生成结果记录**：`kb_output_records`（目前多数 `notebook_id` 为 null，但表结构支持按笔记本存）

以上都是**按现有数据结构**说明的「会存什么、能存什么」；若你后续改了表或写入逻辑，以实际代码和迁移脚本为准。

---

## 四、来源（文件列表）怎么读？和用户怎么连？

「来源」= 左侧展示的知识库文件列表，**只在前端读**，和用户的绑定靠 **user_id（和可选 notebook id）**。

### 1. 用户是谁（和谁连）

- **配置了 Supabase 时**  
  - 登录态来自 `supabase.auth.getSession()` / `onAuthStateChange`。  
  - 前端把 `session` 放进 `authStore`，用到的用户标识是 **`user.id`**（Supabase `auth.users.id`）和 `user.email`。  
  - 所以「当前用户」= 当前 Supabase 登录用户的 `user.id`。

- **未配置 Supabase 时**  
  - 使用 mock 用户：`user.id = 'dev-user-001'`，`user.email = 'dev@notebook.local'`。  
  - 所有「来源」和「笔记本」都按这个 mock 用户隔离（本地 JSON + localStorage）。

### 2. 来源（文件列表）怎么读——和笔记本绑定，每个笔记本独立来源

- **配置了 Supabase 且当前笔记本来自数据库（UUID）**  
  - 在 `NotebookView` 里调 `fetchFiles()`：  
    - `supabase.from('knowledge_base_files').select('*').eq('user_id', user?.id).eq('kb_id', notebook.id)`  
  - 即：**只读该笔记本下的来源**（按 `user_id` + `kb_id`）。  
  - 上传时插入 `knowledge_base_files` 并带 `kb_id = notebook.id`，所以来源和笔记本一一对应。

- **本地笔记本（id 以 `local_` 开头）或未配置 Supabase**  
  - 从 **localStorage** 读：key = `kb_files_${user.id}_${notebook.id}`（有笔记本时），这样**每个笔记本一个 key，互不共用**。  
  - 上传时只往当前笔记本对应的 key 里 append，不写入 Supabase（本地笔记本没有对应 `knowledge_bases` 行）。

### 3. 和用户、笔记本的连接总结

| 环节         | 和用户、笔记本怎么连 |
|--------------|----------------------|
| 用户身份     | Supabase：`auth.session.user.id` → `user.id`；未配置：mock `user.id` |
| 来源列表读取 | **每个笔记本独立**：Supabase 笔记本按 `user_id` + `kb_id` 查；本地笔记本按 localStorage `kb_files_${user.id}_${notebook.id}` |
| 上传文件落库 | 数据库笔记本：insert 带 `user_id` + `kb_id`；本地笔记本：只写 localStorage 对应 key |
| 笔记本列表   | 后端 GET /kb/notebooks 传 `user_id`；Supabase 表 `knowledge_bases` 按 `user_id` 查 |

所以：**来源和笔记本一一对应**：每个笔记本只显示、只写入该笔记本下的来源；和用户的连接是 **user_id**，和笔记本的连接是 **kb_id**（数据库）或 **localStorage key 里的 notebook.id**（本地）。
