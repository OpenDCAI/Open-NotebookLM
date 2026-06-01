import type { Locale } from './store';

const textMap: Record<string, string> = {
  '知识工作台': 'Knowledge Workspace',
  '管理你的知识库，随时进入工作区开始探索。': 'Manage your knowledge bases and start exploring whenever you are ready.',
  '退出登录': 'Sign out',
  '新建笔记本': 'New notebook',
  '工作区': 'Workspace',
  '选择一个笔记本继续工作': 'Select a notebook to continue',
  '搜索笔记本': 'Search notebooks',
  '还没有笔记本': 'No notebooks yet',
  '没有匹配结果': 'No matching results',
  '先创建一个笔记本，再进入 ThinkFlow 工作台。': 'Create a notebook first, then enter the ThinkFlow workspace.',
  '换个关键词试试，或者直接创建新的笔记本。': 'Try another keyword, or create a new notebook.',
  '未命名笔记本': 'Untitled notebook',
  '获取笔记本列表失败': 'Failed to load notebooks',
  '创建笔记本失败': 'Failed to create notebook',
  '知识库': 'Knowledge base',
  '点击进入，开始你的知识探索之旅。': 'Open it to start exploring your knowledge.',
  '打开笔记本': 'Open notebook',
  '工作区概览': 'Workspace overview',
  '知识空间': 'Knowledge spaces',
  '个工作区': 'workspaces',
  '模式': 'Mode',
  '云端同步': 'Cloud sync',
  '本地试用': 'Local trial',
  '核心能力': 'Core capability',
  '来源 · 对话 · 产出': 'Sources · Chat · Outputs',
  '完整知识工作闭环': 'A complete knowledge-work loop',
  '创建后会直接进入该笔记本的 ThinkFlow 工作台。': 'After creation, you will enter this notebook in ThinkFlow.',
  '输入笔记本名称': 'Notebook name',
  '取消': 'Cancel',
  '创建中...': 'Creating...',
  '创建并进入': 'Create and enter',
  '开启你的知识之旅': 'Start your knowledge journey',
  '在这里管理你的文档、生成洞见、创建多样化产出。': 'Manage documents, generate insights, and create rich outputs here.',
  '探索': 'Explore',
  '智能问答': 'Smart Q&A',
  '基于来源的深度 RAG 对话，精准引用原文': 'Source-grounded RAG chat with precise citations',
  '整理': 'Organize',
  '知识梳理': 'Knowledge synthesis',
  '沉淀对话、整理文档、构建专属知识底稿': 'Capture chats, organize documents, and build your knowledge draft',
  '产出': 'Outputs',
  '多样产出': 'Rich outputs',
  '一键生成 PPT、播客、导图、测验和报告': 'Generate slides, podcasts, mind maps, quizzes, and reports',
  'AI 全链路知识工作台': 'End-to-end AI knowledge workspace',
  '从来源导入、智能问答到多样产出，ThinkFlow 覆盖知识工作的完整闭环。': 'From source import and Q&A to rich outputs, ThinkFlow covers the full knowledge-work loop.',
  '创建你的账号': 'Create your account',
  '欢迎回来': 'Welcome back',
  '注册后即可进入统一的 ThinkFlow 工作台。': 'Register to enter the unified ThinkFlow workspace.',
  '登录后继续你的文档与产出工作流。': 'Sign in to continue your document and output workflow.',
  '登录': 'Sign in',
  '注册': 'Register',
  '邮箱': 'Email',
  '密码': 'Password',
  '确认密码': 'Confirm password',
  '请输入密码': 'Enter password',
  '至少 6 位': 'At least 6 characters',
  '再次输入密码': 'Enter password again',
  '登录中...': 'Signing in...',
  '验证码': 'Verification code',
  '输入邮件中的验证码': 'Enter the code from your email',
  '先填写上方信息再发送': 'Fill in the fields above before sending',
  '发送': 'Send',
  '新': 'New',
  '本轮': 'This round',
  '搜索': 'Search',
  '已发送': 'Sent',
  '验证码已发送，请查收邮件。': 'Verification code sent. Please check your email.',
  '没收到？重新发送': 'Did not receive it? Send again',
  '验证中...': 'Verifying...',
  '发送中...': 'Sending...',
  '完成验证': 'Complete verification',
  '以访客身份继续': 'Continue as guest',
  '请输入邮箱和密码。': 'Enter your email and password.',
  '请输入正确的邮箱地址。': 'Enter a valid email address.',
  '请完整填写邮箱和密码。': 'Fill in your email and password.',
  '两次输入的密码不一致。': 'The two passwords do not match.',
  '密码长度至少为 6 位。': 'Password must be at least 6 characters.',
  '请输入验证码。': 'Enter the verification code.',
  '缺少待验证邮箱。': 'Missing email to verify.',
  '认证未配置': 'Authentication is not configured',
  '登录失败': 'Sign-in failed',
  '注册失败': 'Registration failed',
  '验证失败': 'Verification failed',
  '重发失败': 'Resend failed',
  '历史': 'History',
  '素材': 'Sources',
  '当前来源': 'Current sources',
  '已选': 'Selected',
  'SelectedSources': 'selected sources',
  '个解析中': 'parsing',
  '刷新来源状态': 'Refresh source status',
  '正在加载素材...': 'Loading sources...',
  '暂无素材': 'No sources yet',
  '入库中…': 'Indexing...',
  '已入库': 'Indexed',
  '解析中…': 'Parsing...',
  '待入库': 'Not indexed',
  '重新入库': 'Re-index',
  '预览': 'Preview',
  '删除': 'Delete',
  '添加来源': 'Add source',
  '上传中...': 'Uploading...',
  '快速上传文件': 'Quick upload',
  '暂无产出': 'No outputs yet',
  '项': 'items',
  '当前查看': 'Viewing',
  '打开查看': 'Open',
  '测验结果': 'Quiz results',
  '这轮测验已经完成': 'This quiz is complete',
  '答对': 'Correct',
  '答错': 'Incorrect',
  '跳过': 'Skipped',
  '重新做一遍': 'Retry',
  '查看逐题复盘': 'Review each question',
  '逐题复盘': 'Question review',
  '检查你的答案与每题解析': 'Check your answers and explanations',
  '返回结果页': 'Back to results',
  '你的答案': 'Your answer',
  '本题已跳过': 'Skipped',
  '解析': 'Explanation',
  '依据': 'Evidence',
  '互动测验': 'Interactive quiz',
  '先作答，再查看结果与复盘': 'Answer first, then view results and review',
  '完成后给出结果页': 'Results appear after completion',
  '上一题': 'Previous',
  '下一题': 'Next',
  '完成测验': 'Finish quiz',
  '未生成题目': 'No question generated',
  '未提供选项内容': 'No option text provided',
  '思维导图预览': 'Mind map preview',
  '放大': 'Zoom in',
  '缩小': 'Zoom out',
  '复位': 'Reset',
  '查看图形': 'View diagram',
  '查看代码': 'View code',
  '下载 SVG': 'Download SVG',
  '下载代码': 'Download code',
  'Mermaid 代码:': 'Mermaid code:',
  '渲染失败': 'Render failed',
  '查看原始代码': 'View source code',
  '思维导图放大预览': 'Mind map zoom preview',
  '暂无可预览内容': 'Nothing to preview',
  '学习卡片': 'Flashcards',
  '逐张翻卡学习当前知识点': 'Flip cards to study the current knowledge points',
  '点击卡片查看答案': 'Click the card to view the answer',
  '填空卡': 'Fill-in card',
  '概念卡': 'Concept card',
  '问答卡': 'Q&A card',
  '未生成问题': 'No question generated',
  '点击翻到答案面': 'Click to flip to the answer',
  '答案面': 'Answer side',
  '答案': 'Answer',
  '未生成答案': 'No answer generated',
  '上一张': 'Previous card',
  '下一张': 'Next card',
  '结果为空': 'Empty result',
  '无数据返回': 'No data returned',
  '导出 CSV': 'Export CSV',
  '摘要': 'Summary',
  '梳理文档': 'Document',
  '大纲编排': 'Outline',
  '+ 新建': '+ New',
  '完成编辑': 'Done editing',
  '编辑摘要': 'Edit summary',
  '摘要名称由你决定，也可以先留空后再改': 'Name the summary now, or leave it blank and edit it later',
  '摘要不是默认生成的，它更像 AI 帮你记下来的阅读笔记。': 'Summaries are not generated by default. They are reading notes captured by AI.',
  '这里是 AI 笔记的可编辑区。': 'This is the editable AI notes area.',
  '保存中': 'Saving',
  '保存摘要': 'Save summary',
  '编辑全文': 'Edit full text',
  '这是只读的高权重上下文，不允许直接编辑；需要改动时请重新从对话沉淀。': 'This is read-only high-priority context. Capture it again from chat if it needs changes.',
  '正在准备并生成': 'Preparing and generating ',
  '从文档页点击一个产出按钮后，这里会直接显示当前结果工作台。': 'Click an output button from the document page to show the result workspace here.',
  '报告': 'Report',
  '导图': 'Mind map',
  '播客': 'Podcast',
  '卡片': 'Cards',
  '测验': 'Quiz',
  'PPT': 'PPT',
  '视频': 'Video',
  '来源': 'Sources',
  '对话': 'Chat',
  '文档': 'Document',
  '保存Document': 'Save document',
  '保存文档': 'Save document',
  '优先使用当前Document': 'Use the current document first',
  '优先使用当前梳理文档': 'Use the current document first',
  '如果Document为空，会先基于Current sources自动生成一份Sources梳理': 'If the document is empty, ThinkFlow will first generate a source synthesis from the current sources.',
  '如果文档为空，会先基于当前来源自动生成一份来源梳理': 'If the document is empty, ThinkFlow will first generate a source synthesis from the current sources.',
  '请先围绕左侧SelectedSources提问。Chat是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成Summary、Organize进Document。': 'Ask questions around the selected sources on the left first. Chat is the main flow; you can capture an answer, a Q&A pair, or multiple turns into Summary or organize it into Document.',
  '请先围绕左侧selected sources提问。Chat是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成Summary、Organize进Document。': 'Ask questions around the selected sources on the left first. Chat is the main flow; you can capture an answer, a Q&A pair, or multiple turns into Summary or organize it into Document.',
  '请先围绕左侧已选来源提问。对话是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成摘要、梳理进文档。': 'Ask questions around the selected sources on the left first. Chat is the main flow; you can capture an answer, a Q&A pair, or multiple turns into Summary or organize it into Document.',
  '这里是后续 PPT、Report和Mind map的主输入区，用来持续累积你确认过的正文内容，而不是临时聊天副本。': 'This is the main input area for later PPT, reports, and mind maps. It continuously accumulates confirmed body content, not temporary chat copies.',
  '这里是后续 PPT、报告和导图的主输入区，用来持续累积你确认过的正文内容，而不是临时聊天副本。': 'This is the main input area for later PPT, reports, and mind maps. It continuously accumulates confirmed body content, not temporary chat copies.',
  '来源是主输入；梳理文档用于沉淀结构化理解，也可以作为后续产出的增强上下文。': 'Sources are the primary input. Documents preserve structured understanding and can enhance later outputs.',
  '来源是主输入；当前梳理文档会作为可选增强上下文': 'Sources are the primary input. The current document acts as optional enhancement context.',
  '当前没有选择梳理文档，本次会直接基于来源和可选参考生成结果。': 'No document is selected for this run. ThinkFlow will generate the result directly from sources and any optional references.',
  '可追加、AI Organize、AI 融合，也可以手动编辑全文并回看History版本。': 'You can append, organize with AI, merge with AI, manually edit the full text, and review history versions.',
  '可追加、AI 整理、AI 融合，也可以手动编辑全文并回看历史版本。': 'You can append, organize with AI, merge with AI, manually edit the full text, and review history versions.',
  '右侧是你确认过的Document，会作为后续 PPT / Report / Mind map的直接输入。': 'The right side contains your confirmed document, used directly as input for later PPT, reports, and mind maps.',
  '右侧是你确认过的梳理文档，会作为后续 PPT / 报告 / 导图的直接输入。': 'The right side contains your confirmed document, used directly as input for later PPT, reports, and mind maps.',
  '先在中间持续Chat，再把真正有价值的段落或回答推送到这里。': 'Keep chatting in the center first, then push truly useful paragraphs or answers here.',
  '先在中间持续对话，再把真正有价值的段落或回答推送到这里。': 'Keep chatting in the center first, then push truly useful paragraphs or answers here.',
  '沉淀到工作区': 'Capture to workspace',
  '把当前对话整理到右侧工作区，后续可以继续复用。': 'Organize the current chat into the right workspace for reuse.',
  '沉淀目标': 'Capture target',
  '沉淀关键理解与结论': 'Capture key understanding and conclusions',
  '整理成持续演进的主文档': 'Organize into the evolving main document',
  '作为后续输出的重要约束和方向': 'Use as important constraints and direction for outputs',
  '目标文档': 'Target document',
  '+ 新建文档': '+ New document',
  '命名方式': 'Naming mode',
  'AI 命名': 'AI naming',
  '自动生成一个简洁可读的标题': 'Automatically generate a concise readable title',
  '手动填写': 'Manual name',
  '你可以直接定标题，不填时也会回退为 AI 命名': 'You can set a title directly. Empty titles fall back to AI naming.',
  '新建名称': 'New name',
  '可手动填写；留空则仍会回退为 AI 命名': 'Optional manual name. Empty falls back to AI naming.',
  '当前将由 AI 自动命名，你确认沉淀后会直接生成。': 'AI will name it automatically after you confirm capture.',
  '处理方式': 'Processing mode',
  '直接追加': 'Append directly',
  '原文放入文档末尾': 'Append original text to the document',
  'AI整理后追加': 'Organize with AI, then append',
  '整理成当前提纲': 'Organize into the current outline',
  'AI融合到已有内容': 'AI merge into existing content',
  '融入现有段落': 'Merge into existing sections',
  '推荐': 'Recommended',
  '补充指示（可选）': 'Extra instruction (optional)',
  '本次沉淀来源': 'Capture source',
  '确认沉淀': 'Confirm capture',
  '处理中...': 'Processing...',
  '历史对话': 'Chat history',
  '这里展示当前笔记本下已记录的对话内容。': 'Recorded chat messages for this notebook appear here.',
  '正在加载历史对话...': 'Loading chat history...',
  '当前还没有可查看的历史对话。': 'No chat history yet.',
  '来源预览': 'Source preview',
  '正在加载来源内容...': 'Loading source content...',
  '关闭': 'Close',
  '确认本次 PPT 来源': 'Confirm sources for this PPT',
  '确认后会直接开始生成，并锁定这一版结果的来源快照。之后若要换输入范围，请重新生成一版。': 'Generation starts after confirmation and locks this source snapshot. Generate a new version to change inputs.',
  '来源文件': 'Source files',
  '未选择来源文件': 'No source files selected',
  '梳理文档 / 参考文档': 'Documents / references',
  '未选择梳理文档': 'No document selected',
  '正在整理来源，请稍候。': 'Preparing sources. Please wait.',
  '来源解析失败，请关闭后重试。': 'Failed to parse sources. Close and retry.',
  '确认并生成大纲': 'Confirm and generate outline',
  '确认并开始生成': 'Confirm and generate',
  '整理来源中...': 'Preparing sources...',
  '返回对话': 'Back to chat',
  '沉浸编辑': 'Immersive editing',
  '退出沉浸': 'Exit immersive',
  '本次 PPT 来源已锁定': 'Sources for this PPT are locked',
  '本次产出来源已锁定': 'Sources for this output are locked',
  '未选择': 'Not selected',
  '主文档': 'Main document',
  '未设置': 'Not set',
  '大纲确认': 'Outline review',
  '逐页生成确认': 'Page review',
  '生成结果': 'Generated result',
  '返回文档': 'Back to document',
  '保存大纲': 'Save outline',
  '确认大纲，进入逐页生成': 'Confirm outline and generate pages',
  '清空': 'Clear',
  '提示词 AI 修改': 'Revise with AI prompt',
  'AI 调整中...': 'AI revising...',
  '当前页预览': 'Current page preview',
  '单页编辑': 'Page editing',
  '页面标题': 'Page title',
  '每行一个要点': 'One bullet per line',
  '编辑中': 'Editing',
  '查看': 'View',
  '+ 添加页面': '+ Add page',
  '已确认大纲': 'Confirmed outline',
  '当前大纲只读': 'Current outline is read-only',
  '收起': 'Collapse',
  '查看已确认大纲': 'View confirmed outline',
  '收起已确认大纲': 'Collapse confirmed outline',
  '生成页面结果中...': 'Generating page results...',
  '重新生成每页结果': 'Regenerate each page',
  '生成每页结果': 'Generate each page',
  '页面规模': 'Page count',
  '确认进度': 'Review progress',
  '已开启': 'Enabled',
  '已关闭': 'Disabled',
  '来源素材与自动插图 / 生图': 'Source assets and generated illustrations',
  '单页修改': 'Single-page revision',
  '上一页': 'Previous page',
  '下一页': 'Next page',
  '当前页重生成中...': 'Regenerating current page...',
  '按提示重做当前页': 'Regenerate current page from prompt',
  '确认中...': 'Confirming...',
  '确认当前页并完成': 'Confirm current page and finish',
  '确认当前页并继续': 'Confirm current page and continue',
  '打开 PDF': 'Open PDF',
  '下载 PPTX': 'Download PPTX',
  '回流来源': 'Send back to sources',
  '摘要区说明': 'Summary panel guide',
  '梳理文档说明': 'Document panel guide',
};

const reverseTextMap = Object.fromEntries(Object.entries(textMap).map(([zh, en]) => [en, zh]));

const dynamicRules = [
  {
    zh: /^验证码已发送到 (.+)，请查收。$/,
    en: (match: RegExpMatchArray) => `Verification code sent to ${match[1]}. Please check your email.`,
    enPattern: /^Verification code sent to (.+)\. Please check your email\.$/,
    zhBack: (match: RegExpMatchArray) => `验证码已发送到 ${match[1]}，请查收。`,
  },
  {
    zh: /^已重新发送到 (.+)。$/,
    en: (match: RegExpMatchArray) => `Sent again to ${match[1]}.`,
    enPattern: /^Sent again to (.+)\.$/,
    zhBack: (match: RegExpMatchArray) => `已重新发送到 ${match[1]}。`,
  },
  {
    zh: /^(\d+)s 后重发$/,
    en: (match: RegExpMatchArray) => `Resend in ${match[1]}s`,
    enPattern: /^Resend in (\d+)s$/,
    zhBack: (match: RegExpMatchArray) => `${match[1]}s 后重发`,
  },
  {
    zh: /^第 (\d+) 题$/,
    en: (match: RegExpMatchArray) => `Question ${match[1]}`,
    enPattern: /^Question (\d+)$/,
    zhBack: (match: RegExpMatchArray) => `第 ${match[1]} 题`,
  },
  {
    zh: /^第 (\d+) 页$/,
    en: (match: RegExpMatchArray) => `Page ${match[1]}`,
    enPattern: /^Page (\d+)$/,
    zhBack: (match: RegExpMatchArray) => `第 ${match[1]} 页`,
  },
  {
    zh: /^页面 (\d+)$/,
    en: (match: RegExpMatchArray) => `Page ${match[1]}`,
    enPattern: /^Page (\d+)$/,
    zhBack: (match: RegExpMatchArray) => `页面 ${match[1]}`,
  },
  {
    zh: /^来源 (\d+)$/,
    en: (match: RegExpMatchArray) => `Sources ${match[1]}`,
    enPattern: /^Sources (\d+)$/,
    zhBack: (match: RegExpMatchArray) => `来源 ${match[1]}`,
  },
  {
    zh: /^新(Chat.*)$/,
    en: (match: RegExpMatchArray) => `New ${match[1]}`,
    enPattern: /^New (Chat.*)$/,
    zhBack: (match: RegExpMatchArray) => `新${match[1]}`,
  },
];

const phraseFallbacks: Array<[RegExp, string]> = [
  [
    /请先围绕左侧.*?提问。.*?沉淀成.*?文档。/,
    'Ask questions around the selected sources on the left first. Chat is the main flow; you can capture useful answers into Summary or organize it into Document.',
  ],
];

const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'alt'];

function translateValue(value: string, locale: Locale): string {
  const trimmed = value.trim();
  if (!trimmed) return value;

  const exact = locale === 'en' ? textMap[trimmed] : reverseTextMap[trimmed];
  if (exact) return value.replace(trimmed, exact);

  for (const rule of dynamicRules) {
    const match = trimmed.match(locale === 'en' ? rule.zh : rule.enPattern);
    if (match) {
      return value.replace(trimmed, locale === 'en' ? rule.en(match) : rule.zhBack(match));
    }
  }

  if (locale === 'en') {
    let next = value;
    for (const [pattern, replacement] of phraseFallbacks) {
      next = next.replace(pattern, replacement);
    }
    for (const [zh, en] of Object.entries(textMap)) {
      if (zh.length > 1 && next.includes(zh)) {
        next = next.split(zh).join(en);
      }
    }
    return next;
  }

  let next = value;
  for (const [en, zh] of Object.entries(reverseTextMap)) {
    if (en.length > 1 && next.includes(en)) {
      next = next.split(en).join(zh);
    }
  }
  return next;
}

function shouldSkipElement(element: Element): boolean {
  return ['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE'].includes(element.tagName);
}

function translateTextNode(node: Node, locale: Locale) {
  if (node.nodeType !== Node.TEXT_NODE || !node.textContent) return;
  const parent = node.parentElement;
  if (!parent || shouldSkipElement(parent)) return;
  node.textContent = translateValue(node.textContent, locale);
}

function translateElementAttributes(element: Element, locale: Locale) {
  if (shouldSkipElement(element)) return;
  for (const attribute of ATTRIBUTES) {
    const value = element.getAttribute(attribute);
    if (value) {
      element.setAttribute(attribute, translateValue(value, locale));
    }
  }
}

function translateSubtree(root: ParentNode, locale: Locale) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let current = walker.nextNode();
  while (current) {
    translateTextNode(current, locale);
    current = walker.nextNode();
  }

  if (root instanceof Element || root instanceof Document || root instanceof DocumentFragment) {
    const elements = root instanceof Element ? [root, ...root.querySelectorAll('*')] : Array.from(root.querySelectorAll('*'));
    for (const element of elements) {
      translateElementAttributes(element, locale);
    }
  }
}

let observer: MutationObserver | null = null;
let activeLocale: Locale = 'zh';
let translating = false;
let pendingTranslate: number | null = null;

function scheduleDomTranslation(locale: Locale) {
  activeLocale = locale;
  if (pendingTranslate !== null) {
    window.clearTimeout(pendingTranslate);
  }
  pendingTranslate = window.setTimeout(() => {
    pendingTranslate = null;
    translateDom(activeLocale);
  }, 40);
}

export function translateDom(locale: Locale) {
  activeLocale = locale;
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  document.title = 'ThinkFlow';

  if (translating) return;
  translating = true;
  window.requestAnimationFrame(() => {
    observer?.disconnect();
    translateSubtree(document.body, activeLocale);
    observer?.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRIBUTES,
    });
    translating = false;
  });
}

export function installDomTranslator(locale: Locale) {
  activeLocale = locale;
  translateDom(locale);

  if (observer) return;
  observer = new MutationObserver((mutations) => {
    if (translating) return;
    if (mutations.length > 0) {
      scheduleDomTranslation(activeLocale);
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTES,
  });
}
