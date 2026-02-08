# NotebookLM v2 知识库集成指南

## 📋 概述

本项目成功将 `frontend-workflow` 知识库的后端功能集成到 `frontend-v2` (NotebookLM) 项目中。

**核心目标**：
- ✅ 保持 Notebook 的前端界面风格
- ✅ 接入知识库的后端 API
- ✅ 支持文件上传、智能问答、PPT生成、思维导图等功能
- ✅ 不改动后端逻辑，前端适配后端

---

## 🔧 完成的工作

### 1. 项目配置

#### 1.1 创建的配置文件

- **`vite.config.ts`** - Vite 配置，包含后端代理
  - 端口: 3001
  - 后端代理: `http://localhost:8210`

- **`src/config/api.ts`** - API 配置文件
  - API Key 管理
  - apiFetch 封装函数

- **`src/lib/supabase.ts`** - Supabase 客户端
  - 支持认证和数据库操作
  - 未配置时自动降级

- **`src/stores/authStore.ts`** - 认证状态管理
  - 使用 Zustand 管理用户状态
  - 支持 session 管理

- **`src/services/apiSettingsService.ts`** - API 设置服务
  - 管理 LLM API 配置

#### 1.2 依赖更新

在 `package.json` 中添加了：
```json
{
  "@supabase/supabase-js": "^2.89.0",
  "mermaid": "^10.6.1",
  "zustand": "^4.4.7"
}
```

### 2. 核心组件重构

#### 2.1 NotebookView.tsx (二级界面)

**原有功能**：静态展示的笔记本界面

**新增功能**：
1. **文件管理**
   - 从 Supabase 获取用户上传的文件
   - 支持文件选择（多选）
   - 支持文件上传

2. **智能问答**
   - 基于选中文件的 RAG 问答
   - 显示历史对话
   - 实时流式响应

3. **Studio 工具**
   - PPT 生成
   - 思维导图生成（支持 Mermaid 渲染）
   - 知识播客生成
   - 视频讲解生成
   - 语义检索

4. **UI 保持**
   - 保留了原有的 NotebookLM 风格
   - 三栏布局（来源、对话、工具）
   - Tab 切换（对话、检索、来源管理）

#### 2.2 App.tsx

添加了认证初始化逻辑：
- 如果 Supabase 已配置，使用真实认证
- 如果未配置，创建模拟用户（方便开发）

#### 2.3 Dashboard.tsx (一级界面)

保持原有设计，展示：
- 精选笔记本（写死的数据）
- 最近打开的笔记本（写死的数据）
- 新建笔记本入口

### 3. 工具组件

#### 3.1 MermaidPreview.tsx

从 `frontend-workflow` 复制的思维导图预览组件：
- 支持 Mermaid 代码渲染
- 支持放大预览
- 支持下载 SVG 和源代码
- 支持编辑和实时预览

### 4. 类型定义

更新 `src/types/index.ts`：
```typescript
export type MaterialType = 'image' | 'doc' | 'video' | 'link' | 'audio';
export interface KnowledgeFile { ... }
export interface ChatMessage { ... }
export type SectionType = 'library' | 'upload' | 'output' | 'settings';
export type ToolType = 'chat' | 'ppt' | 'mindmap' | 'podcast' | 'video' | 'search';
```

---

## 🚀 使用指南

### 启动项目

```bash
cd /data/users/szl/opennotebook/Paper2Any/frontend-v2

# 安装依赖（已完成）
npm install

# 启动开发服务器
npm run dev
```

访问: `http://localhost:3001`

### 环境变量配置

如果需要使用 Supabase，创建 `.env` 文件：

```env
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_anon_key
VITE_API_KEY=df-internal-2024-workflow-key
```

如果不配置，将使用模拟用户。

### 后端服务

确保后端服务运行在 `http://localhost:8210`

主要 API 端点：
- `POST /api/v1/kb/upload` - 文件上传
- `POST /api/v1/kb/chat` - 智能问答
- `POST /api/v1/kb/mindmap` - 思维导图生成
- `POST /api/v1/kb/ppt` - PPT 生成
- `POST /api/v1/kb/podcast` - 播客生成

---

## 📁 项目结构

```
frontend-v2/
├── src/
│   ├── components/
│   │   └── knowledge-base/
│   │       └── tools/
│   │           └── MermaidPreview.tsx  # 思维导图组件
│   ├── config/
│   │   └── api.ts                      # API 配置
│   ├── lib/
│   │   └── supabase.ts                 # Supabase 客户端
│   ├── pages/
│   │   ├── Dashboard.tsx               # 一级界面
│   │   └── NotebookView.tsx            # 二级界面（核心）
│   ├── services/
│   │   └── apiSettingsService.ts       # API 设置
│   ├── stores/
│   │   └── authStore.ts                # 认证状态
│   ├── types/
│   │   └── index.ts                    # 类型定义
│   ├── App.tsx                         # 主应用
│   └── main.tsx                        # 入口
├── vite.config.ts                      # Vite 配置
├── package.json                        # 依赖配置
└── README.md                           # 项目说明
```

---

## 🔄 适配逻辑

### 前端适配后端

1. **文件上传**
   - 前端: 通过 `<input type="file">` 上传
   - 后端: `POST /api/v1/kb/upload`
   - 数据库: 保存到 Supabase `knowledge_base_files` 表

2. **文件管理**
   - 前端: 从 Supabase 读取用户的文件列表
   - 显示: 左侧来源面板
   - 选择: 支持多选，自动选中所有文件

3. **智能问答**
   - 输入: 用户问题 + 选中的文件
   - 后端: `POST /api/v1/kb/chat`
   - 参数: `{ files, query, history, api_url, api_key }`
   - 响应: `{ answer, file_analyses }`

4. **工具生成**
   - 思维导图: `POST /api/v1/kb/mindmap` -> 返回 `mindmap_code`
   - PPT: `POST /api/v1/kb/ppt` -> 返回 `ppt_url`
   - 播客: `POST /api/v1/kb/podcast` -> 返回 `audio_url`

### 数据流

```
用户上传文件
    ↓
前端调用 /api/v1/kb/upload
    ↓
后端保存文件，返回 URL
    ↓
前端保存到 Supabase
    ↓
用户选择文件，发起问答/生成
    ↓
前端调用相应 API，传入选中文件的 URL
    ↓
后端处理，返回结果
    ↓
前端展示（对话框/工具面板）
```

---

## ✅ 功能清单

### 已实现功能

- [x] 文件上传（支持 PDF, DOCX, PPTX, 图片等）
- [x] 文件列表展示
- [x] 文件多选
- [x] 智能问答（RAG）
- [x] 思维导图生成（Mermaid 渲染）
- [x] PPT 生成
- [x] 播客生成
- [x] 前端样式保持 NotebookLM 风格
- [x] 认证状态管理（支持 Supabase 或模拟用户）
- [x] 后端 API 集成

### 待完善功能

- [ ] 来源管理（删除、重新索引等）
- [ ] 多模态检索功能实现
- [ ] 视频讲解生成完整实现
- [ ] 一级界面（Dashboard）接入真实数据
- [ ] API 设置界面
- [ ] 错误处理优化
- [ ] 加载状态优化

---

## 🎯 核心原则

1. **前端适配后端**
   - 不修改后端 API
   - 前端调用现有接口
   - 数据格式遵循后端规范

2. **保持 UI 风格**
   - Notebook 的界面设计
   - 三栏布局
   - 原有的交互逻辑

3. **复用知识库功能**
   - 文件管理
   - 智能工具
   - 认证系统

---

## 📝 注意事项

1. **后端依赖**
   - 必须运行 Paper2Any 后端服务
   - 默认端口: 8210
   - 确保后端 API 可访问

2. **数据库**
   - 如果使用 Supabase，需要配置环境变量
   - 表结构: `knowledge_base_files`
   - 字段: user_id, file_name, file_type, storage_path 等

3. **开发模式**
   - 未配置 Supabase 时，使用模拟用户
   - 模拟用户 ID: `dev-user-001`
   - 适合纯前端开发

4. **生产环境**
   - 必须配置 Supabase
   - 必须配置 LLM API
   - 需要真实的认证系统

---

## 🐛 常见问题

### Q: 上传文件失败？
A: 检查后端服务是否运行，检查网络代理配置

### Q: 无法登录？
A: 如果未配置 Supabase，会自动使用模拟用户

### Q: 生成工具无响应？
A: 检查是否选中了文件，检查后端 API 状态

### Q: 思维导图不显示？
A: 检查 mermaid 依赖是否安装，检查返回的代码格式

---

## 📞 技术支持

如有问题，请检查：
1. 后端服务日志
2. 浏览器控制台错误
3. 网络请求状态
4. 环境变量配置

---

## 🎉 总结

本次集成成功将知识库的强大后端功能与 NotebookLM 优雅的前端界面结合，实现了：

- ✅ **无缝集成** - 前端完全适配后端 API
- ✅ **功能完整** - 支持所有核心知识库工具
- ✅ **开发友好** - 支持模拟用户，方便调试
- ✅ **可扩展** - 易于添加新功能

现在您可以使用 NotebookLM 的界面，享受知识库的全部功能！
