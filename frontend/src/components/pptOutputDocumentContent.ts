type OutlineSectionLike = {
  pageNum?: number;
  title?: string;
  summary?: string;
  bullets?: string[];
  layout_description?: string;
  key_points?: string[];
  asset_ref?: string | null;
};

type PptOutputInfoLike = {
  title?: string;
  page_count?: number;
  audience?: string;
  source_names?: string[];
  bound_document_titles?: string[];
  stage_label?: string;
};

type PptStyleInfoLike = {
  preset?: string;
  label?: string;
  tone?: string;
  visual_style?: string;
  audience_assumption?: string;
  supplement_prompt?: string[];
};

type PptOutputLike = {
  title?: string;
  target_type?: string;
  page_count?: number;
  outline?: OutlineSectionLike[];
  source_names?: string[];
  bound_document_titles?: string[];
  guidance_snapshot_text?: string;
  output_info?: PptOutputInfoLike;
  style_info?: PptStyleInfoLike;
  outline_chat_draft_outline?: OutlineSectionLike[];
  outline_chat_draft_output_info?: PptOutputInfoLike;
  outline_chat_draft_style_info?: PptStyleInfoLike;
};

export function buildPptOutputDocumentContent(output: PptOutputLike): string {
  const outline = Array.isArray(output.outline) ? output.outline : [];
  const outputInfo = output.output_info || {};
  const styleInfo = output.style_info || {};
  const sourceNames = (outputInfo.source_names || output.source_names || []).filter(Boolean);
  const boundTitles = (outputInfo.bound_document_titles || output.bound_document_titles || []).filter(Boolean);
  const guidanceText = String(output.guidance_snapshot_text || '').trim();
  const supplementPrompt = Array.isArray(styleInfo.supplement_prompt)
    ? styleInfo.supplement_prompt.filter(Boolean)
    : [];
  const lines = [
    `# ${outputInfo.title || output.title || 'PPT 产出文档'}`,
    '',
    '## 产出信息',
    '',
    `- 产出类型：PPT`,
    `- 产出标题：${outputInfo.title || output.title || 'PPT 产出文档'}`,
    `- 目标页数：${outputInfo.page_count || output.page_count || outline.length || 10} 页`,
    outputInfo.audience ? `- 面向对象：${outputInfo.audience}` : '- 面向对象：未指定',
    sourceNames.length > 0 ? `- 来源文件：${sourceNames.join('、')}` : '- 来源文件：未选择',
    boundTitles.length > 0 ? `- 参考文档：${boundTitles.join('、')}` : '- 参考文档：未选择',
    `- 生成状态：${outputInfo.stage_label || '大纲讨论中'}`,
    '',
    '## 风格信息',
    '',
    `- 风格类型：${styleInfo.label || styleInfo.preset || '自定义'}`,
    `- 表达语气：${styleInfo.tone || '清晰、准确、贴合用户补充要求'}`,
    `- 视觉倾向：${styleInfo.visual_style || '结构清楚，视觉表达服务内容重点'}`,
    styleInfo.audience_assumption ? `- 受众假设：${styleInfo.audience_assumption}` : '- 受众假设：根据产出信息和用户补充要求确定',
    '- 补充提示词：',
    ...(supplementPrompt.length > 0
      ? supplementPrompt.map((item) => `  - ${item}`)
      : [guidanceText ? `  - ${guidanceText}` : '  - 无']),
    '',
    '## PPT 大纲',
    '',
  ];
  if (outline.length === 0) {
    lines.push('[待补充]');
    return lines.join('\n');
  }
  outline.forEach((slide, index) => {
    const pageNum = slide.pageNum || index + 1;
    lines.push(`### 第 ${pageNum} 页：${slide.title || `页面 ${pageNum}`}`);
    if (slide.layout_description || slide.summary) {
      lines.push('', '**布局说明**', '', slide.layout_description || slide.summary || '');
    }
    const points = slide.key_points || slide.bullets || [];
    if (points.length > 0) {
      lines.push('', '**页面要点**', '');
      points.forEach((point) => lines.push(`- ${point}`));
    }
    if (slide.asset_ref) {
      lines.push('', '**素材建议**', '', `\`${slide.asset_ref}\``);
    }
    lines.push('', '---', '');
  });
  return lines.join('\n').trim();
}
