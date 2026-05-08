import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ThinkFlowCenterPanel } from '../ThinkFlowCenterPanel';

const noop = vi.fn();

function renderPptWorkbenchCenterPanel() {
  const setActivePptSlideIndex = vi.fn();
  render(
    <ThinkFlowCenterPanel
      workspaceMode="output_focus"
      rightPanelOpen={true}
      activePptSlideIndex={0}
      activeOutput={{
        id: 'out_ppt_1',
        document_id: 'doc_1',
        title: '梳理摘要 1 · PPT',
        target_type: 'ppt',
        status: 'pages_ready',
        pipeline_stage: 'pages_ready',
        outline: [
          {
            id: 'slide_1',
            pageNum: 1,
            title: 'SHRP：面向高效编码器压缩的专业化头路由与剪枝',
            layout_description: '标题页布局：中央放置主标题与副标题',
            key_points: ['结构化压缩框架', '最终产出静态压缩编码器'],
          },
          {
            id: 'slide_2',
            pageNum: 2,
            title: '背景与挑战：生产环境中的Transformer编码器',
            layout_description: '左侧列出关键挑战，右侧放置框图',
            key_points: ['延迟和内存开销', '运行时收益有限'],
          },
        ],
        created_at: '2026-04-29T00:00:00+08:00',
        updated_at: '2026-04-29T00:00:00+08:00',
      }}
      chatMessages={[
        { id: 'msg_1', role: 'assistant', content: '这条聊天不应该显示', time: '10:00' },
      ]}
      chatScrollRef={{ current: null }}
      messageRefs={{ current: {} }}
      focusedMessageId=""
      selectedMessageIds={[]}
      renderMessageMarkdown={(message) => <div>{message.content}</div>}
      openPushPopover={noop}
      openQAPushPopover={noop}
      toggleMessageSelection={noop}
      multiSelectPrompt=""
      setMultiSelectPrompt={noop}
      clearSelectedMessages={noop}
      openMultiMessagePush={noop}
      chatInput=""
      setChatInput={noop}
      handleSendMessage={async () => {}}
      chatLoading={false}
      documents={[]}
      boundDocIds={[]}
      toggleBoundDoc={noop}
      openRightPanelForDocument={noop}
      openRightPanelForActiveOutput={noop}
      onSetActivePptSlideIndex={setActivePptSlideIndex}
      onNewConversation={noop}
      chatMode="chat"
      onChatModeChange={noop}
      activeDataset={null}
      dataSessionId={null}
      notebookContext={{ notebookId: 'nb_1', notebookTitle: 'test427', userId: 'user_1', userEmail: 'u@example.com' }}
    />,
  );
  return { setActivePptSlideIndex };
}

describe('ThinkFlowCenterPanel', () => {
  it('replaces the PPT workbench chat column with the confirmed outline', () => {
    const { setActivePptSlideIndex } = renderPptWorkbenchCenterPanel();

    expect(screen.getByText('PPT 大纲')).toBeInTheDocument();
    expect(screen.getByText('SHRP：面向高效编码器压缩的专业化头路由与剪枝')).toBeInTheDocument();
    expect(screen.getByText('标题页布局：中央放置主标题与副标题')).toBeInTheDocument();
    expect(screen.getByText('结构化压缩框架')).toBeInTheDocument();
    expect(screen.queryByText('这条聊天不应该显示')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('背景与挑战：生产环境中的Transformer编码器'));
    expect(setActivePptSlideIndex).toHaveBeenCalledWith(1);
  });
});
