/**
 * 在 Markdown 源字符串中，将 *snippet* 的首次出现包上一层 ``<mark>``，供 react-markdown + rehype-raw 渲染为正文内高亮。
 *
 * 数据流：``fetchGraphragChunkSnippet`` 得到 chunk 正文 → NotebookView 传入全文 MD 与片段 → 本函数注入 HTML → ReactMarkdown 展示。
 * 内容视为可信（本地 MinerU/索引文件）；片段需与全文字面一致，否则 ``indexOf`` 失败则不注入。
 */
export function injectGraphragHighlightInMarkdown(full: string, snippet: string): string {
  const sn = snippet.trim();
  if (!full || !sn) return full;
  const idx = full.indexOf(sn);
  if (idx < 0) return full;
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return (
    full.slice(0, idx) +
    '<mark class="bg-amber-200/90 rounded px-0.5 ring-1 ring-amber-300/60" data-graphrag-hl="1">' +
    esc(sn) +
    '</mark>' +
    full.slice(idx + sn.length)
  );
}
