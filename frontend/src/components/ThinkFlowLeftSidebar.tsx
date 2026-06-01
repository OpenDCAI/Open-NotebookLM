import React, { useState } from 'react';
import { Eye, FolderOpen, ImageIcon, Loader2, MessageCircle, MessageSquarePlus, Package, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';

import type { KnowledgeFile } from '../types';
import { formatThinkFlowDateTime } from './thinkflow-document-utils';

type OutputType = 'ppt' | 'report' | 'mindmap' | 'podcast' | 'flashcard' | 'quiz';

type SidebarOutput = {
  id: string;
  title: string;
  target_type: OutputType;
  outline?: Array<unknown>;
  updated_at: string;
};

type ConversationItem = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

type Props = {
  activeOutputId: string;
  files: KnowledgeFile[];
  getFileEmoji: (type?: string) => string;
  getOutputEmoji: (type: OutputType) => string;
  isOutputWorkspace: boolean;
  leftTab: 'conversations' | 'materials' | 'outputs';
  loadingFiles: boolean;
  onLeftTabChange: (next: 'conversations' | 'materials' | 'outputs') => void;
  onOpenOutput: (output: SidebarOutput) => void | Promise<void>;
  onPreviewSource: (file: KnowledgeFile) => void;
  onDeleteSource: (file: KnowledgeFile) => void;
  onRefreshFiles: () => void | Promise<void>;
  onToggleSource: (fileId: string) => void;
  onReEmbedSource: (file: KnowledgeFile) => Promise<void> | void;
  onReindexPdfImages?: () => Promise<void> | void;
  onExtractPdfImages?: (file: KnowledgeFile) => Promise<void> | void;
  outputs: SidebarOutput[];
  selectedIds: Set<string>;
  uploading: boolean;
  onUpload: React.ChangeEventHandler<HTMLInputElement>;
  onAddSource: () => void;
  conversationList: ConversationItem[];
  activeConversationId: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
};

function statusLabel(file: KnowledgeFile) {
  if (file.vectorStatus === 'embedded' || file.vectorReady || file.isEmbedded) {
    return '已解析';
  }
  if (file.vectorStatus === 'pending') {
    return '解析中';
  }
  if (file.vectorStatus === 'failed') {
    return '失败';
  }
  return '待处理';
}

function statusClassName(file: KnowledgeFile) {
  if (file.vectorStatus === 'embedded' || file.vectorReady || file.isEmbedded) {
    return 'is-ready';
  }
  if (file.vectorStatus === 'pending') {
    return 'is-pending';
  }
  if (file.vectorStatus === 'failed') {
    return 'is-failed';
  }
  return '';
}

export function ThinkFlowLeftSidebar({
  activeOutputId,
  files,
  getFileEmoji,
  getOutputEmoji,
  isOutputWorkspace,
  leftTab,
  loadingFiles,
  onLeftTabChange,
  onOpenOutput,
  onPreviewSource,
  onDeleteSource,
  onRefreshFiles,
  onToggleSource,
  onReEmbedSource,
  onReindexPdfImages,
  onExtractPdfImages,
  outputs,
  selectedIds,
  uploading,
  onUpload,
  onAddSource,
  conversationList,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: Props) {
  const pendingCount = files.filter((file) => file.vectorStatus === 'pending').length;
  const selectedCount = selectedIds.size;
  const [embeddingIds, setEmbeddingIds] = useState<Set<string>>(new Set());
  const [reindexing, setReindexing] = useState(false);
  const [extractingIds, setExtractingIds] = useState<Set<string>>(new Set());

  const handleReindexPdfImages = async () => {
    if (reindexing || !onReindexPdfImages) return;
    setReindexing(true);
    try {
      await onReindexPdfImages();
    } finally {
      setReindexing(false);
    }
  };

  const handleReEmbed = async (file: KnowledgeFile) => {
    if (embeddingIds.has(file.id)) return;
    setEmbeddingIds((prev) => new Set([...prev, file.id]));
    try {
      await onReEmbedSource(file);
    } finally {
      setEmbeddingIds((prev) => {
        const next = new Set(prev);
        next.delete(file.id);
        return next;
      });
    }
  };

  const handleExtractImages = async (file: KnowledgeFile) => {
    if (extractingIds.has(file.id) || !onExtractPdfImages) return;
    setExtractingIds((prev) => new Set([...prev, file.id]));
    try {
      await onExtractPdfImages(file);
    } finally {
      setExtractingIds((prev) => {
        const next = new Set(prev);
        next.delete(file.id);
        return next;
      });
    }
  };

  return (
    <aside className={`thinkflow-left-panel ${isOutputWorkspace ? 'is-hidden' : ''}`}>
      <div className="thinkflow-left-tabs">
        <button
          type="button"
          className={`thinkflow-left-tab ${leftTab === 'conversations' ? 'is-active' : ''}`}
          onClick={() => onLeftTabChange('conversations')}
        >
          <MessageCircle size={15} />
          对话
          {conversationList.length > 0 ? <span className="thinkflow-badge-count">{conversationList.length}</span> : null}
        </button>
        <button
          type="button"
          className={`thinkflow-left-tab ${leftTab === 'materials' ? 'is-active' : ''}`}
          onClick={() => onLeftTabChange('materials')}
        >
          <FolderOpen size={15} />
          素材
        </button>
        <button
          type="button"
          className={`thinkflow-left-tab ${leftTab === 'outputs' ? 'is-active' : ''}`}
          onClick={() => onLeftTabChange('outputs')}
        >
          <Package size={15} />
          产出
          {outputs.length > 0 ? <span className="thinkflow-badge-count">{outputs.length}</span> : null}
        </button>
      </div>

      {leftTab === 'conversations' ? (
        <div className="thinkflow-left-scroll">
          <div className="thinkflow-conversation-list-header">
            <strong>历史对话</strong>
            <button type="button" className="thinkflow-left-refresh-btn" onClick={onNewConversation} title="新建对话">
              <MessageSquarePlus size={14} />
            </button>
          </div>
          {conversationList.length === 0 ? (
            <div className="thinkflow-empty thinkflow-left-empty">暂无对话记录</div>
          ) : (
            conversationList.map((conv) => (
              <button
                key={conv.id}
                type="button"
                className={`thinkflow-conversation-item ${activeConversationId === conv.id ? 'is-active' : ''}`}
                onClick={() => onSelectConversation(conv.id)}
              >
                <div className="thinkflow-conversation-item-title">{conv.title || '未命名对话'}</div>
                {conv.updated_at || conv.created_at ? (
                  <div className="thinkflow-conversation-item-time">
                    {formatThinkFlowDateTime(conv.updated_at || conv.created_at)}
                  </div>
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : leftTab === 'materials' ? (
        <>
          <div className="thinkflow-left-section-head">
            <div className="thinkflow-left-section-copy">
              <strong>当前来源</strong>
              <span>
                已选 {selectedCount}/{files.length || 0}
                {pendingCount > 0 ? ` · ${pendingCount} 个解析中` : ''}
              </span>
            </div>
            <button
              type="button"
              className="thinkflow-left-refresh-btn"
              onClick={() => void onRefreshFiles()}
              disabled={loadingFiles}
              title="刷新来源状态"
            >
              <RefreshCw size={14} className={loadingFiles ? 'is-spinning' : ''} />
            </button>
            {onReindexPdfImages && (
              <button
                type="button"
                className="thinkflow-left-refresh-btn"
                onClick={() => void handleReindexPdfImages()}
                disabled={reindexing}
                title={reindexing ? '图片索引重建中…' : '重建 PDF 图片索引（VLM 模式）'}
              >
                {reindexing ? <Loader2 size={14} className="is-spinning" /> : <ImageIcon size={14} />}
              </button>
            )}
          </div>

          <div className="thinkflow-left-scroll">
            {loadingFiles ? <div className="thinkflow-empty thinkflow-left-empty">正在加载素材...</div> : null}
            {!loadingFiles && files.length === 0 ? <div className="thinkflow-empty thinkflow-left-empty">暂无素材</div> : null}
            {files.map((file) => {
              const isEmbedded = file.vectorStatus === 'embedded' || file.vectorReady || file.isEmbedded;
              const isPending = file.vectorStatus === 'pending';
              const isReEmbedding = embeddingIds.has(file.id);
              return (
                <div
                  key={file.id}
                  className={`thinkflow-file-item ${selectedIds.has(file.id) ? 'is-active' : ''}`}
                >
                  {/* 左侧 emoji */}
                  <div className="thinkflow-file-icon" onClick={() => onToggleSource(file.id)}>
                    {getFileEmoji(file.type)}
                  </div>

                  {/* 中间：两行内容区 */}
                  <button
                    type="button"
                    className="thinkflow-file-body"
                    onClick={() => onToggleSource(file.id)}
                  >
                    {/* 第一行：文件名 */}
                    <div className="thinkflow-file-name" title={file.name}>{file.name}</div>
                    {/* 第二行：状态 */}
                    <div className="thinkflow-file-meta">
                      {isReEmbedding ? (
                        <span className="thinkflow-file-status is-pending">入库中…</span>
                      ) : isEmbedded ? (
                        <span className="thinkflow-file-status is-ready">已入库</span>
                      ) : isPending ? (
                        <span className="thinkflow-file-status is-pending">解析中…</span>
                      ) : (
                        <span className="thinkflow-file-status is-idle">待入库</span>
                      )}
                    </div>
                  </button>

                  {/* 右侧：常驻操作按钮组 */}
                  <div className="thinkflow-file-actions">
                    {/* 未入库：重新入库按钮（转圈 loading） */}
                    {!isEmbedded && !isPending && (
                      <button
                        type="button"
                        className="thinkflow-file-action-icon"
                        onClick={(e) => { e.stopPropagation(); void handleReEmbed(file); }}
                        disabled={isReEmbedding}
                        title={isReEmbedding ? '入库中…' : '重新入库'}
                      >
                        {isReEmbedding
                          ? <Loader2 size={12} className="is-spinning" />
                          : <Upload size={12} />}
                      </button>
                    )}
                    {/* 提取PDF图片按钮：仅对已入库的 doc 类型文件显示 */}
                    {onExtractPdfImages && isEmbedded && file.type === 'doc' && (
                      <button
                        type="button"
                        className="thinkflow-file-action-icon"
                        onClick={(e) => { e.stopPropagation(); void handleExtractImages(file); }}
                        disabled={extractingIds.has(file.id)}
                        title={extractingIds.has(file.id) ? '提取中…' : '查看PDF图片'}
                      >
                        {extractingIds.has(file.id)
                          ? <Loader2 size={12} className="is-spinning" />
                          : <ImageIcon size={12} />}
                      </button>
                    )}
                    <button
                      type="button"
                      className="thinkflow-file-action-icon"
                      onClick={(e) => { e.stopPropagation(); onPreviewSource(file); }}
                      title="预览"
                    >
                      <Eye size={12} />
                    </button>
                    <button
                      type="button"
                      className="thinkflow-file-action-icon is-danger"
                      onClick={(e) => { e.stopPropagation(); onDeleteSource(file); }}
                      title="删除"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <button
            type="button"
            className="thinkflow-add-source-btn"
            onClick={onAddSource}
          >
            <Plus size={16} />
            添加来源
          </button>

          <label
            className="thinkflow-upload-area"
            style={uploading ? { pointerEvents: 'none', opacity: 0.6 } : undefined}
          >
            <Upload size={16} />
            <span>{uploading ? '上传中...' : '快速上传文件'}</span>
            <input type="file" multiple hidden onChange={onUpload} disabled={uploading} />
          </label>
        </>
      ) : (
        <div className="thinkflow-left-scroll">
          {outputs.length === 0 ? <div className="thinkflow-empty thinkflow-left-empty">暂无产出</div> : null}
          {outputs.map((output) => (
            <button
              key={output.id}
              type="button"
              className={`thinkflow-output-card ${activeOutputId === output.id ? 'is-active' : ''}`}
              data-testid={`output-card-${output.id}`}
              onClick={() => void onOpenOutput(output)}
            >
              <div className="thinkflow-output-card-thumb">
                <div className="thinkflow-output-card-emoji">{getOutputEmoji(output.target_type)}</div>
                <div className="thinkflow-output-card-badge">{output.outline?.length || 0} 项</div>
              </div>
              <div className="thinkflow-output-card-info">
                <div className="thinkflow-output-card-title">{output.title}</div>
                <div className="thinkflow-output-card-meta">
                  {output.target_type} · {formatThinkFlowDateTime(output.updated_at)}
                </div>
                <div className="thinkflow-output-card-actions">
                  <span>{activeOutputId === output.id ? '当前查看' : '打开查看'}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
