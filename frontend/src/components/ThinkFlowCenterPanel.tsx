import type { MutableRefObject, ReactNode, RefObject } from 'react';
import { useRef, useCallback } from 'react';
import { Check, FileText, MessageSquarePlus, Plus } from 'lucide-react';

import type {
  ThinkFlowDocument,
  ThinkFlowMessage,
  ThinkFlowOutput,
  OutlineSection,
  WorkspaceMode,
  ChatMode,
  RetrievalMode,
  ChatAttachment,
} from './thinkflow-types';
import type { KnowledgeFile } from '../types';
import { TableAnalysisPanel, type NotebookContext } from './TableAnalysisPanel';

type ThinkFlowCenterPanelProps = {
  workspaceMode: WorkspaceMode;
  rightPanelOpen: boolean;
  activeOutput: ThinkFlowOutput | null;
  activePptSlideIndex?: number;
  chatTitle?: string;
  chatPlaceholder?: string;
  isOutlineChatMode?: boolean;
  chatMessages: ThinkFlowMessage[];
  chatScrollRef: RefObject<HTMLDivElement | null>;
  messageRefs: MutableRefObject<Record<string, HTMLDivElement | null>>;
  focusedMessageId: string;
  selectedMessageIds: string[];
  renderMessageMarkdown: (message: ThinkFlowMessage) => ReactNode;
  chatTopPanel?: ReactNode;
  openPushPopover: (message: ThinkFlowMessage, event: React.MouseEvent<HTMLButtonElement>) => void;
  openQAPushPopover: (message: ThinkFlowMessage, event: React.MouseEvent<HTMLButtonElement>) => void;
  toggleMessageSelection: (messageId: string) => void;
  multiSelectPrompt: string;
  setMultiSelectPrompt: (value: string) => void;
  clearSelectedMessages: () => void;
  openMultiMessagePush: (anchor: HTMLElement) => void;
  chatInput: string;
  setChatInput: (value: string) => void;
  handleSendMessage: () => Promise<void>;
  chatLoading: boolean;
  documents: ThinkFlowDocument[];
  boundDocIds: string[];
  toggleBoundDoc: (docId: string) => void;
  openRightPanelForDocument: () => void;
  openRightPanelForActiveOutput: () => void;
  onSetActivePptSlideIndex?: (index: number) => void;
  onNewConversation: () => void;
  // ─── 表格分析模式 ────────────────────────────────────────────────────────
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  activeDataset: KnowledgeFile | null;
  dataSessionId: string | null;
  notebookContext: NotebookContext;
  chatDisabled?: boolean;
  retrievalMode: RetrievalMode;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
  chatAttachments: ChatAttachment[];
  onAttachmentsChange: (attachments: ChatAttachment[]) => void;
};

export function ThinkFlowCenterPanel({
  workspaceMode,
  rightPanelOpen,
  activeOutput,
  activePptSlideIndex,
  chatTitle,
  chatPlaceholder,
  isOutlineChatMode = false,
  chatMessages,
  chatScrollRef,
  messageRefs,
  focusedMessageId,
  selectedMessageIds,
  renderMessageMarkdown,
  chatTopPanel,
  openPushPopover,
  openQAPushPopover,
  toggleMessageSelection,
  multiSelectPrompt,
  setMultiSelectPrompt,
  clearSelectedMessages,
  openMultiMessagePush,
  chatInput,
  setChatInput,
  handleSendMessage,
  chatLoading,
  documents,
  boundDocIds,
  toggleBoundDoc,
  openRightPanelForDocument,
  openRightPanelForActiveOutput,
  onSetActivePptSlideIndex,
  onNewConversation,
  chatMode,
  onChatModeChange,
  activeDataset,
  dataSessionId,
  notebookContext,
  retrievalMode,
  onRetrievalModeChange,
  chatAttachments,
  onAttachmentsChange,
}: ThinkFlowCenterPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const dataUrl = ev.target?.result as string;
        onAttachmentsChange([
          ...chatAttachments,
          { id: `${Date.now()}_${Math.random()}`, dataUrl, fileName: file.name },
        ]);
      };
      reader.readAsDataURL(file);
    });
    e.target.value = '';
  }, [chatAttachments, onAttachmentsChange]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter((item) => item.type.startsWith('image/'));
    if (imageItems.length === 0) return;
    e.preventDefault();
    imageItems.forEach((item) => {
      const file = item.getAsFile();
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        const dataUrl = ev.target?.result as string;
        onAttachmentsChange([
          ...chatAttachments,
          { id: `${Date.now()}_${Math.random()}`, dataUrl, fileName: 'pasted-image.png' },
        ]);
      };
      reader.readAsDataURL(file);
    });
  }, [chatAttachments, onAttachmentsChange]);

  const formatReferenceDocumentLabel = (doc: ThinkFlowDocument) => {
    const focusState = doc.focus_state;
    if (focusState?.type === 'sections' && Array.isArray(focusState.section_ids) && focusState.section_ids.length > 0) {
      const focusLabel = String(focusState.description || '')
        .replace(/^(焦点|确认模块)：/u, '')
        .trim() || `${focusState.section_ids.length} 个模块`;
      return `${doc.title} / ${focusLabel}`;
    }
    return `${doc.title} / 全文`;
  };

  const isPptWorkbenchOutline = workspaceMode === 'output_focus' && activeOutput?.target_type === 'ppt';

  const renderPptWorkbenchOutline = () => {
    const outline = (activeOutput?.outline || []) as OutlineSection[];
    return (
      <div className="thinkflow-ppt-left-outline">
        <div className="thinkflow-ppt-left-outline-head">
          <span className="thinkflow-output-workspace-kicker">PPT 大纲</span>
          <h3>{activeOutput?.title || '当前 PPT'}</h3>
          <p>这里展示刚刚确认的大纲。右侧工作台保持原布局，用于逐页生成、核对和确认。</p>
          <div className="thinkflow-ppt-left-outline-meta">
            <strong>{outline.length} 页</strong>
            <span>来自本轮 PPT 对话</span>
          </div>
        </div>
        <div className="thinkflow-ppt-left-outline-list">
          {outline.length > 0 ? outline.map((item, index) => {
            const points = item.key_points || item.bullets || [];
            const isActive = typeof activePptSlideIndex === 'number' && activePptSlideIndex === index;
            return (
              <button
                key={item.id || `${activeOutput?.id || 'ppt'}_${index}`}
                type="button"
                className={`thinkflow-ppt-left-outline-card ${isActive ? 'is-active' : ''}`}
                onClick={() => onSetActivePptSlideIndex?.(index)}
              >
                <div className="thinkflow-ppt-left-outline-card-top">
                  <span className="thinkflow-ppt-outline-summary-index">第 {item.pageNum || index + 1} 页</span>
                  <span>{isActive ? '当前页' : '查看'}</span>
                </div>
                <h4>{item.title || `页面 ${index + 1}`}</h4>
                {item.layout_description ? <p>{item.layout_description}</p> : null}
                {points.length > 0 ? (
                  <ul>
                    {points.slice(0, 4).map((point, pointIndex) => (
                      <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="thinkflow-empty">这页还没有要点。</div>
                )}
              </button>
            );
          }) : (
            <div className="thinkflow-empty">暂无可展示的大纲内容。</div>
          )}
        </div>
      </div>
    );
  };

  if (isPptWorkbenchOutline) {
    return (
      <main className={`thinkflow-center-panel ${workspaceMode === 'output_focus' ? 'is-output-focus' : ''}`}>
        <div className="thinkflow-chat-header-bar">
          <div className="thinkflow-chat-header-left">
            <span>📋 PPT 大纲</span>
          </div>
        </div>
        {renderPptWorkbenchOutline()}
      </main>
    );
  }

  return (
    <main className={`thinkflow-center-panel ${workspaceMode === 'output_immersive' ? 'is-output-immersive' : ''} ${workspaceMode === 'output_focus' ? 'is-output-focus' : ''}`}>
      <div className="thinkflow-chat-header-bar">
        <div className="thinkflow-chat-header-left">
          {activeDataset ? (
            // 有 dataset 选中时：显示对话/表格分析切换器
            <div className="flex items-center gap-0.5 rounded-lg bg-gray-100 p-0.5">
              <button
                type="button"
                onClick={() => onChatModeChange('chat')}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  chatMode === 'chat'
                    ? 'bg-white shadow-sm text-gray-900 font-medium'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                💬 对话
              </button>
              <button
                type="button"
                onClick={() => onChatModeChange('table-analysis')}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  chatMode === 'table-analysis'
                    ? 'bg-white shadow-sm text-indigo-600 font-medium'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                📊 表格分析
              </button>
            </div>
          ) : (
            <span>{chatTitle || '💬 对话'}</span>
          )}
        </div>
        <div className="thinkflow-chat-header-actions">
          <button
            type="button"
            className="thinkflow-chat-header-btn"
            onClick={onNewConversation}
            title="开始新对话"
          >
            <MessageSquarePlus size={14} />
            新对话
          </button>
        </div>
      </div>
      <div className="thinkflow-chat-scroll" ref={chatScrollRef}>
        {/* 表格分析模式 */}
        {chatMode === 'table-analysis' && activeDataset ? (
          <TableAnalysisPanel
            sessionId={dataSessionId}
            dataset={activeDataset}
            notebookContext={notebookContext}
          />
        ) : (
          /* 原有聊天消息列表 */
          <>
        {chatTopPanel}
        {chatMessages.map((message) => {
          if (message.role === 'system') {
            const metaType = message.meta?.type || 'manual_edit';
            const iconClass = metaType === 'manual_edit' ? 'edit' : metaType === 'stage_change' ? 'stage' : 'conflict';
            const icon = metaType === 'manual_edit' ? '✏' : metaType === 'stage_change' ? '↩' : '⚠';
            return (
              <div key={message.id} className="tf-system-message">
                <span className={`tf-system-message__icon tf-system-message__icon--${iconClass}`}>
                  {icon}
                </span>
                {message.content}
              </div>
            );
          }
          return (
            <div
              key={message.id}
              ref={(node) => {
                messageRefs.current[message.id] = node;
              }}
              data-message-id={message.id}
              className={`thinkflow-message-row ${message.role} ${focusedMessageId === message.id ? 'is-focused' : ''} ${selectedMessageIds.includes(message.id) ? 'is-selected' : ''}`}
            >
              <div className={`thinkflow-message-shell ${message.role}`}>
                <div className={`thinkflow-bubble ${message.role}`}>
                  <div className="thinkflow-bubble-meta">
                    <span>{message.role === 'assistant' ? 'AI' : '你'}</span>
                    <span>{message.time}</span>
                  </div>
                  {message.attachments && message.attachments.length > 0 && (
                    <div className="thinkflow-bubble-attachments">
                      {message.attachments.map((att) => (
                        <img
                          key={att.id}
                          src={att.dataUrl}
                          alt={att.fileName}
                          className="thinkflow-bubble-attachment-img"
                          title={att.fileName}
                        />
                      ))}
                    </div>
                  )}
                  {renderMessageMarkdown(message)}
                </div>
                {!isOutlineChatMode && (message.role === 'assistant' || message.role === 'user') ? (
                  <div className={`thinkflow-message-actions ${message.role === 'user' ? 'is-user-side' : ''}`}>
                    <button
                      type="button"
                      className={`thinkflow-push-trigger ${message.pushed ? 'is-done' : ''}`}
                      onClick={(event) => openPushPopover(message, event)}
                      disabled={!message.content}
                      title="沉淀当前消息"
                    >
                      {message.pushed ? <Check size={14} /> : <FileText size={14} />}
                    </button>
                    <button
                      type="button"
                      className="thinkflow-message-more"
                      onClick={(event) => openQAPushPopover(message, event)}
                      disabled={!message.content}
                      title="沉淀这一轮问答"
                    >
                      QA
                    </button>
                    <button
                      type="button"
                      className={`thinkflow-message-select ${selectedMessageIds.includes(message.id) ? 'is-active' : ''}`}
                      onClick={() => toggleMessageSelection(message.id)}
                      title="加入多条沉淀"
                    >
                      {selectedMessageIds.includes(message.id) ? <Check size={14} /> : <Plus size={14} />}
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
          </>
        )}
      </div>

      {selectedMessageIds.length > 0 ? (
        <div className="thinkflow-multi-select-bar">
          <div className="thinkflow-multi-select-topline">
            <div className="thinkflow-multi-select-meta">已选 {selectedMessageIds.length} 条消息 · 多条沉淀</div>
            <div className="thinkflow-multi-select-actions">
              <button type="button" className="thinkflow-doc-action-btn" onClick={clearSelectedMessages}>
                取消
              </button>
              <button
                type="button"
                className="thinkflow-generate-btn"
                onClick={(event) => openMultiMessagePush(event.currentTarget)}
              >
                ⟩ 推送
              </button>
            </div>
          </div>
          <textarea
            className="thinkflow-multi-select-input"
            value={multiSelectPrompt}
            onChange={(event) => setMultiSelectPrompt(event.target.value)}
            placeholder="可选：补充你希望这组内容如何被整理，例如'沉淀成产出指导，强调结论和边界条件'"
            rows={2}
          />
        </div>
      ) : null}

      {/* 表格分析模式下隐藏原有聊天输入区 */}
      {chatMode !== 'table-analysis' && (
      <div className="thinkflow-chat-input-area">
        <div className="thinkflow-chat-input-box">
          {/* 附件缩略图区 */}
          {chatAttachments.length > 0 && (
            <div className="thinkflow-attach-strip">
              {chatAttachments.map((att) => (
                <div key={att.id} className="thinkflow-attach-thumb">
                  <img src={att.dataUrl} alt={att.fileName} />
                  <button
                    type="button"
                    className="thinkflow-attach-thumb-remove"
                    onClick={() => onAttachmentsChange(chatAttachments.filter((a) => a.id !== att.id))}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          <textarea
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void handleSendMessage();
              }
            }}
            onPaste={handlePaste}
            placeholder={
              retrievalMode === 'vlm'
                ? '👁 VLM 模式：输入文字，或粘贴 / 附加图片进行多模态检索...'
                : (chatPlaceholder || '输入消息，围绕当前素材梳理你真正想要的结论...')
            }
            className="thinkflow-chat-input"
            rows={2}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileSelect}
          />
          <div className="thinkflow-chat-toolbar">
            {isOutlineChatMode ? (
              <span className="thinkflow-doc-check-tip">当前消息会综合来源、梳理文档、产出指导和当前产出文档，先整理这份 PPT 的候选修改；只有点击"应用候选修改"后才会覆盖正式产出文档，也不会写入普通问答历史。</span>
            ) : (
              <>
                <button type="button" className="thinkflow-toolbar-btn">
                  🔍 搜索
                </button>
                <div className="thinkflow-toolbar-divider" />
                {documents.map((doc) => (
                  <label
                    key={doc.id}
                    className={`thinkflow-doc-check ${boundDocIds.includes(doc.id) ? 'is-checked' : ''}`}
                    title={formatReferenceDocumentLabel(doc)}
                  >
                    <input
                      type="checkbox"
                      checked={boundDocIds.includes(doc.id)}
                      onChange={() => toggleBoundDoc(doc.id)}
                    />
                    📄 {formatReferenceDocumentLabel(doc)}
                  </label>
                ))}
                {boundDocIds.length > 0 ? <span className="thinkflow-doc-check-tip">对话将参考此文档</span> : null}
                {!rightPanelOpen && workspaceMode === 'normal' ? (
                  <button
                    type="button"
                    className="thinkflow-toolbar-btn"
                    onClick={openRightPanelForDocument}
                  >
                    + 新建梳理
                  </button>
                ) : null}
                <div className="thinkflow-toolbar-divider" />
                <button
                  type="button"
                  className={`thinkflow-retrieval-mode-btn${retrievalMode === 'vlm' ? ' is-active' : ''}`}
                  onClick={() => onRetrievalModeChange(retrievalMode === 'vlm' ? 'text' : 'vlm')}
                  title={retrievalMode === 'vlm' ? '当前：VLM 多模态检索，点击切换为文本检索' : '当前：文本检索，点击切换为 VLM 多模态检索'}
                >
                  {retrievalMode === 'vlm' ? '👁 VLM' : '📝 文本'}
                </button>
                {retrievalMode === 'vlm' && (
                  <button
                    type="button"
                    className="thinkflow-toolbar-btn"
                    onClick={() => fileInputRef.current?.click()}
                    title="附加图片"
                  >
                    📎
                  </button>
                )}
              </>
            )}
            <div className="thinkflow-toolbar-spacer" />
            <button type="button" className="thinkflow-send-btn" onClick={() => void handleSendMessage()} disabled={(!chatInput.trim() && chatAttachments.length === 0) || chatLoading}>
              {chatLoading ? '...' : '↑'}
            </button>
          </div>
        </div>
      </div>
      )}

      {!rightPanelOpen && workspaceMode === 'normal' ? (
        <button
          type="button"
          className="thinkflow-open-right-btn"
          onClick={openRightPanelForActiveOutput}
        >
          {activeOutput ? '🧩' : '📄'}
        </button>
      ) : null}
    </main>
  );
}
