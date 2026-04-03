import React, { useState, useRef, useEffect } from 'react';
import { Bot, Send, X, ChevronDown, ChevronUp, Copy } from 'lucide-react';
import { apiFetch } from '../../config/api';
import { Badge, BadgeGroup } from '../ui';
import type { KnowledgeFile } from '../../types';

interface AIPanelProps {
  blockId: string;
  files: KnowledgeFile[];
  user: any;
  notebook?: any;
  noteContext: string;
  noteMemory: string;
  onInsertText: (text: string, blockId: string) => void;
  onClose: () => void;
  onUpdateMemory: (memory: string) => void;
}

const ORGANIZE_PRESETS = [
  { label: 'Summarize key points', value: 'Summarize the key points from the context into a concise, well-structured list.' },
  { label: 'Organize by theme', value: 'Organize the content by main themes and create clearly structured sections.' },
  { label: 'Create outline', value: 'Create a clear hierarchical outline from the provided content.' },
  { label: 'Extract action items', value: 'Extract all action items, tasks, and next steps from the content.' },
  { label: 'Generate FAQ', value: 'Generate a helpful FAQ list based on the content with clear questions and answers.' },
  { label: 'Expand on this', value: 'Expand on and develop the ideas in this content with more detail and depth.' },
];

export const AIPanel: React.FC<AIPanelProps> = ({
  blockId,
  files,
  user,
  notebook,
  noteContext,
  noteMemory,
  onInsertText,
  onClose,
  onUpdateMemory,
}) => {
  // Default: select all files
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(
    new Set(files.map(f => f.id))
  );
  const [inputText, setInputText] = useState('');
  const [showPresets, setShowPresets] = useState(false);
  const [aiResponse, setAiResponse] = useState('');
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-select newly added files
  useEffect(() => {
    setSelectedFileIds(prev => {
      const newIds = new Set(prev);
      files.forEach(f => {
        if (!prev.has(f.id)) {
          newIds.add(f.id);
        }
      });
      return newIds;
    });
  }, [files]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const toggleFile = (fileId: string) => {
    setSelectedFileIds(prev => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };

  const handleAsk = async () => {
    if (!inputText.trim()) return;
    setLoading(true);
    setAiResponse('');
    try {
      const selectedFilePaths = files
        .filter(f => selectedFileIds.has(f.id))
        .map(f => f.url)
        .filter((url): url is string => Boolean(url));

      // Build prompt with memory as system context
      const systemContext = noteMemory
        ? `You are a helpful note-taking assistant.\n\nNote context and history:\n${noteMemory}`
        : `You are a helpful note-taking assistant helping the user write and organize their notes.`;

      const noteContextPart = noteContext
        ? `\n\nCurrent note content:\n${noteContext.slice(0, 800)}`
        : '';

      const fullPrompt = `${systemContext}${noteContextPart}\n\nUser request: ${inputText}\n\nProvide a helpful, well-structured response that can be directly inserted into the note.`;

      const res = await apiFetch('/api/v1/kb/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: selectedFilePaths,
          query: fullPrompt,
          history: [],
          email: user?.email || user?.id || undefined,
          notebook_id: notebook?.id || undefined,
        }),
      });
      const data = await res.json();
      const response = data.answer || data.response || 'No response';
      setAiResponse(response);

      // Update memory with this operation
      const memoryEntry = `- AI request: "${inputText.slice(0, 80)}"\n  Response summary: "${response.slice(0, 150)}..."`;
      if (!noteMemory) {
        const baseMemory = `## Note Context\n${noteContext.slice(0, 500)}\n\n## Operations History\n${memoryEntry}`;
        onUpdateMemory(baseMemory);
      } else {
        onUpdateMemory(`${noteMemory}\n${memoryEntry}`.slice(-2000));
      }
    } catch {
      setAiResponse('Failed to get AI response. Please check your API settings.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-1 border border-accent-200 bg-accent-50/40 rounded-xl p-3 shadow-sm">
      {/* Source file selection - horizontal, small text */}
      {files.length > 0 && (
        <BadgeGroup className="mb-2.5 max-h-24 overflow-y-auto">
          <span className="text-xs text-neutral-500 shrink-0 font-medium">Sources:</span>
          {files.map(f => (
            <button
              key={f.id}
              onClick={() => toggleFile(f.id)}
              className="focus:outline-none"
            >
              <Badge
                variant={selectedFileIds.has(f.id) ? 'accent' : 'default'}
                size="sm"
                className="cursor-pointer hover:opacity-80 transition-opacity"
              >
                {f.name || f.id}
              </Badge>
            </button>
          ))}
        </BadgeGroup>
      )}

      {/* Input area */}
      <div className="flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleAsk();
            }
            if (e.key === 'Escape') onClose();
          }}
          placeholder="Ask AI to help write, organize, or expand your notes..."
          className="flex-1 px-3 py-2 text-sm border border-neutral-200 rounded-lg outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20 resize-none bg-white transition-all"
          rows={1}
          onInput={e => {
            e.currentTarget.style.height = 'auto';
            e.currentTarget.style.height = e.currentTarget.scrollHeight + 'px';
          }}
        />
        <div className="flex gap-1 shrink-0">
          <button
            onClick={() => setShowPresets(!showPresets)}
            className="p-2 text-neutral-400 hover:text-neutral-600 hover:bg-neutral-50 rounded-lg transition-colors"
            title="Preset prompts"
          >
            {showPresets ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          <button
            onClick={handleAsk}
            disabled={loading || !inputText.trim()}
            className="p-2 bg-accent-500 text-white rounded-lg hover:bg-accent-600 disabled:opacity-40 transition-colors shadow-sm"
          >
            {loading ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send size={16} />
            )}
          </button>
          <button
            onClick={onClose}
            className="p-2 text-neutral-400 hover:text-neutral-600 hover:bg-neutral-50 rounded-lg transition-colors"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Preset prompts dropdown */}
      {showPresets && (
        <div className="mt-1.5 border border-neutral-200 bg-white rounded-lg shadow-sm overflow-hidden">
          {ORGANIZE_PRESETS.map(p => (
            <button
              key={p.label}
              onClick={() => {
                setInputText(p.value);
                setShowPresets(false);
                textareaRef.current?.focus();
              }}
              className="w-full px-3 py-2 text-sm text-left hover:bg-accent-50 text-neutral-700 border-b border-neutral-100 last:border-0 transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {/* AI Response */}
      {aiResponse && !loading && (
        <div className="mt-2.5 p-3 bg-white rounded-lg border border-neutral-200 text-sm">
          <div className="flex items-center gap-1 text-xs text-accent-600 font-medium mb-1.5">
            <Bot size={12} /> AI Response
          </div>
          <p className="text-neutral-700 whitespace-pre-wrap leading-relaxed">{aiResponse}</p>
          <button
            onClick={() => {
              onInsertText(aiResponse, blockId);
              onClose();
            }}
            className="mt-2 px-3 py-1.5 bg-success-500 text-white rounded-lg text-xs hover:bg-success-600 flex items-center gap-1 transition-colors shadow-sm"
          >
            <Copy size={12} /> Paste to note
          </button>
        </div>
      )}
    </div>
  );
};
