# ThinkFlow 闪卡功能升级设计

> 当前状态：本文末尾已按 2026-04-21 实际落地版本补充“当前落地设计”。补充内容覆盖生成配置、真实来源路径、`generation_input.md` 纠偏、引用预览、回流来源、翻卡动效与可读性修复。

## 1. 背景与目标

当前 ThinkFlow 闪卡存在三个明确问题：

1. 闪卡答案里可能出现来源编号引用，如 `[1]`、`[2]`，但当前无法点击，也无法简略查看对应知识来源。
2. 闪卡生成配置能力不足，缺少难度等级、卡片数量、主题、测试内容等控制项。
3. 闪卡展示风格偏朴素，不符合“闪卡”这种偏记忆强化工具的产品气质。

本次升级目标：

- 让闪卡答案中的来源编号可点击，并支持卡片内简版来源预览与跳转完整来源。
- 为闪卡增加生成配置，且将配置保存到这组闪卡结果中。
- 对闪卡进行更有表现力的视觉升级。
- 中文前端与英文前端同步支持，不允许只改单端。

## 2. 用户确认的行为约束

### 2.1 来源引用

- 答案中的 `[1]`、`[2]`、`[3]` 等编号都代表来源引用，不限于 `[1]`。
- 一张卡片中若存在多个引用，例如 `[1][2]`，这些引用需要分别可点。
- 点击某个引用后：
  - 先在卡片背面展开当前引用的简版来源预览。
  - 如果该卡还有其他引用，用户可以在预览区中切换到其他引用。
  - 当前预览区提供“打开完整来源”按钮，复用现有来源详情能力。

### 2.2 生成配置

- 难度等级为单选：
  - `基础`
  - `进阶`
  - `挑战`
- 用户选择某一难度后，生成整组同一难度的闪卡。
- 卡片数量允许用户设置。
- 如果用户不设置卡片数量，则沿用当前默认生成逻辑。
- 主题、测试内容为自由文本输入。
- 主题、测试内容使用“自由文本 + 示例占位提示”。
- 这些生成配置需要保存到该组闪卡结果中。
- 重新打开该组闪卡时，用户可以看到当时的生成条件。
- 但这些值不作为下一次生成的默认值。

### 2.3 视觉风格

- 闪卡需要更炫酷、更有记忆工具感。
- 保持翻卡交互，但视觉层次、动画、难度差异需要增强。

## 3. 现状分析

### 3.1 后端数据结构现状

当前闪卡 schema 定义见：

- `fastapi_app/schemas.py`

现有 `Flashcard` 仅包含：

- `question`
- `answer`
- `difficulty`
- `source_file`
- `source_excerpt`
- `tags`

问题：

- 没有显式保存卡片级引用映射，无法稳定支持 `[1][2]` 点击。
- 没有保存整组闪卡的生成配置。

### 3.2 中文前端现状

当前中文前端闪卡组件见：

- `frontend_zh/src/components/ThinkFlowFlashcardStudy.tsx`
- `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- `frontend_zh/src/components/ThinkFlowWorkspace.css`

问题：

- 背面答案是普通文本，没有 citation 解析。
- 只有 `source_file` / `source_excerpt` 的静态显示，没有“多引用 -> 多来源预览”的交互层。
- 当前卡片已有翻转结构，但视觉表达仍偏基础。

### 3.3 英文前端现状

当前英文前端闪卡链路见：

- `frontend_en/src/pages/NotebookView.tsx`
- `frontend_en/src/components/flashcards/FlashcardViewer.tsx`

问题：

- 英文前端与中文前端并非同一套组件，需要同步改造。
- 当前英文闪卡也没有 citation 点击能力。
- 当前英文闪卡配置能力与本次需求不匹配。

## 4. 设计方案

### 4.1 总体方案

采用“前后端一起补齐元数据”的方案，而不是仅做前端补丁。

原因：

- 闪卡历史记录需要可复现。
- 同一张卡片可能有多个引用，必须保存稳定映射。
- 生成条件需要跟随这组闪卡一起持久化。
- 中英前端都需要消费同一套结构化数据。

### 4.2 后端结构扩展

#### 4.2.1 请求结构扩展

扩展闪卡生成请求：

- `difficulty_level: Optional[str]`
- `card_count: Optional[int]`
- `topic: Optional[str]`
- `test_focus: Optional[str]`

说明：

- `difficulty_level` 取值限定为：
  - `basic`
  - `intermediate`
  - `advanced`
- 前端展示使用中文文案，但后端内部建议使用稳定英文枚举。
- `card_count` 若为空，则走当前默认逻辑。
- `topic`、`test_focus` 可为空。

#### 4.2.2 闪卡结果结构扩展

新增卡片级引用结构：

- `citations: List[FlashcardCitation]`

其中每个 citation 建议包含：

- `source_number`
- `file_name`
- `file_path`
- `preview`
- `chunk_index`

新增整组配置结构：

- `generation_config: FlashcardGenerationConfig`

建议字段：

- `difficulty_level`
- `card_count`
- `topic`
- `test_focus`
- `language`
- `generated_at`

#### 4.2.3 兼容策略

旧闪卡数据兼容原则：

- 没有 `generation_config` 时，前端不显示“本组生成条件”。
- 没有 `citations` 时，前端不把 `[1]` 渲染成可点击交互。
- 老字段 `source_file` / `source_excerpt` 保留，作为兼容性兜底展示。

### 4.3 闪卡生成逻辑

闪卡生成链路在后端应新增以下能力：

- 将 `difficulty_level`、`topic`、`test_focus` 进入 prompt。
- 将 `card_count` 显式传递给生成逻辑。
- 生成结果中：
  - `answer` 保留 `[1][2]` 这种文本编号。
  - 同时结构化保存 `citations`，供前端渲染点击逻辑。

引用映射来源应优先复用现有知识问答链路中的来源编号语义，而不是由前端自行猜测。

### 4.4 中文前端交互设计

#### 4.4.1 生成前配置区

在当前闪卡生成入口附近增加配置区，字段如下：

- 难度等级：单选
- 卡片数量：数字输入
- 主题：自由文本输入，带示例占位提示
- 测试内容：自由文本输入，带示例占位提示

示例占位提示：

- 主题：`例如：Transformer 结构、实验结果对比、核心术语`
- 测试内容：`例如：只考概念理解、偏实验结论、重点记忆公式`

交互规则：

- 不填写卡片数量时，后端走默认值。
- 不填写主题或测试内容时，不额外注入限制。

#### 4.4.2 闪卡展示区

卡片正面：

- 问题
- 难度标识
- 卡片类型

卡片背面：

- 答案
- 可点击来源引用
- 来源预览区
- 标签区

#### 4.4.3 来源引用交互

答案中的 `[1]`、`[2]` 等标记将被解析为 citation token。

行为：

- 点击某个 token 后，背面展开来源预览区。
- 默认展示当前被点击引用的预览。
- 如果这张卡还有其他引用，在预览区顶部显示可切换引用标签。
- 每个引用预览区显示：
  - 来源编号
  - 文件名
  - 片段预览
  - “打开完整来源”按钮

“打开完整来源”行为：

- 复用现有来源详情打开逻辑。
- 若已存在来源详情弹层或侧栏能力，则直接复用，不新增第二套来源查看器。

#### 4.4.4 历史闪卡

重新打开一组闪卡时：

- 在闪卡视图顶部展示“本组生成条件”。
- 包括：
  - 难度
  - 卡片数量
  - 主题
  - 测试内容
  - 生成时间

该信息只展示，不回填到新建闪卡配置表单中。

### 4.5 英文前端同步设计

英文前端同步改造原则：

- 与中文前端能力对齐
- 交互一致
- 仅文案英文化，不做双轨功能差异

需要同步的能力：

- 闪卡生成配置区
- 历史闪卡生成条件展示
- citation 点击与简版来源预览
- 打开完整来源按钮
- 更强的翻卡视觉表现

### 4.6 视觉升级方案

#### 4.6.1 视觉方向

保持翻卡核心模式，但增强以下元素：

- 3D 翻转深度
- 卡面渐变与光泽层
- 边缘高光与更明显阴影
- 难度等级的视觉区分
- 来源预览区的轻量展开动画

#### 4.6.2 难度视觉映射

- `基础`
  - 明亮、清晰、轻压力
- `进阶`
  - 对比更强、层次更深
- `挑战`
  - 更锐利、更深色、更强聚焦

#### 4.6.3 动效边界

动效原则：

- 有记忆点，但不影响连续刷卡效率
- 不做重型粒子或过度动画
- 确保移动端和桌面端都能稳定运行

## 5. 文件级改动范围

### 5.1 后端

- `fastapi_app/schemas.py`
- `fastapi_app/services/output_v2_service.py`
- 闪卡生成相关 service / workflow 实现文件

### 5.2 中文前端

- `frontend_zh/src/components/ThinkFlowWorkspace.tsx`
- `frontend_zh/src/components/ThinkFlowFlashcardStudy.tsx`
- `frontend_zh/src/components/ThinkFlowWorkspace.css`

### 5.3 英文前端

- `frontend_en/src/pages/NotebookView.tsx`
- `frontend_en/src/components/flashcards/FlashcardViewer.tsx`
- 如有必要，同步英文侧闪卡生成入口组件

## 6. 验证方案

至少验证以下场景：

1. 新生成一组闪卡时，四个生成配置字段都能正确提交。
2. 不填写卡片数量时，仍按默认逻辑生成。
3. 单卡包含多个引用时，例如 `[1][2]`，两个编号都能点击。
4. 点击某个引用后，先展开当前预览，再能切换其他引用。
5. “打开完整来源”可跳转到现有来源详情。
6. 重新打开同一组闪卡时，能够看到保存下来的生成条件。
7. 老闪卡数据仍可正常打开，不因缺少 `generation_config` / `citations` 报错。
8. 中文前端与英文前端功能一致。

## 7. 风险与注意事项

- 闪卡引用 `[1]` 的点击能力不能仅靠答案字符串猜测，必须以结构化 `citations` 为准。
- 中英文前端必须同步修改，避免功能漂移。
- 历史兼容不能破坏旧闪卡读取。
- 本次需求只针对闪卡，不顺手重构 quiz 全链路。

## 8. 当前落地设计（2026-04-21）

本节记录当前已经落地并经过多轮修正后的完整设计。若前文与本节有差异，以本节为准。

### 8.1 生成前自选配置

闪卡在“确认本次闪卡来源”弹窗中提供生成前配置，不再直接使用固定默认值。

配置项：

- 难度等级：单选，取值为 `basic` / `intermediate` / `advanced`，中文显示为“基础 / 进阶 / 挑战”。
- 卡片数量：数字输入，范围在前端限制为 1-50；为空时后端沿用默认逻辑。
- 主题：自由文本输入，用于限定生成主题，例如“Transformer 结构、实验结果对比、核心术语”。
- 测试内容：自由文本输入，用于限定考察重点，例如“只考概念理解、偏实验结论、重点记忆公式”。

行为规则：

- 配置在确认弹窗内可编辑，点击“确认并开始生成”时随 `flashcard_config` 提交。
- 配置会保存到本组闪卡结果的 `generation_config` / output 的 `flashcard_config`。
- 重新打开历史闪卡时，顶部展示“本组生成条件”。
- 历史条件只展示，不回填下一次生成表单。
- 成功开始生成后，前端重置本次草稿配置，避免污染下一次生成。

### 8.2 后端数据结构

闪卡卡片结构包含：

- `question`
- `answer`
- `type`
- `difficulty`
- `source_file`
- `source_excerpt`
- `tags`
- `citations`
- `created_at`

`citations` 是卡片级结构化引用数组，每项包含：

- `source_number`
- `file_name`
- `file_path`
- `preview`
- `chunk_index`

整组生成配置结构为 `FlashcardGenerationConfig`：

- `difficulty_level`
- `card_count`
- `topic`
- `test_focus`
- `language`
- `generated_at`

### 8.3 outputs-v2 真实来源策略

outputs-v2 生成闪卡时会先创建聚合输入文件 `generation_input.md`。该文件只作为 LLM 的综合上下文，不应作为用户可见来源。

真实来源策略：

- output 创建时保存真实来源快照：
  - `source_paths`
  - `source_names`
- 生成闪卡时，`file_paths=[generation_input.md]` 继续用于提取综合文本。
- 同时额外传入：
  - `citation_source_paths=item.source_paths`
  - `citation_source_names=item.source_names`
- 后端使用 `citation_source_paths/source_names` 构造可见 citation 映射。
- 如果真实 PDF 路径解析失败，也不能回退显示 `generation_input.md`；至少保留真实 PDF 文件名。
- 前端展示层额外做历史兼容：如果旧结果里 `source_file` 或 `citations[].file_name/file_path` 包含 `generation_input.md`，会按 `source_number` 使用 `activeOutput.source_names/source_paths` 替换展示。

示例：

- `source_names[0] = 2025.findings-emnlp.342.pdf`
- `source_names[1] = 2601.22139v1.pdf`
- 答案中的 `[1]` 展示为第一个 PDF。
- 答案中的 `[2]` 展示为第二个 PDF。

### 8.4 引用交互

答案中的 `[1]`、`[2]` 等编号会被解析成可点击 citation token。

交互规则：

- 点击编号后，在卡片背面展开来源预览区。
- 一张卡片有多个引用时，预览区顶部显示引用切换 tabs。
- 每个引用预览区展示：
  - 来源编号
  - 文件名
  - 片段预览
  - chunk 信息（如果存在）
- “打开完整来源”按钮只在 citation 具备可定位来源文件时展示。
- 如果 citation 只有 preview、无法定位完整文件，则不展示“打开完整来源”，避免点开后看到重复内容。
- 如果按钮存在但最终匹配不到左侧文件，前端提示：“没有找到可打开的完整来源文件，当前仅能查看卡片内来源片段。”

完整来源匹配规则：

- `filePath` 与左侧来源 URL 完全相等。
- 左侧来源 URL 以后缀形式匹配 `filePath`。
- `filePath` 以后缀形式匹配左侧来源 URL。
- `decodeURIComponent` 后相等。
- `fileName` 与左侧来源名称相等。

### 8.5 视觉与动效

闪卡保留正反面翻卡交互，并增强视觉表现。

整体卡面：

- 3D perspective 翻转。
- 渐变背景。
- radial glow。
- 流光 sheen。
- scan 光带。
- hover 轻微浮起与 3D 倾斜。

难度视觉：

- 基础：浅蓝、清晰、轻压力。
- 进阶：浅紫层次，答案框使用高对比深色文字。
- 挑战：深色卡面，答案框、依据框、引用框使用深色玻璃态背景与浅色文字。

翻转稳定性：

- 未激活 face 设置 `opacity: 0`。
- 未激活 face 设置 `pointer-events: none`。
- 使用 `backface-visibility` 与 `-webkit-backface-visibility`。
- 使用 `z-index` 保证只有当前面可见可交互。
- 修复过“卡片未翻转时，鼠标移到底部会出现镜像来源框”的问题。

可读性要求：

- 答案文本与答案框背景必须有明确对比。
- 深色难度不能出现白字白底。
- 进阶卡片不能出现浅字浅底。

### 8.6 回流来源

“回流来源”用于将当前产出重新导入为知识来源，供后续继续复用。

规则：

- 有现成产物文件时，优先导入现有文件。
- 闪卡和测验这类结构化 JSON 结果如果没有可导入文件，后端生成 Markdown 后导入。
- 闪卡回流 Markdown 包含：
  - 标题
  - 生成条件
  - 卡片问题
  - 卡片答案
  - 难度
  - 来源文件
  - 来源摘录

### 8.7 主要文件职责

后端：

- `fastapi_app/schemas.py`：定义闪卡、引用、生成配置 schema。
- `fastapi_app/services/flashcard_service.py`：构造 prompt、解析 LLM JSON、生成结构化 citations。
- `fastapi_app/routers/kb.py`：`/generate-flashcards` 接收生成配置和真实 citation 来源参数。
- `fastapi_app/services/output_v2_service.py`：保存 `flashcard_config`，传递真实 `source_paths/source_names`，支持闪卡/测验回流来源。

中文前端：

- `frontend_zh/src/components/ThinkFlowWorkspace.tsx`：
  - 管理生成前配置草稿。
  - 提交 `flashcard_config`。
  - 解析闪卡结果。
  - 对 `generation_input.md` 做来源显示纠偏。
  - 打开完整来源或显示错误提示。
- `frontend_zh/src/components/ThinkFlowFlashcardStudy.tsx`：
  - 展示翻卡学习 UI。
  - 渲染 citation token。
  - 展示 citation tabs 与来源片段。
  - 按条件展示“打开完整来源”按钮。
- `frontend_zh/src/components/ThinkFlowWorkspace.css`：
  - 卡片渐变、动效、翻面层级。
  - 三种难度视觉主题。
  - 答案区、来源区可读性。

英文前端：

- `frontend_en/src/components/flashcards/FlashcardViewer.tsx`
- `frontend_en/src/pages/NotebookView.tsx`

### 8.8 当前验证清单

需要持续验证：

1. 生成前可编辑难度、卡片数量、主题、测试内容。
2. 不填数量时仍按默认逻辑生成。
3. 历史闪卡顶部能展示本组生成条件。
4. `[1]`、`[2]` 可点击并展开来源预览。
5. 多引用卡片可在 tabs 间切换。
6. 选择两个 PDF 生成闪卡时，来源显示真实 PDF 文件名，不显示 `generation_input.md`。
7. 旧结果里写死的 `generation_input.md` 能被前端纠偏展示。
8. 只有 preview 无真实文件时，不显示“打开完整来源”按钮。
9. 有真实文件时，“打开完整来源”能打开现有来源详情。
10. “回流来源”能把闪卡结果导入为 Markdown 来源。
11. 翻转前背面不会漏出镜像内容。
12. 进阶/挑战卡片答案面文字清晰可读。
