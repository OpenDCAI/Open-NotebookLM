import { describe, expect, it } from 'vitest';
import { buildPptOutputDocumentContent } from '../pptOutputDocumentContent';

describe('buildPptOutputDocumentContent', () => {
  it('uses only the applied PPT outline and style while a draft candidate is pending', () => {
    const content = buildPptOutputDocumentContent({
      title: 'PPT 产出文档',
      page_count: 2,
      outline: [
        {
          pageNum: 1,
          title: '正式标题',
          layout_description: '正式布局',
          key_points: ['正式要点'],
        },
      ],
      output_info: {
        title: '正式产出标题',
        page_count: 1,
        stage_label: '大纲讨论中',
      },
      style_info: {
        label: '简洁干净',
        tone: '正式语气',
        visual_style: '正式视觉',
        supplement_prompt: ['正式补充'],
      },
      outline_chat_draft_outline: [
        {
          pageNum: 1,
          title: '候选标题',
          layout_description: '候选布局',
          key_points: ['候选要点'],
        },
      ],
      outline_chat_draft_output_info: {
        title: '候选产出标题',
        page_count: 9,
      },
      outline_chat_draft_style_info: {
        label: '商务风格',
        tone: '候选语气',
        visual_style: '候选视觉',
        supplement_prompt: ['候选补充'],
      },
    });

    expect(content).toContain('正式产出标题');
    expect(content).toContain('正式标题');
    expect(content).toContain('正式布局');
    expect(content).toContain('正式要点');
    expect(content).toContain('简洁干净');
    expect(content).not.toContain('候选产出标题');
    expect(content).not.toContain('候选标题');
    expect(content).not.toContain('候选布局');
    expect(content).not.toContain('候选要点');
    expect(content).not.toContain('商务风格');
  });
});
