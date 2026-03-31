import { useEffect, useRef, useState, useCallback } from 'react';
import MindMap from 'simple-mind-map';
import Export from 'simple-mind-map/src/plugins/Export.js';
import { transformMarkdownTo } from 'simple-mind-map/src/parse/markdownTo.js';
import { Download, Expand, Shrink, ZoomIn, ZoomOut, Maximize2, MessageSquare, FileText, Code } from 'lucide-react';
import { mermaidToMarkdown, isMermaidMindmap, markdownToMermaid } from '../../../utils/mermaidToMarkdown';

MindMap.usePlugin(Export);

interface MindMapPreviewProps {
  mermaidCode: string;
  title?: string;
  onNodeClick?: (nodeText: string) => void;
}

export const MindMapPreview = ({ mermaidCode, title = "思维导图预览", onNodeClick }: MindMapPreviewProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mindMapRef = useRef<MindMap | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);
  const [askMenu, setAskMenu] = useState<{ nodeText: string; parentText: string; x: number; y: number } | null>(null);

  const parseData = useCallback(() => {
    if (!mermaidCode) return null;
    try {
      const markdown = isMermaidMindmap(mermaidCode)
        ? mermaidToMarkdown(mermaidCode)
        : mermaidCode;
      return transformMarkdownTo(markdown);
    } catch {
      return null;
    }
  }, [mermaidCode]);

  useEffect(() => {
    if (!containerRef.current || !mermaidCode) return;

    const data = parseData();
    if (!data) {
      setRenderError('解析思维导图数据失败');
      return;
    }

    setRenderError(null);

    if (mindMapRef.current) {
      mindMapRef.current.destroy();
      mindMapRef.current = null;
    }

    try {
      const mm = new MindMap({
        el: containerRef.current,
        data,
        theme: 'default',
        layout: 'logicalStructure',
        scaleRatio: 0.1,
        minZoomRatio: 20,
        maxZoomRatio: 500,
        readonly: true,
        enableFreeDrag: false,
        alwaysShowExpandBtn: true,
        initRootNodePosition: ['center', 'center'],
        exportPaddingX: 50,
        exportPaddingY: 50,
      });

      mindMapRef.current = mm;

      if (onNodeClick) {
        mm.on('node_click', (node: any, e: any) => {
          const text = node?.nodeData?.data?.text;
          if (!text) return;
          setTooltip(null);
          const parentText = node?.parent?.nodeData?.data?.text || '';
          const raw = e?.originEvent || e?.event || e;
          const rect = containerRef.current?.getBoundingClientRect();
          if (rect && raw?.clientX != null) {
            setAskMenu({
              nodeText: text,
              parentText,
              x: raw.clientX - rect.left,
              y: raw.clientY - rect.top,
            });
          } else if (rect) {
            // Fallback: center of container
            setAskMenu({
              nodeText: text,
              parentText,
              x: rect.width / 2,
              y: rect.height / 2,
            });
          }
        });
        mm.on('node_mouseenter', (node: any, e: any) => {
          const text = node?.nodeData?.data?.text;
          if (text) {
            const raw = e?.originEvent || e?.event || e;
            const rect = containerRef.current?.getBoundingClientRect();
            if (rect && raw?.clientX != null) {
              setTooltip({
                text: '点击提问',
                x: raw.clientX - rect.left,
                y: raw.clientY - rect.top - 36,
              });
            }
          }
        });
        mm.on('node_mouseleave', () => {
          setTooltip(null);
        });
      }

      // Only fit on initial render, not on expand/collapse
      let firstRender = true;
      mm.on('node_tree_render_end', () => {
        if (firstRender) {
          firstRender = false;
          setTimeout(() => mm.view.fit(), 100);
        }
      });
    } catch (e: any) {
      console.error('MindMap render error:', e);
      setRenderError(e.message || '渲染思维导图失败');
    }

    return () => {
      if (mindMapRef.current) {
        mindMapRef.current.destroy();
        mindMapRef.current = null;
      }
    };
  }, [mermaidCode, parseData]);

  const handleExpandAll = () => {
    mindMapRef.current?.execCommand('EXPAND_ALL');
  };

  const handleCollapseAll = () => {
    mindMapRef.current?.execCommand('UNEXPAND_ALL');
  };

  const handleZoomIn = () => mindMapRef.current?.view.enlarge();
  const handleZoomOut = () => mindMapRef.current?.view.narrow();
  const handleFit = () => mindMapRef.current?.view.fit();

  const handleDownloadPng = async () => {
    if (!mindMapRef.current) return;
    try {
      // Save current view state
      const viewState = mindMapRef.current.view.getTransformData();
      const fullData = mindMapRef.current.getData();
      // Expand all for export
      mindMapRef.current.execCommand('EXPAND_ALL');
      await new Promise(r => setTimeout(r, 800));
      mindMapRef.current.view.fit();
      await new Promise(r => setTimeout(r, 300));
      await mindMapRef.current.export('png', true, `mindmap_${Date.now()}`);
      // Restore previous state
      mindMapRef.current.setData(fullData);
      await new Promise(r => setTimeout(r, 300));
      mindMapRef.current.view.setTransformData(viewState);
    } catch (e) {
      console.error('PNG export failed:', e);
    }
  };

  const handleDownloadTxt = async () => {
    if (!mindMapRef.current) return;
    try {
      await mindMapRef.current.export('txt', true, `mindmap_${Date.now()}`);
    } catch (e) {
      console.error('TXT export failed:', e);
    }
  };

  const handleDownloadMermaid = () => {
    const mermaid = isMermaidMindmap(mermaidCode)
      ? mermaidCode
      : markdownToMermaid(mermaidCode);
    const blob = new Blob([mermaid], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mindmap_${Date.now()}.mmd`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const btnBase = "px-2.5 py-1.5 rounded-lg text-xs flex items-center gap-1.5 transition-colors";
  const btnGhost = `${btnBase} bg-gray-100 hover:bg-gray-200 border border-gray-200 text-gray-600`;
  const btnAccent = `${btnBase} bg-cyan-50 hover:bg-cyan-100 border border-cyan-200 text-cyan-700`;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-gray-700">{title}</h4>
      </div>

      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button onClick={handleExpandAll} className={btnGhost} title="展开全部">
          <Expand size={14} /> 展开全部
        </button>
        <button onClick={handleCollapseAll} className={btnGhost} title="收缩全部">
          <Shrink size={14} /> 收缩全部
        </button>
        <button onClick={handleZoomIn} className={btnGhost} title="放大">
          <ZoomIn size={14} />
        </button>
        <button onClick={handleZoomOut} className={btnGhost} title="缩小">
          <ZoomOut size={14} />
        </button>
        <button onClick={handleFit} className={btnGhost} title="适应画布">
          <Maximize2 size={14} /> 适应
        </button>

        <div className="w-px h-5 bg-gray-200 mx-1" />

        <button onClick={handleDownloadPng} className={btnAccent} title="下载 PNG（全部展开）">
          <Download size={14} /> PNG
        </button>
        <button onClick={handleDownloadTxt} className={btnAccent} title="下载层级文本">
          <FileText size={14} /> 文本
        </button>
        <button onClick={handleDownloadMermaid} className={btnAccent} title="下载 Mermaid 代码">
          <Code size={14} /> Mermaid
        </button>
      </div>

      {renderError ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <div className="text-red-600 text-sm mb-2">渲染失败</div>
          <div className="text-xs text-red-400">{renderError}</div>
        </div>
      ) : (
        <div className="relative">
          <div
            ref={containerRef}
            className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm"
            style={{ width: '100%', height: '500px', cursor: onNodeClick ? 'pointer' : 'default' }}
          />
          {tooltip && !askMenu && (
            <div
              className="absolute pointer-events-none z-50 px-2.5 py-1.5 bg-gray-800 text-white text-xs rounded-lg shadow-lg whitespace-nowrap"
              style={{ left: tooltip.x, top: tooltip.y, transform: 'translateX(-50%)' }}
            >
              {tooltip.text}
            </div>
          )}
        </div>
      )}

      {/* Ask menu — rendered outside container to avoid overflow clipping */}
      {askMenu && onNodeClick && (
        <>
          <div className="fixed inset-0 z-[100]" onClick={() => setAskMenu(null)} />
          <div
            className="fixed z-[101] w-80 bg-white border border-gray-200 rounded-xl shadow-xl p-2 space-y-1"
            style={{ left: askMenu.x + (containerRef.current?.getBoundingClientRect()?.left || 0), top: askMenu.y + (containerRef.current?.getBoundingClientRect()?.top || 0) + 8 }}
          >
            <div className="px-3 py-1.5 text-xs text-gray-400 font-medium">针对「{askMenu.nodeText}」提问</div>
            <button
              className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-cyan-50 hover:text-cyan-700 rounded-lg transition-colors"
              onClick={() => {
                onNodeClick(`讨论这些来源对「${askMenu.nodeText}」的看法。`);
                setAskMenu(null);
              }}
            >
              <MessageSquare size={14} className="inline mr-2 text-cyan-500" />
              讨论这些来源对「{askMenu.nodeText}」的看法
            </button>
            {askMenu.parentText && (
              <button
                className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-cyan-50 hover:text-cyan-700 rounded-lg transition-colors"
                onClick={() => {
                  onNodeClick(`在更大的「${askMenu.parentText}」背景范畴下，讨论这些来源对「${askMenu.nodeText}」的看法。`);
                  setAskMenu(null);
                }}
              >
                <MessageSquare size={14} className="inline mr-2 text-cyan-500" />
                在「{askMenu.parentText}」背景下，讨论对「{askMenu.nodeText}」的看法
              </button>
            )}
          </div>
        </>
      )}

      <div className="mt-3 text-xs text-gray-400">
        {onNodeClick
          ? '提示：滚轮缩放，拖拽平移。点击节点可发起提问。'
          : '提示：滚轮缩放，拖拽平移。点击节点旁按钮可展开/收缩。'}
      </div>
    </div>
  );
};
