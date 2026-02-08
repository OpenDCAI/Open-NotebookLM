import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Download } from 'lucide-react';

const DRAWIO_ORIGINS = new Set(['https://embed.diagrams.net', 'https://app.diagrams.net']);
const DRAWIO_EXPORT_TIMEOUT_MS = 5000;
const DRAWIO_ANIMATE_STEP_MS = 60;
const DRAWIO_ANIMATE_MAX_CELLS = 240;
const DRAWIO_ANIMATE_LARGE_BATCH = 5;

export interface DrawioInlineEditorProps {
  title?: string;
  subtitle?: string;
  xmlContent: string;
  onXmlChange?: (xml: string) => void;
  height?: string;
  loadingLabel?: string;
  /** 是否使用紧凑样式（适合嵌入卡片/弹窗） */
  compact?: boolean;
  /** 是否最大化：只显示画布，无标题/导出栏，占满父容器 */
  maximized?: boolean;
}

const DrawioInlineEditor: React.FC<DrawioInlineEditorProps> = ({
  title = 'DrawIO',
  subtitle = 'Edit here; export .drawio / .png / .svg',
  xmlContent,
  onXmlChange,
  height = '480px',
  loadingLabel,
  compact = false,
  maximized = false,
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const lastLoadedXmlRef = useRef('');
  const [drawioReady, setDrawioReady] = useState(false);
  const [exportFormat, setExportFormat] = useState<'drawio' | 'png' | 'svg'>('drawio');
  const [exportFilename, setExportFilename] = useState('diagram');
  const [isExporting, setIsExporting] = useState(false);
  const isAnimatingRef = useRef(false);
  const animationTokenRef = useRef(0);
  const pendingExportRef = useRef<{
    resolve: ((data: string) => void) | null;
    reject: ((error: Error) => void) | null;
    format: 'xml' | 'png' | 'svg' | null;
  }>({ resolve: null, reject: null, format: null });

  const postToDrawio = useCallback((payload: Record<string, unknown>) => {
    const frame = iframeRef.current?.contentWindow;
    if (!frame) return;
    frame.postMessage(JSON.stringify(payload), '*');
  }, []);

  const requestDrawioFit = useCallback(() => {
    postToDrawio({ action: 'zoom', zoom: 'fit' });
  }, [postToDrawio]);

  const parseXmlForAnimation = useCallback((xml: string) => {
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(xml, 'text/xml');
      if (doc.querySelector('parsererror')) return null;
      const root =
        doc.querySelector('mxGraphModel > root') ||
        doc.querySelector('root');
      if (!root) return null;

      const rootCells = Array.from(root.children).filter(
        (node) => node.nodeName === 'mxCell'
      ) as Element[];
      if (!rootCells.length) return null;

      const baseCells = rootCells.filter((cell) => {
        const id = cell.getAttribute('id');
        return id === '0' || id === '1';
      });
      const normalCells = rootCells.filter((cell) => {
        const id = cell.getAttribute('id');
        return id !== '0' && id !== '1';
      });
      const nonEdges = normalCells.filter((cell) => cell.getAttribute('edge') !== '1');
      const edges = normalCells.filter((cell) => cell.getAttribute('edge') === '1');
      const orderedCells = [...nonEdges, ...edges];

      return { doc, baseCells, orderedCells };
    } catch {
      return null;
    }
  }, []);

  const buildXmlWithCells = useCallback((sourceDoc: Document, cells: Element[]) => {
    const docClone = sourceDoc.cloneNode(true) as Document;
    const root =
      docClone.querySelector('mxGraphModel > root') ||
      docClone.querySelector('root');
    if (!root) return '';
    while (root.firstChild) {
      root.removeChild(root.firstChild);
    }
    for (const cell of cells) {
      root.appendChild(docClone.importNode(cell, true));
    }
    return new XMLSerializer().serializeToString(docClone);
  }, []);

  const animateDrawioLoad = useCallback(
    async (xml: string) => {
      const parsed = parseXmlForAnimation(xml);
      if (!parsed) {
        postToDrawio({ action: 'load', xml, autosave: 1 });
        lastLoadedXmlRef.current = xml;
        setTimeout(() => requestDrawioFit(), 120);
        return;
      }

      const { doc, baseCells, orderedCells } = parsed;
      const total = orderedCells.length;
      const batchSize =
        total > DRAWIO_ANIMATE_MAX_CELLS ? DRAWIO_ANIMATE_LARGE_BATCH : 1;
      const token = ++animationTokenRef.current;
      isAnimatingRef.current = true;

      for (let i = 0; i < total; i += batchSize) {
        if (animationTokenRef.current !== token) return;
        const subset = orderedCells.slice(0, Math.min(i + batchSize, total));
        const autosave = i + batchSize >= total ? 1 : 0;
        const partialXml = buildXmlWithCells(doc, [...baseCells, ...subset]);
        if (!partialXml) break;
        postToDrawio({ action: 'load', xml: partialXml, autosave });
        setTimeout(() => requestDrawioFit(), 80);
        await new Promise((resolve) => setTimeout(resolve, DRAWIO_ANIMATE_STEP_MS));
      }

      if (animationTokenRef.current === token) {
        lastLoadedXmlRef.current = xml;
        isAnimatingRef.current = false;
        setTimeout(() => requestDrawioFit(), 120);
      }
    },
    [buildXmlWithCells, parseXmlForAnimation, postToDrawio, requestDrawioFit]
  );

  const requestDrawioExport = useCallback(
    (format: 'xml' | 'png' | 'svg') => {
      if (!drawioReady) {
        return Promise.reject(new Error('Draw.io not ready'));
      }

      return new Promise<string>((resolve, reject) => {
        pendingExportRef.current = { resolve, reject, format };
        postToDrawio({ action: 'export', format });
        window.setTimeout(() => {
          if (pendingExportRef.current.resolve === resolve) {
            pendingExportRef.current = { resolve: null, reject: null, format: null };
            reject(new Error('Export timeout'));
          }
        }, DRAWIO_EXPORT_TIMEOUT_MS);
      });
    },
    [drawioReady, postToDrawio]
  );

  const syncXmlFromDrawio = useCallback(async () => {
    if (!drawioReady) return xmlContent;
    try {
      const exported = await requestDrawioExport('xml');
      if (exported && exported.includes('<mxfile')) {
        return exported;
      }
    } catch (e) {
      console.warn('Failed to sync XML from draw.io:', e);
    }
    return xmlContent;
  }, [drawioReady, xmlContent, requestDrawioExport]);

  const downloadXmlFile = useCallback((xml: string, filename: string) => {
    const blob = new Blob([xml], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 100);
  }, []);

  const downloadExportData = useCallback(
    (data: string, format: 'png' | 'svg', filename: string) => {
      let url = '';
      let shouldRevoke = false;
      const trimmed = data.trim();

      if (trimmed.startsWith('data:')) {
        url = trimmed;
      } else if (format === 'png') {
        url = `data:image/png;base64,${trimmed}`;
      } else if (trimmed.startsWith('<svg')) {
        const blob = new Blob([trimmed], { type: 'image/svg+xml' });
        url = URL.createObjectURL(blob);
        shouldRevoke = true;
      } else {
        const blob = new Blob([trimmed], { type: 'image/svg+xml' });
        url = URL.createObjectURL(blob);
        shouldRevoke = true;
      }

      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      if (shouldRevoke) {
        setTimeout(() => URL.revokeObjectURL(url), 100);
      }
    },
    []
  );

  const handleExport = useCallback(async () => {
    if (!xmlContent || isExporting) return;
    setIsExporting(true);

    const trimmedName = exportFilename.trim();
    const safeName = (trimmedName || 'diagram').replace(/[\\/:*?"<>|]/g, '_');

    if (exportFormat === 'drawio') {
      const latestXml = await syncXmlFromDrawio();
      if (latestXml && latestXml.includes('<mxfile')) {
        downloadXmlFile(latestXml, `${safeName}.drawio`);
      }
      setIsExporting(false);
      return;
    }

    try {
      const exportData = await requestDrawioExport(exportFormat);
      if (exportData) {
        downloadExportData(exportData, exportFormat, `${safeName}.${exportFormat}`);
      }
    } catch (e) {
      console.warn('Export failed:', e);
    } finally {
      setIsExporting(false);
    }
  }, [
    xmlContent,
    isExporting,
    exportFormat,
    exportFilename,
    syncXmlFromDrawio,
    downloadXmlFile,
    downloadExportData,
    requestDrawioExport,
  ]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (!DRAWIO_ORIGINS.has(event.origin) || typeof event.data !== 'string') return;
      let message: { event?: string; xml?: string; data?: string } = {};
      try {
        message = JSON.parse(event.data) as { event?: string; xml?: string; data?: string };
      } catch {
        return;
      }

      if (message.event === 'init' || message.event === 'ready') {
        setDrawioReady(true);
        postToDrawio({
          action: 'configure',
          config: {
            sidebar: false,
            format: false,
            layers: false,
            menubar: false,
            toolbar: false,
            status: false,
          },
        });
        return;
      }

      if (
        (message.event === 'save' || message.event === 'autosave') &&
        typeof message.xml === 'string'
      ) {
        if (isAnimatingRef.current) return;
        lastLoadedXmlRef.current = message.xml;
        if (onXmlChange) onXmlChange(message.xml);
        return;
      }

      if (
        message.event === 'export' &&
        pendingExportRef.current.resolve &&
        typeof message.data === 'string'
      ) {
        const resolver = pendingExportRef.current.resolve;
        pendingExportRef.current = { resolve: null, reject: null, format: null };
        resolver(message.data);
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [onXmlChange, postToDrawio]);

  useEffect(() => {
    if (!drawioReady || !xmlContent) return;
    if (xmlContent === lastLoadedXmlRef.current) return;
    animateDrawioLoad(xmlContent);
  }, [drawioReady, xmlContent, animateDrawioLoad]);

  const headerClass = compact
    ? 'flex flex-wrap items-center gap-2 text-gray-700'
    : 'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between';
  const cardClass = compact
    ? 'bg-white border border-gray-200 rounded-xl p-3'
    : 'bg-white border border-gray-200 rounded-xl p-4 shadow-sm';

  if (maximized) {
    return (
      <div className="absolute inset-0 flex flex-col bg-gray-50 overflow-hidden" style={{ minHeight: 0 }}>
        <iframe
          ref={iframeRef}
          src="https://embed.diagrams.net/?embed=1&spin=1&proto=json&autosave=1&saveAndExit=0&noSaveBtn=1&noExitBtn=1&sidebar=0&layers=0&toolbar=0&menubar=0&status=0&format=0"
          className="flex-1 w-full min-h-0 border-0 block"
          style={{ minHeight: 0 }}
          title="draw.io editor"
        />
      </div>
    );
  }

  return (
    <div className={cardClass}>
      <div className={headerClass}>
        <div>
          <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
          {!compact && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`text-xs ${drawioReady ? 'text-teal-600' : 'text-gray-400'}`}
          >
            {drawioReady ? 'Ready' : loadingLabel ?? 'Loading…'}
          </span>
          <select
            value={exportFormat}
            onChange={(e) =>
              setExportFormat(e.target.value as 'drawio' | 'png' | 'svg')
            }
            className="rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-700 focus:ring-2 focus:ring-teal-500/30"
          >
            <option value="drawio">.drawio</option>
            <option value="png">.png</option>
            <option value="svg">.svg</option>
          </select>
          <input
            value={exportFilename}
            onChange={(e) => setExportFilename(e.target.value)}
            className="w-20 rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-700 focus:ring-2 focus:ring-teal-500/30"
            placeholder="diagram"
          />
          <button
            type="button"
            onClick={handleExport}
            disabled={isExporting || !xmlContent}
            className="inline-flex items-center gap-1.5 rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs font-medium text-teal-700 hover:bg-teal-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExporting ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-teal-300 border-t-teal-600" />
            ) : (
              <Download size={14} />
            )}
            Export
          </button>
        </div>
      </div>
      <div
        className="mt-3 overflow-hidden rounded-lg border border-gray-200 bg-gray-50"
        style={{ height }}
      >
        <iframe
          ref={iframeRef}
          src="https://embed.diagrams.net/?embed=1&spin=1&proto=json&autosave=1&saveAndExit=0&noSaveBtn=1&noExitBtn=1&sidebar=0&layers=0&toolbar=0&menubar=0&status=0&format=0"
          className="h-full w-full border-0"
          title="draw.io editor"
        />
      </div>
    </div>
  );
};

export default DrawioInlineEditor;
