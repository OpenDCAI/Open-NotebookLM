import { describe, expect, it } from 'vitest';
import { buildOutlineChatMessages } from '../usePptOutlineManager';

describe('buildOutlineChatMessages', () => {
  it('shows style-only candidate diffs without outline page changes', () => {
    const messages = buildOutlineChatMessages({
      id: 'out_ppt_1',
      document_id: 'doc_ppt_1',
      title: 'PPT 产出文档',
      target_type: 'ppt',
      status: 'outline_ready',
      outline: [
        {
          id: 'slide_1',
          pageNum: 1,
          title: '原始标题',
          key_points: ['原始要点'],
          layout_description: '原始布局',
        },
      ],
      style_info: {
        preset: 'clean',
        label: '简洁干净',
        tone: '简洁',
        visual_style: '留白',
        supplement_prompt: [],
      },
      outline_chat_draft_outline: [
        {
          id: 'slide_1',
          pageNum: 1,
          title: '原始标题',
          key_points: ['原始要点'],
          layout_description: '原始布局',
        },
      ],
      outline_chat_draft_style_info: {
        preset: 'business',
        label: '商务风格',
        tone: '结论先行，表达清晰',
        visual_style: '浅色背景、图表突出',
        supplement_prompt: ['风格调整为商务风格，修改一下风格信息'],
      },
      outline_chat_has_pending_changes: true,
      outline_chat_active_session_id: 'session_1',
      outline_chat_sessions: [
        {
          id: 'session_1',
          status: 'active',
          has_pending_changes: true,
          change_summary: '已整理一版候选风格信息，当前不会改动页级大纲。',
          messages: [
            { id: 'user_1', role: 'user', content: '风格调整为商务风格，修改一下风格信息' },
            { id: 'assistant_1', role: 'assistant', content: '已整理一版候选风格信息。' },
          ],
        },
      ],
      created_at: '2026-04-29T00:00:00+08:00',
      updated_at: '2026-04-29T00:00:00+08:00',
    });

    const assistant = messages[messages.length - 1];
    expect(assistant.meta?.type).toBe('ppt_outline_draft');
    expect(assistant.meta?.outlineDiff.totalCount).toBe(0);
    expect(assistant.meta?.styleDiff.totalCount).toBeGreaterThan(0);
    expect(assistant.meta?.styleDiff.entries[0].label).toBe('风格类型');
  });
});
