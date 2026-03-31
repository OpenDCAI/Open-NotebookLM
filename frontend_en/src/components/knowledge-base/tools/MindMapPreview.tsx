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

export const MindMapPreview = ({ mermaidCode, title = "Mind map preview", onNodeClick }: MindMapPreviewProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mindMapRef = useRef<MindMap | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);
  const [askMenu, setAskMenu] = useState<{ nodeText: string; parentText: string; x: number; y: number } | null>(null);

  // Convert input to markdown if needed, then to mind map data
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
      setRenderError('Failed to parse mindmap data');
      return;
    }

    setRenderError(null);

    // Destroy previous instance
    if (mindMapRef.current) {
      mindMapRef.current.destroy();
      mindMapRef.current = null;
      setIsReady(false);
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
        exportPaddingX: 20,
        exportPaddingY: 20,
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
                text: 'Click to ask',
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

      // Fit view after render
      // Only fit on initial render, not on expand/collapse
      let firstRender = true;
      mm.on('node_tree_render_end', () => {
        if (firstRender) {
          firstRender = false;
          setIsReady(true);
          setTimeout(() => mm.view.fit(), 100);
        }
      });
    } catch (e: any) {
      console.error('MindMap render error:', e);
      setRenderError(e.message || 'Failed to render mindmap');
    }

    return () => {
      if (mindMapRef.current) {
        mindMapRef.current.destroy();
        mindMapRef.current = null;
      }
    };
  }, [mermaidCode]);

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
      await new Promise(r => setTimeout(r, 500));
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

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {/* View controls */}
        <button onClick={handleExpandAll} className={btnGhost} title="Expand all">
          <Expand size={14} /> Expand all
        </button>
        <button onClick={handleCollapseAll} className={btnGhost} title="Collapse all">
          <Shrink size={14} /> Collapse all
        </button>
        <button onClick={handleZoomIn} className={btnGhost} title="Zoom in">
          <ZoomIn size={14} />
        </button>
        <button onClick={handleZoomOut} className={btnGhost} title="Zoom out">
          <ZoomOut size={14} />
        </button>
        <button onClick={handleFit} className={btnGhost} title="Fit view">
          <Maximize2 size={14} /> Fit
        </button>

        <div className="w-px h-5 bg-gray-200 mx-1" />

        {/* Export controls */}
        <button onClick={handleDownloadPng} className={btnAccent} title="Download PNG (fully expanded)">
          <Download size={14} /> PNG
        </button>
        <button onClick={handleDownloadTxt} className={btnAccent} title="Download hierarchical text">
          <FileText size={14} /> TXT
        </button>
        <button onClick={handleDownloadMermaid} className={btnAccent} title="Download Mermaid code">
          <Code size={14} /> Mermaid
        </button>
      </div>

      {/* Mind map container */}
      {renderError ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <div className="text-red-600 text-sm mb-2">Render failed</div>
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

      {askMenu && onNodeClick && (
        <>
          <div className="fixed inset-0 z-[100]" onClick={() => setAskMenu(null)} />
          <div
            className="fixed z-[101] w-80 bg-white border border-gray-200 rounded-xl shadow-xl p-2 space-y-1"
            style={{ left: askMenu.x + (containerRef.current?.getBoundingClientRect()?.left || 0), top: askMenu.y + (containerRef.current?.getBoundingClientRect()?.top || 0) + 8 }}
          >
            <div className="px-3 py-1.5 text-xs text-gray-400 font-medium">Ask about "{askMenu.nodeText}"</div>
            <button
              className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-cyan-50 hover:text-cyan-700 rounded-lg transition-colors"
              onClick={() => {
                onNodeClick(`Discuss what these sources say about "${askMenu.nodeText}".`);
                setAskMenu(null);
              }}
            >
              <MessageSquare size={14} className="inline mr-2 text-cyan-500" />
              Discuss what sources say about "{askMenu.nodeText}"
            </button>
            {askMenu.parentText && (
              <button
                className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-cyan-50 hover:text-cyan-700 rounded-lg transition-colors"
                onClick={() => {
                  onNodeClick(`In the broader context of "${askMenu.parentText}", discuss what these sources say about "${askMenu.nodeText}".`);
                  setAskMenu(null);
                }}
              >
                <MessageSquare size={14} className="inline mr-2 text-cyan-500" />
                In context of "{askMenu.parentText}", discuss "{askMenu.nodeText}"
              </button>
            )}
          </div>
        </>
      )}

      <div className="mt-3 text-xs text-gray-400">
        {onNodeClick
          ? 'Tip: Scroll to zoom, drag to pan. Click a node to ask a question about it.'
          : 'Tip: Scroll to zoom, drag to pan. Click the button next to a node to expand/collapse.'}
      </div>
    </div>
  );
};
