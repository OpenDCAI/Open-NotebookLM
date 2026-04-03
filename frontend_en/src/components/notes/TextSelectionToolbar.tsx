import React, { useState, useRef, useEffect } from 'react';
import { Sparkles, BookOpen, AlignLeft, ChevronDown, Send, Copy, X } from 'lucide-react';
import { apiFetch } from '../../config/api';
import type { KnowledgeFile } from '../../types';

interface TextSelectionToolbarProps {
  selectedText: string;
  position: { x: number; y: number };
  files: KnowledgeFile[];
  user: any;
  noteMemory: string;
  noteContext: string;
  onDiffResult: (originalText: string, revisedText: string) => void;
  onInsertBelow: (text: string) => void;
  onUpdateMemory: (memory: string) => void;
  onClose: () => void;
}

const POLISH_STYLES = [
  { label: 'Formal', prompt: 'Rewrite the following text in a formal, professional tone. Return only the rewritten text:' },
  { label: 'Casual', prompt: 'Rewrite the following text in a friendly, casual conversational tone. Return only the rewritten text:' },
  { label: 'Concise', prompt: 'Rewrite the following text more concisely, keeping only the essential information. Return only the rewritten text:' },
  { label: 'Academic', prompt: 'Rewrite the following text in a scholarly, academic writing style. Return only the rewritten text:' },
  { label: 'Creative', prompt: 'Rewrite the following text in a more engaging, vivid, and creative style. Return only the rewritten text:' },
];

const ORGANIZE_PRESETS = [
  { label: 'Summarize key points', prompt: 'Summarize the key points of the following text into a structured list:' },
  { label: 'Organize by theme', prompt: 'Organize the following content by main themes with clear section headings:' },
  { label: 'Create bullet points', prompt: 'Convert the following text into a clear, structured bullet-point list:' },
  { label: 'Create an outline', prompt: 'Create a structured hierarchical outline from the following content:' },
  { label: 'Expand and elaborate', prompt: 'Expand on the following text with more detail, examples, and depth:' },
];

type ToolbarMode = 'toolbar' | 'polish' | 'understand' | 'organize' | 'result-understand' | 'result-organize';

export const TextSelectionToolbar: React.FC<TextSelectionToolbarProps> = ({
  selectedText,
  position,
  files,
  user,
  noteMemory,
  noteContext,
  onDiffResult,
  onInsertBelow,
  onUpdateMemory,
  onClose,
}) => {
  const [mode, setMode] = useState<ToolbarMode>('toolbar');
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [customPrompt, setCustomPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [resultText, setResultText] = useState('');
  const toolbarRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    setTimeout(() => document.addEventListener('mousedown', handleMouseDown), 100);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [onClose]);

  const callAI = async (instruction: string): Promise<string> => {
    const selectedFilePaths = files
      .filter(f => selectedFileIds.has(f.id))
      .map(f => f.url)
      .filter((url): url is string => Boolean(url));

    const systemContext = noteMemory
      ? `You are a helpful writing assistant.\n\nContext:\n${noteMemory}`
      : `You are a helpful writing assistant.`;

    const prompt = `${systemContext}\n\n${instruction}\n\n"${selectedText}"\n\nReturn only the processed result without any explanation or preamble.`;

    const res = await apiFetch('/api/v1/kb/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: selectedFilePaths,
        query: prompt,
        history: [],
      }),
    });
    const data = await res.json();
    return data.answer || data.response || 'No response';
  };

  const handlePolish = async (stylePrompt: string, styleName: string) => {
    setLoading(true);
    try {
      const result = await callAI(stylePrompt);
      onDiffResult(selectedText, result);
      // Update memory
      const entry = `- Polish (${styleName}): "${selectedText.slice(0, 60)}..." → "${result.slice(0, 60)}..."`;
      onUpdateMemory(noteMemory ? `${noteMemory}\n${entry}`.slice(-2000) : `## Operations\n${entry}`);
      onClose();
    } catch {
      setLoading(false);
    }
  };

  const handleUnderstand = async () => {
    setMode('understand');
    setLoading(true);
    try {
      const result = await callAI(
        'Please explain and analyze the following text clearly and insightfully. What does it mean? What are the key ideas and implications?'
      );
      setResultText(result);
      setMode('result-understand');
      const entry = `- Understand: "${selectedText.slice(0, 60)}..."`;
      onUpdateMemory(noteMemory ? `${noteMemory}\n${entry}`.slice(-2000) : `## Operations\n${entry}`);
    } catch {
      setResultText('Failed to get AI response.');
      setMode('result-understand');
    } finally {
      setLoading(false);
    }
  };

  const handleOrganize = async (prompt: string) => {
    setLoading(true);
    try {
      const result = await callAI(prompt);
      setResultText(result);
      setMode('result-organize');
      const entry = `- Organize: "${selectedText.slice(0, 60)}..."`;
      onUpdateMemory(noteMemory ? `${noteMemory}\n${entry}`.slice(-2000) : `## Operations\n${entry}`);
    } catch {
      setResultText('Failed to get AI response.');
      setMode('result-organize');
    } finally {
      setLoading(false);
    }
  };

  const toggleFile = (fileId: string) => {
    setSelectedFileIds(prev => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };

  // Clamp position so toolbar stays on screen
  const left = Math.min(Math.max(position.x, 8), window.innerWidth - 320);
  const top = Math.max(position.y - 48, 8);

  const SourceSelector = () =>
    files.length > 0 ? (
      <div className="px-3 py-2 border-b border-gray-100 max-h-32 overflow-y-auto">
        <span className="text-xs text-gray-400 block mb-1">Sources (optional):</span>
        <div className="flex flex-wrap gap-1">
          {files.map(f => (
            <button
              key={f.id}
              onClick={() => toggleFile(f.id)}
              className={`px-2 py-0.5 text-xs rounded-full border transition-all ${
                selectedFileIds.has(f.id)
                  ? 'bg-blue-500 text-white border-blue-500'
                  : 'bg-white text-gray-500 border-gray-200 hover:border-blue-300'
              }`}
            >
              {f.name || f.id}
            </button>
          ))}
        </div>
      </div>
    ) : null;

  return (
    <div
      ref={toolbarRef}
      style={{ position: 'fixed', left, top, zIndex: 1000 }}
      className="bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden min-w-[280px] max-w-[360px]"
    >
      {/* Header */}
      {mode !== 'toolbar' && (
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50">
          <button
            onClick={() => setMode('toolbar')}
            className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            ← Back
          </button>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Main toolbar */}
      {mode === 'toolbar' && (
        <div className="flex items-center gap-0.5 p-1">
          <button
            onClick={() => setMode('polish')}
            className="flex items-center gap-1.5 px-3 py-2 text-sm hover:bg-purple-50 text-purple-600 rounded-lg font-medium transition-colors"
          >
            <Sparkles size={14} /> Polish
          </button>
          <div className="w-px h-5 bg-gray-200" />
          <button
            onClick={handleUnderstand}
            className="flex items-center gap-1.5 px-3 py-2 text-sm hover:bg-blue-50 text-blue-600 rounded-lg font-medium transition-colors"
          >
            <BookOpen size={14} /> Understand
          </button>
          <div className="w-px h-5 bg-gray-200" />
          <button
            onClick={() => setMode('organize')}
            className="flex items-center gap-1.5 px-3 py-2 text-sm hover:bg-green-50 text-green-600 rounded-lg font-medium transition-colors"
          >
            <AlignLeft size={14} /> Organize
          </button>
          <div className="w-px h-5 bg-gray-200" />
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 rounded-lg">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Polish style selection */}
      {mode === 'polish' && (
        <div>
          <SourceSelector />
          <div className="p-1">
            <div className="px-3 py-1.5 text-xs text-gray-400 font-medium uppercase tracking-wider">
              Choose polish style
            </div>
            {POLISH_STYLES.map(s => (
              <button
                key={s.label}
                onClick={() => handlePolish(s.prompt, s.label)}
                disabled={loading}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-purple-50 text-purple-700 rounded-lg disabled:opacity-50 transition-colors"
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Sparkles size={13} className="opacity-60" />
                )}
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Organize options */}
      {mode === 'organize' && (
        <div>
          <SourceSelector />
          <div className="p-1">
            <div className="px-3 py-1.5 text-xs text-gray-400 font-medium uppercase tracking-wider">
              Organize as
            </div>
            {ORGANIZE_PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => handleOrganize(p.prompt)}
                disabled={loading}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-green-50 text-green-700 rounded-lg disabled:opacity-50 transition-colors"
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <AlignLeft size={13} className="opacity-60" />
                )}
                {p.label}
              </button>
            ))}
            <div className="flex gap-1.5 mx-1 mt-1.5">
              <input
                value={customPrompt}
                onChange={e => setCustomPrompt(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && customPrompt.trim() && handleOrganize(customPrompt)}
                placeholder="Custom instruction..."
                className="flex-1 px-2.5 py-1.5 text-xs border border-gray-200 rounded-lg outline-none focus:border-green-400"
              />
              <button
                onClick={() => customPrompt.trim() && handleOrganize(customPrompt)}
                disabled={loading || !customPrompt.trim()}
                className="px-2.5 py-1.5 bg-green-500 text-white rounded-lg text-xs disabled:opacity-40 hover:bg-green-600 transition-colors"
              >
                <Send size={12} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading state for understand */}
      {mode === 'understand' && loading && (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500">
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Analyzing...
        </div>
      )}

      {/* Result: Understand */}
      {mode === 'result-understand' && (
        <div className="p-3 max-w-sm">
          <div className="text-xs font-medium text-blue-500 mb-2 flex items-center gap-1">
            <BookOpen size={12} /> AI Understanding
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap max-h-52 overflow-y-auto leading-relaxed">
            {resultText}
          </div>
          <button
            onClick={() => {
              onInsertBelow(resultText);
              onClose();
            }}
            className="mt-2.5 px-3 py-1.5 bg-green-500 text-white rounded-lg text-xs hover:bg-green-600 flex items-center gap-1 transition-colors"
          >
            <Copy size={12} /> Paste to note
          </button>
        </div>
      )}

      {/* Result: Organize */}
      {mode === 'result-organize' && (
        <div className="p-3 max-w-sm">
          <div className="text-xs font-medium text-green-500 mb-2 flex items-center gap-1">
            <AlignLeft size={12} /> AI Organization
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap max-h-52 overflow-y-auto leading-relaxed">
            {resultText}
          </div>
          <button
            onClick={() => {
              onInsertBelow(resultText);
              onClose();
            }}
            className="mt-2.5 px-3 py-1.5 bg-green-500 text-white rounded-lg text-xs hover:bg-green-600 flex items-center gap-1 transition-colors"
          >
            <Copy size={12} /> Paste to note
          </button>
        </div>
      )}
    </div>
  );
};
