# Supabase / 数据库配置说明

项目里**数据库（Supabase）**的配置分布在**后端**和**前端**两处，通过环境变量传入。

---

## 1. 后端（FastAPI）

### 配置位置

- **读取代码**：`fastapi_app/dependencies/auth.py`
  - `get_supabase_client()`：用 **anon key**，用于 JWT 校验、前端直连时的 RLS
  - `get_supabase_admin_client()`：用 **service role key**，用于服务端写库（对话、输出、笔记本等）

- **环境变量**（需在**运行后端的进程**里生效）：

  | 变量名 | 用途 | 必填 |
  |--------|------|------|
  | `SUPABASE_URL` | 项目 URL，如 `https://xxxx.supabase.co` | 用 Supabase 时必填 |
  | `SUPABASE_ANON_KEY` | 匿名公钥（Settings → API → anon public） | JWT 校验时必填 |
  | `SUPABASE_SERVICE_ROLE_KEY` | 服务端密钥（Settings → API → service_role） | 后端写库时必填 |

- **写入方式**：在 **`fastapi_app/.env`** 中配置（若用 dotenv），或启动前在 shell 里 `export`。

### 后端如何读到 .env

- `fastapi_app/config/settings.py` 里 Pydantic 的 `env_file = ".env"` 只影响 **settings** 里的配置项，**不会**自动给 `os.getenv()` 用的 Supabase 变量加料。
- 若希望用 `fastapi_app/.env` 给 Supabase 用，需要：
  - 在**项目根**或 **fastapi_app** 目录下启动（且把 `.env` 放在同一目录），并确保有地方执行 `load_dotenv()`（例如在 `main.py` 最开头加 `from dotenv import load_dotenv; load_dotenv()`），或
  - 在启动命令前 `export` 上述三个变量。

**示例 `fastapi_app/.env`：**

```env
SUPABASE_URL=https://你的项目.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 2. 前端（Vite / frontend-v2）

### 配置位置

- **读取代码**：`frontend-v2/src/lib/supabase.ts`
  - 用 `import.meta.env.VITE_SUPABASE_URL` 和 `import.meta.env.VITE_SUPABASE_ANON_KEY` 创建 Supabase 客户端。
  - `isSupabaseConfigured()` 为 true 时才会用 Supabase（登录、知识库文件、表 `knowledge_base_files` 等）。

- **环境变量**（必须以 `VITE_` 开头，构建/开发时注入）：
  - `VITE_SUPABASE_URL`：同后端，项目 URL。
  - `VITE_SUPABASE_ANON_KEY`：同后端的 anon key（**不要**在前端放 service_role key）。

- **写入方式**：在 **`frontend-v2/.env`** 或 `frontend-v2/.env.local` 中配置。

**示例 `frontend-v2/.env`：**

```env
VITE_SUPABASE_URL=https://你的项目.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 3. 配置汇总表

| 用途 | 后端 env | 前端 env | 说明 |
|------|----------|----------|------|
| 项目 URL | `SUPABASE_URL` | `VITE_SUPABASE_URL` | 同一项目填同一个 URL |
| 匿名 key | `SUPABASE_ANON_KEY` | `VITE_SUPABASE_ANON_KEY` | 前端 + 后端 JWT 校验 |
| 服务端 key | `SUPABASE_SERVICE_ROLE_KEY` | 不配置 | 仅后端，用于写库 |

---

## 4. 未配置时的行为

- **后端**：`get_supabase_admin_client()` 返回 `None` 时，笔记本/对话/输出会走**本地回退**（本地 JSON 文件或磁盘扫描），不会报错。
- **前端**：未配置 `VITE_SUPABASE_*` 时，`isSupabaseConfigured()` 为 false，使用 mock 用户和 localStorage，不连 Supabase。

---

## 5. 表结构（Supabase SQL Editor）

若使用 Supabase，需在项目中执行建表脚本（通常位于 `database/` 或项目根下的 SQL 文件），例如：

- `01_init_schema.sql`：基础表 + `knowledge_bases`、`knowledge_base_files` 等
- `05_kb_conversations.sql`：对话与消息表
- `06_kb_output_records.sql`：生成记录表

在 Supabase 控制台 → SQL Editor 中执行对应脚本即可。
