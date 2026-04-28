import { useEffect, useRef, useState } from 'react';
import { Code, Download, Expand, FileText, Maximize2, MessageSquare, Shrink, ZoomIn, ZoomOut } from 'lucide-react';
import MindMap from 'simple-mind-map';
import Export from 'simple-mind-map/src/plugins/Export.js';
import { transformMarkdownTo } from 'simple-mind-map/src/parse/markdownTo.js';
import { isMermaidMindmap, markdownToMermaid, mermaidToMarkdown } from '../utils/mermaidToMarkdown';

MindMap.usePlugin(Export);

type MermaidPreviewProps = {
  mermaidCode: string;
  title?: string;
  onNodeClick?: (nodeText: string) => void;
};

type AskMenuState = {
  nodeText: string;
  parentText: string;
  x: number;
  y: number;
};

export function MermaidPreview({ mermaidCode, title = '思维导图预览', onNodeClick }: MermaidPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mindMapRef = useRef<any>(null);
  const onNodeClickRef = useRef(onNodeClick);
  const shouldAutoFitRef = useRef(false);
  const lastRenderedCodeRef = useRef('');
  const [renderError, setRenderError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);
  const [askMenu, setAskMenu] = useState<AskMenuState | null>(null);
  const previewFitPadding = 84;

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    if (!containerRef.current) return;

    try {
      const mindMap = new MindMap({
        el: containerRef.current,
        data: {
          data: {
            text: '思维导图',
          },
          children: [],
        },
        theme: 'default',
        themeConfig: {
          lineColor: '#7dd3fc',
          generalizationLineColor: '#7dd3fc',
          associativeLineActiveColor: '#38bdf8',
          hoverRectColor: '#7dd3fc',
          root: {
            fillColor: '#38bdf8',
            color: '#ffffff',
            borderColor: '#38bdf8',
            borderWidth: 0,
            borderRadius: 14,
            paddingX: 24,
            paddingY: 12,
          },
          second: {
            fillColor: '#f0f9ff',
            color: '#0284c7',
            borderColor: '#7dd3fc',
            borderWidth: 1,
            borderRadius: 12,
            paddingX: 18,
            paddingY: 10,
          },
          node: {
            fillColor: '#ffffff',
            color: '#111827',
            borderColor: '#bae6fd',
            borderWidth: 1,
            borderRadius: 10,
            paddingX: 16,
            paddingY: 8,
          },
          generalization: {
            fillColor: '#f0f9ff',
            color: '#0284c7',
            borderColor: '#7dd3fc',
            borderWidth: 1,
            borderRadius: 12,
          },
        },
        layout: 'logicalStructure',
        scaleRatio: 0.1,
        minZoomRatio: 20,
        maxZoomRatio: 500,
        readonly: true,
        enableFreeDrag: false,
        alwaysShowExpandBtn: true,
        initRootNodePosition: ['center', 'center'],
        fitPadding: previewFitPadding,
        exportPaddingX: 50,
        exportPaddingY: 50,
      });

      mindMapRef.current = mindMap;

      mindMap.on('node_tree_render_end', () => {
        if (!shouldAutoFitRef.current) return;
        shouldAutoFitRef.current = false;
        setTimeout(() => mindMap.view.fit(undefined, false, previewFitPadding), 80);
      });

      mindMap.on('node_click', (node: any, event: any) => {
        if (!onNodeClickRef.current) return;
        const text = node?.nodeData?.data?.text;
        if (!text) return;
        setTooltip(null);
        const parentText = node?.parent?.nodeData?.data?.text || '';
        const raw = event?.originEvent || event?.event || event;
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect && raw?.clientX != null) {
          setAskMenu({
            nodeText: text,
            parentText,
            x: raw.clientX - rect.left,
            y: raw.clientY - rect.top,
          });
        } else if (rect) {
          setAskMenu({
            nodeText: text,
            parentText,
            x: rect.width / 2,
            y: rect.height / 2,
          });
        }
      });

      mindMap.on('node_mouseenter', (node: any, event: any) => {
        if (!onNodeClickRef.current) return;
        const text = node?.nodeData?.data?.text;
        if (!text) return;
        const raw = event?.originEvent || event?.event || event;
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect && raw?.clientX != null) {
          setTooltip({
            text: '点击提问',
            x: raw.clientX - rect.left,
            y: raw.clientY - rect.top - 36,
          });
        }
      });

      mindMap.on('node_mouseleave', () => {
        setTooltip(null);
      });

      const resizeObserver = new ResizeObserver(() => {
        mindMapRef.current?.resize();
      });
      resizeObserver.observe(containerRef.current);

      return () => {
        resizeObserver.disconnect();
        if (mindMapRef.current) {
          mindMapRef.current.destroy();
          mindMapRef.current = null;
        }
      };
    } catch (error: any) {
      setRenderError(error?.message || '渲染思维导图失败');
    }
  }, []);

  useEffect(() => {
    if (!mindMapRef.current || !mermaidCode) return;
    try {
      const markdown = isMermaidMindmap(mermaidCode) ? mermaidToMarkdown(mermaidCode) : mermaidCode;
      const data = transformMarkdownTo(markdown);
      setRenderError(null);
      setTooltip(null);
      setAskMenu(null);
      shouldAutoFitRef.current = mermaidCode !== lastRenderedCodeRef.current;
      lastRenderedCodeRef.current = mermaidCode;
      mindMapRef.current.setData(data);
    } catch {
      setRenderError('解析思维导图数据失败');
    }
  }, [mermaidCode]);

  const handleExpandAll = () => {
    mindMapRef.current?.execCommand('EXPAND_ALL');
  };

  const handleCollapseAll = () => {
    mindMapRef.current?.execCommand('UNEXPAND_ALL');
  };

  const handleZoomIn = () => mindMapRef.current?.view.enlarge();
  const handleZoomOut = () => mindMapRef.current?.view.narrow();
  const handleFit = () => mindMapRef.current?.view.fit(undefined, false, previewFitPadding);

  const handleDownloadPng = async () => {
    if (!mindMapRef.current) return;
    try {
      const viewState = mindMapRef.current.view.getTransformData();
      const fullData = mindMapRef.current.getData();
      mindMapRef.current.execCommand('EXPAND_ALL');
      await new Promise((resolve) => setTimeout(resolve, 800));
      mindMapRef.current.view.fit(undefined, false, previewFitPadding);
      await new Promise((resolve) => setTimeout(resolve, 300));
      await mindMapRef.current.export('png', true, `mindmap_${Date.now()}`);
      mindMapRef.current.setData(fullData);
      await new Promise((resolve) => setTimeout(resolve, 300));
      mindMapRef.current.view.setTransformData(viewState);
    } catch {
      // keep preview usable even if export fails
    }
  };

  const handleDownloadTxt = async () => {
    if (!mindMapRef.current) return;
    try {
      await mindMapRef.current.export('txt', true, `mindmap_${Date.now()}`);
    } catch {
      // keep preview usable even if export fails
    }
  };

  const handleDownloadMermaid = () => {
    const normalized = isMermaidMindmap(mermaidCode) ? mermaidCode : markdownToMermaid(mermaidCode);
    const blob = new Blob([normalized], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mindmap_${Date.now()}.mmd`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const btnBase = 'flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] transition-colors';
  const btnGhost = `${btnBase} border border-sky-200 bg-white text-sky-700 shadow-sm hover:bg-sky-50`;
  const btnAccent = `${btnBase} border border-sky-200 bg-sky-50 text-sky-700 shadow-sm hover:bg-sky-100`;

  return (
    <div className="px-6 pb-5 pt-4">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-gray-700">{title}</h4>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button type="button" onClick={handleExpandAll} className={btnGhost} title="展开全部">
          <Expand size={12} />
          展开全部
        </button>
        <button type="button" onClick={handleCollapseAll} className={btnGhost} title="收缩全部">
          <Shrink size={12} />
          收缩全部
        </button>
        <button type="button" onClick={handleZoomIn} className={btnGhost} title="放大">
          <ZoomIn size={12} />
        </button>
        <button type="button" onClick={handleZoomOut} className={btnGhost} title="缩小">
          <ZoomOut size={12} />
        </button>
        <button type="button" onClick={handleFit} className={btnGhost} title="适应画布">
          <Maximize2 size={12} />
          适应
        </button>

        <div className="mx-1 h-5 w-px bg-gray-200" />

        <button type="button" onClick={() => void handleDownloadPng()} className={btnAccent} title="下载 PNG（全部展开）">
          <Download size={12} />
          PNG
        </button>
        <button type="button" onClick={() => void handleDownloadTxt()} className={btnAccent} title="下载层级文本">
          <FileText size={12} />
          文本
        </button>
        <button type="button" onClick={handleDownloadMermaid} className={btnAccent} title="下载 Mermaid 代码">
          <Code size={12} />
          Mermaid
        </button>
      </div>

      {renderError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <div className="mb-2 text-sm text-red-600">渲染失败</div>
          <div className="text-xs text-red-400">{renderError}</div>
        </div>
      ) : (
        <div className="relative rounded-2xl border border-gray-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.98))] p-3 shadow-sm">
          <div
            ref={containerRef}
            className="overflow-hidden rounded-xl border border-gray-200 bg-white"
            style={{
              width: '100%',
              height: '500px',
              cursor: onNodeClick ? 'pointer' : 'default',
            }}
          />
          {tooltip && !askMenu ? (
            <div
              className="pointer-events-none absolute z-50 whitespace-nowrap rounded-lg bg-gray-800 px-2.5 py-1.5 text-xs text-white shadow-lg"
              style={{ left: tooltip.x, top: tooltip.y, transform: 'translateX(-50%)' }}
            >
              {tooltip.text}
            </div>
          ) : null}
        </div>
      )}

      {askMenu && onNodeClick ? (
        <>
          <div className="fixed inset-0 z-[100]" onClick={() => setAskMenu(null)} />
          <div
            className="fixed z-[101] w-80 space-y-1 rounded-xl border border-sky-100 bg-white p-2 shadow-xl"
            style={{
              left: askMenu.x + (containerRef.current?.getBoundingClientRect()?.left || 0),
              top: askMenu.y + (containerRef.current?.getBoundingClientRect()?.top || 0) + 8,
            }}
          >
            <div className="px-3 py-1.5 text-xs font-medium text-gray-400">针对「{askMenu.nodeText}」提问</div>
            <button
              type="button"
              className="w-full rounded-lg px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-cyan-50 hover:text-cyan-700"
              onClick={() => {
                onNodeClick(`根据来源，展开说明「${askMenu.nodeText}」。`);
                setAskMenu(null);
              }}
            >
              <MessageSquare size={14} className="mr-2 inline text-cyan-500" />
              根据来源，展开说明「{askMenu.nodeText}」
            </button>
            {askMenu.parentText ? (
              <button
                type="button"
                className="w-full rounded-lg px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-cyan-50 hover:text-cyan-700"
                onClick={() => {
                  onNodeClick(`在「${askMenu.parentText}」背景下，根据来源展开说明「${askMenu.nodeText}」。`);
                  setAskMenu(null);
                }}
              >
                <MessageSquare size={14} className="mr-2 inline text-cyan-500" />
                在「{askMenu.parentText}」背景下，根据来源展开说明「{askMenu.nodeText}」
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      <div className="mt-3 text-xs text-gray-400">
        {onNodeClick ? '提示：点击拖拽，Ctrl+滚轮缩放，点击节点并发起提问并自动选中来源。' : '提示：滚轮缩放，点击节点旁按钮可展开/收缩。'}
      </div>
    </div>
  );
}
