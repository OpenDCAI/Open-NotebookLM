import React, { useCallback, useRef, useState } from 'react';
import {
  FileText,
  Link,
  Loader2,
  Search,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';

import { apiFetch, parseJson } from '../config/api';

type Props = {
  notebookId: string;
  notebookTitle: string;
  userId: string;
  email: string;
  open: boolean;
  onClose: () => void;
  onSourceAdded: () => void;
};

type TabKey = 'upload' | 'url' | 'text' | 'fast' | 'deep';

type FastResult = {
  title: string;
  link: string;
  snippet: string;
  selected?: boolean;
};

const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'upload', label: '文件上传', icon: <Upload size={15} /> },
  { key: 'url', label: '网页链接', icon: <Link size={15} /> },
  { key: 'text', label: '文本粘贴', icon: <FileText size={15} /> },
  { key: 'fast', label: '快速搜索', icon: <Search size={15} /> },
  { key: 'deep', label: '深度研究', icon: <Sparkles size={15} /> },
];

export function ThinkFlowAddSourceModal({
  notebookId,
  notebookTitle,
  userId,
  email,
  open,
  onClose,
  onSourceAdded,
}: Props) {
  const [tab, setTab] = useState<TabKey>('upload');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const effectiveUserId = userId || 'local';
  const effectiveEmail = email || effectiveUserId || 'local';

  // URL tab
  const [urlValue, setUrlValue] = useState('');

  // Text tab
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');

  // Fast research tab
  const [searchQuery, setSearchQuery] = useState('');
  const [fastResults, setFastResults] = useState<FastResult[]>([]);
  const [importingLinks, setImportingLinks] = useState(false);

  // Deep research tab
  const [deepTopic, setDeepTopic] = useState('');

  // Upload tab
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const resetMessages = useCallback(() => {
    setError('');
    setSuccess('');
  }, []);

  const handleClose = useCallback(() => {
    resetMessages();
    onClose();
  }, [onClose, resetMessages]);

  // ── File Upload ──
  const uploadFiles = useCallback(
    async (fileList: FileList) => {
      if (fileList.length === 0) return;
      setLoading(true);
      resetMessages();
      try {
        for (const file of Array.from(fileList)) {
          const formData = new FormData();
          formData.append('file', file);
          formData.append('email', effectiveEmail);
          formData.append('user_id', effectiveUserId);
          formData.append('notebook_id', notebookId);
          formData.append('notebook_title', notebookTitle);
          const res = await apiFetch('/api/v1/kb/upload', { method: 'POST', body: formData });
          await parseJson(res);
        }
        setSuccess(`已上传 ${fileList.length} 个文件`);
        onSourceAdded();
      } catch (err: any) {
        setError(err?.message || '上传失败');
      } finally {
        setLoading(false);
      }
    },
    [effectiveEmail, effectiveUserId, notebookId, notebookTitle, onSourceAdded, resetMessages],
  );

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) void uploadFiles(e.target.files);
      e.target.value = '';
    },
    [uploadFiles],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length > 0) void uploadFiles(e.dataTransfer.files);
    },
    [uploadFiles],
  );

  // ── URL Import ──
  const handleUrlImport = useCallback(async () => {
    const trimmed = urlValue.trim();
    if (!trimmed) return;
    setLoading(true);
    resetMessages();
    try {
      const res = await apiFetch('/api/v1/kb/import-url-as-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebookId,
          email: effectiveEmail,
          user_id: effectiveUserId,
          notebook_title: notebookTitle,
          url: trimmed,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || '导入失败');
      }
      setSuccess('网页已导入');
      setUrlValue('');
      onSourceAdded();
    } catch (err: any) {
      setError(err?.message || '导入网页失败');
    } finally {
      setLoading(false);
    }
  }, [urlValue, notebookId, effectiveEmail, effectiveUserId, notebookTitle, onSourceAdded, resetMessages]);

  // ── Text Paste ──
  const handleTextAdd = useCallback(async () => {
    if (!textContent.trim()) return;
    setLoading(true);
    resetMessages();
    try {
      const res = await apiFetch('/api/v1/kb/add-text-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebookId,
          email: effectiveEmail,
          user_id: effectiveUserId,
          notebook_title: notebookTitle,
          title: textTitle.trim() || '直接输入',
          content: textContent,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || '添加失败');
      }
      setSuccess('文本已添加为来源');
      setTextTitle('');
      setTextContent('');
      onSourceAdded();
    } catch (err: any) {
      setError(err?.message || '添加文本失败');
    } finally {
      setLoading(false);
    }
  }, [textContent, textTitle, notebookId, effectiveEmail, effectiveUserId, notebookTitle, onSourceAdded, resetMessages]);

  // ── Fast Research ──
  const handleFastSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    resetMessages();
    setFastResults([]);
    try {
      const res = await apiFetch('/api/v1/kb/fast-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery.trim(), top_k: 10 }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || '搜索失败');
      }
      const data = await res.json();
      const sources: FastResult[] = (data.sources || []).map((s: any) => ({
        title: s.title || '',
        link: s.link || '',
        snippet: s.snippet || '',
        selected: false,
      }));
      setFastResults(sources);
      if (sources.length === 0) setError('未找到相关结果');
    } catch (err: any) {
      setError(err?.message || '搜索失败');
    } finally {
      setLoading(false);
    }
  }, [searchQuery, resetMessages]);

  const toggleFastResult = useCallback((index: number) => {
    setFastResults((prev) => prev.map((r, i) => (i === index ? { ...r, selected: !r.selected } : r)));
  }, []);

  const handleImportSelected = useCallback(async () => {
    const selected = fastResults.filter((r) => r.selected);
    if (selected.length === 0) return;
    setImportingLinks(true);
    resetMessages();
    try {
      const res = await apiFetch('/api/v1/kb/import-link-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebookId,
          email: effectiveEmail,
          user_id: effectiveUserId,
          notebook_title: notebookTitle,
          items: selected.map((r) => ({ title: r.title, link: r.link, snippet: r.snippet })),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || '导入失败');
      }
      setSuccess(`已导入 ${selected.length} 条搜索结果`);
      setFastResults([]);
      setSearchQuery('');
      onSourceAdded();
    } catch (err: any) {
      setError(err?.message || '导入搜索结果失败');
    } finally {
      setImportingLinks(false);
    }
  }, [fastResults, notebookId, effectiveEmail, effectiveUserId, notebookTitle, onSourceAdded, resetMessages]);

  // ── Deep Research ──
  const handleDeepResearch = useCallback(async () => {
    if (!deepTopic.trim()) return;
    setLoading(true);
    resetMessages();
    try {
      const res = await apiFetch('/api/v1/kb/deep-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: deepTopic.trim(),
          notebook_id: notebookId,
          notebook_title: notebookTitle,
          user_id: effectiveUserId,
          email: effectiveEmail,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || '深度研究失败');
      }
      setSuccess('深度研究完成，报告已添加为来源');
      setDeepTopic('');
      onSourceAdded();
    } catch (err: any) {
      setError(err?.message || '深度研究失败');
    } finally {
      setLoading(false);
    }
  }, [deepTopic, notebookId, notebookTitle, effectiveUserId, effectiveEmail, onSourceAdded, resetMessages]);

  if (!open) return null;

  return (
    <>
      <div className="thinkflow-popover-overlay" onClick={handleClose} />
      <div className="thinkflow-output-context-modal thinkflow-add-source-modal" role="dialog" aria-modal="true">
        <div className="thinkflow-output-context-modal-header">
          <div>
            <h3>添加来源</h3>
            <p>上传文件、粘贴文本、导入网页或搜索引入新素材</p>
          </div>
          <button type="button" className="thinkflow-panel-guide-close" onClick={handleClose}><X size={16} /></button>
        </div>

        <div className="thinkflow-add-source-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`thinkflow-add-source-tab ${tab === t.key ? 'is-active' : ''}`}
              onClick={() => { setTab(t.key); resetMessages(); }}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {error ? <div className="thinkflow-add-source-msg is-error">{error}</div> : null}
        {success ? <div className="thinkflow-add-source-msg is-success">{success}</div> : null}

        <div className="thinkflow-output-context-modal-body">
          {tab === 'upload' ? (
            <div
              className={`thinkflow-upload-area thinkflow-add-source-drop ${dragOver ? 'is-drag-over' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              {loading ? <Loader2 size={22} className="is-spinning" /> : <Upload size={22} />}
              <span>{loading ? '上传中...' : '拖拽文件到此处，或点击选择文件'}</span>
              <small>支持 PDF / Word / 图片 / CSV 等格式，可多选</small>
              <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileChange} disabled={loading} />
            </div>
          ) : null}

          {tab === 'url' ? (
            <div className="thinkflow-add-source-form">
              <label className="thinkflow-add-source-label">网页 URL</label>
              <input
                className="thinkflow-add-source-input"
                type="url"
                placeholder="https://example.com/article"
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void handleUrlImport(); }}
                disabled={loading}
              />
              <div className="thinkflow-add-source-actions">
                <button type="button" className="thinkflow-generate-btn" onClick={handleUrlImport} disabled={loading || !urlValue.trim()}>
                  {loading ? <Loader2 size={14} className="is-spinning" /> : <Link size={14} />}
                  导入网页
                </button>
              </div>
            </div>
          ) : null}

          {tab === 'text' ? (
            <div className="thinkflow-add-source-form">
              <label className="thinkflow-add-source-label">标题（可选）</label>
              <input
                className="thinkflow-add-source-input"
                type="text"
                placeholder="给这段文本起个名字"
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
                disabled={loading}
              />
              <label className="thinkflow-add-source-label">内容</label>
              <textarea
                className="thinkflow-add-source-textarea"
                placeholder="粘贴或输入文本内容..."
                rows={8}
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
                disabled={loading}
              />
              <div className="thinkflow-add-source-actions">
                <button type="button" className="thinkflow-generate-btn" onClick={handleTextAdd} disabled={loading || !textContent.trim()}>
                  {loading ? <Loader2 size={14} className="is-spinning" /> : <FileText size={14} />}
                  添加文本
                </button>
              </div>
            </div>
          ) : null}

          {tab === 'fast' ? (
            <div className="thinkflow-add-source-form">
              <label className="thinkflow-add-source-label">搜索关键词</label>
              <div className="thinkflow-add-source-row">
                <input
                  className="thinkflow-add-source-input"
                  type="text"
                  placeholder="输入关键词搜索网络资源"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void handleFastSearch(); }}
                  disabled={loading}
                />
                <button type="button" className="thinkflow-generate-btn" onClick={handleFastSearch} disabled={loading || !searchQuery.trim()}>
                  {loading ? <Loader2 size={14} className="is-spinning" /> : <Search size={14} />}
                  搜索
                </button>
              </div>
              {fastResults.length > 0 ? (
                <div className="thinkflow-add-source-results">
                  {fastResults.map((r, i) => (
                    <button
                      key={r.link}
                      type="button"
                      className={`thinkflow-output-context-option ${r.selected ? 'is-active' : ''}`}
                      onClick={() => toggleFastResult(i)}
                    >
                      <input type="checkbox" checked={!!r.selected} readOnly />
                      <span title={r.link}>{r.title || r.link}</span>
                    </button>
                  ))}
                  <div className="thinkflow-add-source-actions">
                    <button
                      type="button"
                      className="thinkflow-generate-btn"
                      onClick={handleImportSelected}
                      disabled={importingLinks || fastResults.filter((r) => r.selected).length === 0}
                    >
                      {importingLinks ? <Loader2 size={14} className="is-spinning" /> : <Link size={14} />}
                      导入选中 ({fastResults.filter((r) => r.selected).length})
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {tab === 'deep' ? (
            <div className="thinkflow-add-source-form">
              <label className="thinkflow-add-source-label">研究主题</label>
              <textarea
                className="thinkflow-add-source-textarea"
                placeholder="描述你想深入研究的主题，AI 将自动搜索、分析并生成研究报告作为来源"
                rows={4}
                value={deepTopic}
                onChange={(e) => setDeepTopic(e.target.value)}
                disabled={loading}
              />
              <p className="thinkflow-add-source-hint">深度研究可能需要数分钟，完成后报告将自动添加为来源</p>
              <div className="thinkflow-add-source-actions">
                <button type="button" className="thinkflow-generate-btn" onClick={handleDeepResearch} disabled={loading || !deepTopic.trim()}>
                  {loading ? <Loader2 size={14} className="is-spinning" /> : <Sparkles size={14} />}
                  {loading ? '研究中...' : '开始深度研究'}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
