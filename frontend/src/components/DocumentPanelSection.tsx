import { useState, type ReactNode, type RefObject } from 'react';
import { CheckCircle2, Save, Target, Trash2, X } from 'lucide-react';

import type { ThinkFlowOutputButton } from './thinkflow-types';
import { formatThinkFlowDateTime } from './thinkflow-document-utils';

type DocumentPanelSectionProps = {
  documents: Array<{ id: string; title: string }>;
  activeDocumentId: string;
  activeDocument: { id: string; title: string; document_type?: string } | null;
  pendingDocument?: { title: string; content: string } | null;
  documentTitle: string;
  documentContent: string;
  editMode: boolean;
  showVersionPanel: boolean;
  versions: Array<{ id: string; reason?: string; created_at: string }>;
  panelGuide: ReactNode;
  documentSections: any[];
  renderDocumentSection: (section: any) => ReactNode;
  docBodyRef: RefObject<HTMLDivElement | null>;
  focusState: { type: string; description?: string; section_ids?: string[]; stash_item_ids?: string[] };
  stashItems: Array<{ id: string; content: string; created_at?: string }>;
  changeLogs: Array<{ id: string; summary: string; timestamp: string; type: string }>;
  conversationActiveDocumentId: string;
  conversationActiveDocument: { id: string; title: string } | null;
  guidanceItems: Array<{ id: string; title: string }>;
  selectedGuidanceIds: string[];
  outputButtons: ThinkFlowOutputButton[];
  generatingOutline: string | null;
  documentSaving: boolean;
  onSelectDocument: (id: string) => Promise<void>;
  onActivateDisplayedDocument: () => Promise<void>;
  onClearFocus: () => Promise<void>;
  onCreateDocument: () => Promise<void>;
  onCreateOutputDocument: (params?: {
    title?: string;
    sourceRefs?: Array<{ id: string; type: 'document' | 'output_document'; title: string; metadata?: Record<string, any> }>;
  }) => Promise<void>;
  onToggleDocumentEdit: () => void;
  onToggleVersionPanel: () => void;
  onDeleteDocument: (id: string) => Promise<void>;
  onDocumentTitleChange: (value: string) => void;
  onDocumentContentChange: (value: string) => void;
  onRestoreVersion: (versionId: string) => Promise<void>;
  onToggleGuidanceSelection: (id: string) => void;
  onOutputAction: (type: string) => Promise<void>;
  onSaveDocument: () => Promise<void>;
};

export function DocumentPanelSection({
  documents,
  activeDocumentId,
  activeDocument,
  pendingDocument,
  documentTitle,
  documentContent,
  editMode,
  showVersionPanel,
  versions,
  panelGuide,
  documentSections,
  renderDocumentSection,
  docBodyRef,
  focusState,
  stashItems,
  changeLogs,
  conversationActiveDocumentId,
  conversationActiveDocument,
  guidanceItems,
  selectedGuidanceIds,
  outputButtons,
  generatingOutline,
  documentSaving,
  onSelectDocument,
  onActivateDisplayedDocument,
  onClearFocus,
  onCreateDocument,
  onCreateOutputDocument,
  onToggleDocumentEdit,
  onToggleVersionPanel,
  onDeleteDocument,
  onDocumentTitleChange,
  onDocumentContentChange,
  onRestoreVersion,
  onToggleGuidanceSelection,
  onOutputAction,
  onSaveDocument,
}: DocumentPanelSectionProps) {
  const [outputWizardOpen, setOutputWizardOpen] = useState(false);
  const [outputWizardTitle, setOutputWizardTitle] = useState('PPT 产出文档');
  const [outputWizardSources, setOutputWizardSources] = useState<Record<string, { body: boolean; stash: boolean }>>({});
  const displayedActiveDocument = pendingDocument
    ? { id: '__ppt_output_pending__', title: pendingDocument.title, document_type: 'output_doc' }
    : activeDocument;
  const displayedActiveDocumentId = pendingDocument ? '__ppt_output_pending__' : activeDocumentId;
  const displayedDocumentTitle = pendingDocument ? pendingDocument.title : documentTitle;
  const displayedDocumentContent = pendingDocument ? pendingDocument.content : documentContent;
  const isOutputDocument = displayedActiveDocument?.document_type === 'output_doc';
  const isPendingDocument = Boolean(pendingDocument);
  const focusText = focusState.description || (isOutputDocument ? '确认模块：全文' : '焦点：全文');

  const toggleOutputWizardSource = (documentId: string, key: 'body' | 'stash') => {
    setOutputWizardSources((previous) => {
      const current = previous[documentId] || { body: key === 'body', stash: key === 'stash' };
      return {
        ...previous,
        [documentId]: {
          ...current,
          [key]: !current[key],
        },
      };
    });
  };

  const submitOutputWizard = async () => {
    const sourceRefs = documents
      .map((doc) => {
        const range = outputWizardSources[doc.id];
        if (!range?.body && !range?.stash) return null;
        return {
          id: doc.id,
          type: 'document' as const,
          title: doc.title,
          metadata: {
            include_body: Boolean(range.body),
            include_stash: Boolean(range.stash),
          },
        };
      })
      .filter(Boolean) as Array<{ id: string; type: 'document'; title: string; metadata?: Record<string, any> }>;
    await onCreateOutputDocument({ title: outputWizardTitle, sourceRefs });
    setOutputWizardOpen(false);
  };

  return (
    <>
      <div className="thinkflow-doc-header">
        <div className="thinkflow-doc-tabs">
          {documents.map((doc) => (
            <button
              key={doc.id}
              type="button"
              className={`thinkflow-doc-tab ${displayedActiveDocumentId === doc.id ? 'is-active' : ''} ${conversationActiveDocumentId === doc.id ? 'is-conversation-active' : ''}`}
              onClick={() => void onSelectDocument(doc.id)}
            >
              {conversationActiveDocumentId === doc.id ? <span className="thinkflow-doc-active-dot" /> : null}
              {doc.title}
            </button>
          ))}
        </div>
        <div className="thinkflow-doc-header-actions">
          <button type="button" className="thinkflow-doc-new-btn" onClick={() => void onCreateDocument()}>
            + 新建
          </button>
          <button type="button" className="thinkflow-doc-new-btn" onClick={() => setOutputWizardOpen(true)}>
            + 产出文档
          </button>
          <div className="thinkflow-doc-actions">
            <button type="button" className={`thinkflow-doc-action-btn ${editMode ? 'is-active' : ''}`} onClick={onToggleDocumentEdit} disabled={isPendingDocument}>
              {editMode ? '编辑中' : '编辑全文'}
            </button>
            <button type="button" className={`thinkflow-doc-action-btn ${showVersionPanel ? 'is-active' : ''}`} onClick={onToggleVersionPanel} disabled={isPendingDocument || versions.length <= 1}>
              历史{versions.length > 1 ? `(${versions.length})` : ''}
            </button>
            {displayedActiveDocument && !isPendingDocument ? (
              <button type="button" className="thinkflow-doc-action-btn is-danger" onClick={() => void onDeleteDocument(displayedActiveDocument.id)}>
                <Trash2 size={14} />
                删除
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {displayedActiveDocument ? (
        <div className="thinkflow-doc-title-row">
          <input
            className="thinkflow-doc-title-input"
            value={displayedDocumentTitle}
            onChange={(event) => onDocumentTitleChange(event.target.value)}
            disabled={isPendingDocument}
            placeholder="为这份梳理输入标题，或稍后从对话内容整理命名"
          />
        </div>
      ) : null}

      {displayedActiveDocument ? (
        <div className={`thinkflow-doc-focus-bar ${isOutputDocument ? 'is-output-module-focus' : ''}`}>
          <div>
            <Target size={13} />
            <span>{isOutputDocument ? focusText.replace(/^焦点：/, '确认模块：') : focusText}</span>
          </div>
          {focusState.type !== 'full' && !isPendingDocument ? (
            <button type="button" className="thinkflow-doc-action-btn" onClick={() => void onClearFocus()}>
              <X size={12} />
              {isOutputDocument ? '取消确认' : '回到全文'}
            </button>
          ) : null}
        </div>
      ) : null}

      {displayedActiveDocument && !isPendingDocument && conversationActiveDocumentId && displayedActiveDocument.id !== conversationActiveDocumentId ? (
        <div className="thinkflow-doc-active-warning">
          <span>当前显示的是「{displayedActiveDocument.title}」，对话活跃文档是「{conversationActiveDocument?.title || '未命名文档'}」</span>
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => void onActivateDisplayedDocument()}>
            <CheckCircle2 size={13} />
            切换活跃为本文档
          </button>
        </div>
      ) : null}

      {panelGuide}

      <div className="thinkflow-doc-body" ref={docBodyRef}>
        {!displayedActiveDocument ? (
        <div className="thinkflow-empty">
            来源是主输入；梳理文档用于沉淀结构化理解，也可以作为后续产出的增强上下文。
            <br />
            先在中间持续对话，再把真正有价值的段落或回答推送到这里。
          </div>
        ) : isPendingDocument ? (
          <pre className="thinkflow-markdown thinkflow-ppt-output-pending-doc">{displayedDocumentContent}</pre>
        ) : !displayedDocumentContent.trim() ? (
          <div className="thinkflow-empty">
            在左边对话中选中内容，点击 <strong>⟩</strong> 推送到这里。
          </div>
        ) : editMode ? (
          <textarea className="thinkflow-doc-editor" value={displayedDocumentContent} onChange={(event) => onDocumentContentChange(event.target.value)} />
        ) : (
          <div className="thinkflow-doc-sections">{documentSections.map(renderDocumentSection)}</div>
        )}
        {displayedActiveDocument && !isPendingDocument ? (
          <div className="thinkflow-doc-stash">
            <div className="thinkflow-doc-stash-head">暂存区 ({stashItems.length})</div>
            {stashItems.length === 0 ? (
              <div className="thinkflow-doc-stash-empty">暂无暂存内容</div>
            ) : (
              stashItems.map((item, index) => (
                <article key={item.id} className="thinkflow-doc-stash-item">
                  <div className="thinkflow-doc-stash-meta">暂存 {index + 1}{item.created_at ? ` · ${formatThinkFlowDateTime(item.created_at)}` : ''}</div>
                  <p>{item.content}</p>
                </article>
              ))
            )}
          </div>
        ) : null}
      </div>

      {showVersionPanel && versions.length > 1 ? (
        <div className="thinkflow-version-panel">
          {versions.map((version, index) => (
            <div key={version.id} className={`thinkflow-version-item ${index === 0 ? 'is-current' : ''}`}>
              <div className="thinkflow-version-main">
                <div className="thinkflow-version-title">{version.reason || 'update'}</div>
                <div className="thinkflow-version-time">{formatThinkFlowDateTime(version.created_at)}</div>
              </div>
              {index > 0 ? (
                <button type="button" className="thinkflow-version-restore" onClick={() => void onRestoreVersion(version.id)}>
                  恢复
                </button>
              ) : (
                <span className="thinkflow-version-current">当前</span>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <div className="thinkflow-output-toolbar">
        {changeLogs.length > 0 ? (
          <div className="thinkflow-doc-change-strip">
            <span>最近变更</span>
            {changeLogs.slice(0, 3).map((item) => (
              <em key={item.id}>{item.summary || item.type}</em>
            ))}
          </div>
        ) : null}
        <span className="thinkflow-output-toolbar-label">产出</span>
        <span className="thinkflow-output-toolbar-tip">来源是主输入；当前梳理文档和产出指导会作为可选增强上下文</span>
        <div className="thinkflow-guidance-strip">
          {guidanceItems.length === 0 ? <span className="thinkflow-doc-check-tip">暂无产出指导</span> : null}
          {guidanceItems.map((item) => (
            <label key={item.id} className={`thinkflow-doc-check ${selectedGuidanceIds.includes(item.id) ? 'is-checked' : ''}`}>
              <input type="checkbox" checked={selectedGuidanceIds.includes(item.id)} onChange={() => onToggleGuidanceSelection(item.id)} />
              <Target size={12} /> {item.title}
            </label>
          ))}
        </div>
        {outputButtons.map((button) => (
          <button key={button.type} type="button" className="thinkflow-output-toolbar-btn" onClick={() => void onOutputAction(button.type)} disabled={generatingOutline !== null}>
            {button.icon}
            {generatingOutline === button.type
              ? `生成${button.label}中`
              : activeDocument?.document_type === 'output_doc' && button.type === 'ppt'
                ? '进入 PPT 工作台'
                : button.label}
          </button>
        ))}
        <button type="button" className="thinkflow-save-btn" onClick={() => void onSaveDocument()} disabled={documentSaving}>
          <Save size={14} />
          {documentSaving ? '保存中' : '保存文档'}
        </button>
      </div>

      {outputWizardOpen ? (
        <>
          <div className="thinkflow-popover-overlay" onClick={() => setOutputWizardOpen(false)} />
          <div className="thinkflow-output-doc-wizard">
            <div className="thinkflow-output-doc-wizard-head">
              <div>
                <h3>新建产出文档</h3>
                <p>选择本次 PPT 产出文档要读取的梳理文档范围。</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setOutputWizardOpen(false)}>关闭</button>
            </div>
            <label className="thinkflow-add-source-label">
              标题
              <input className="thinkflow-add-source-input" value={outputWizardTitle} onChange={(event) => setOutputWizardTitle(event.target.value)} />
            </label>
            <div className="thinkflow-output-doc-source-list">
              {documents.map((doc) => {
                const range = outputWizardSources[doc.id] || { body: activeDocumentId === doc.id, stash: false };
                return (
                  <div key={doc.id} className="thinkflow-output-doc-source-item">
                    <strong>{doc.title}</strong>
                    <label>
                      <input type="checkbox" checked={range.body} onChange={() => toggleOutputWizardSource(doc.id, 'body')} />
                      主文
                    </label>
                    <label>
                      <input type="checkbox" checked={range.stash} onChange={() => toggleOutputWizardSource(doc.id, 'stash')} />
                      暂存区
                    </label>
                  </div>
                );
              })}
            </div>
            <div className="thinkflow-push-actions">
              <button type="button" className="thinkflow-doc-action-btn" onClick={() => setOutputWizardOpen(false)}>取消</button>
              <button type="button" className="thinkflow-generate-btn" onClick={() => void submitOutputWizard()}>创建</button>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
