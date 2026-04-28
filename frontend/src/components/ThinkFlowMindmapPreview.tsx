import type { Dispatch, SetStateAction } from 'react';

import type { KnowledgeFile } from '../types';
import { MermaidPreview } from './MermaidPreview';
import type { ThinkFlowOutput } from './thinkflow-types';
import type { ConversationSourceRef } from './useConversationSourceRefs';

type ThinkFlowMindmapPreviewProps = {
  activeOutput: ThinkFlowOutput;
  files: KnowledgeFile[];
  conversationSourceRefs: ConversationSourceRef[];
  resolveFileUrl: (file: Partial<KnowledgeFile>) => string;
  setConversationSourceRefs: Dispatch<SetStateAction<ConversationSourceRef[]>>;
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>;
  persistConversationWorkspaceState: (params: { sourceRefs: ConversationSourceRef[] }) => Promise<any>;
  setCaptureFeedback: (message: string) => void;
  setGlobalError: (message: string) => void;
  setChatInput: (value: string) => void;
};

export function ThinkFlowMindmapPreview({
  activeOutput,
  files,
  conversationSourceRefs,
  resolveFileUrl,
  setConversationSourceRefs,
  setSelectedIds,
  persistConversationWorkspaceState,
  setCaptureFeedback,
  setGlobalError,
  setChatInput,
}: ThinkFlowMindmapPreviewProps) {
  const buildActiveOutputMaterialRefs = (): ConversationSourceRef[] => {
    const matchedFiles = files.filter((file) => {
      const fileUrl = resolveFileUrl(file);
      return (activeOutput.source_paths || []).includes(fileUrl) || (activeOutput.source_names || []).includes(file.name || '');
    });

    const matchedFileIds = new Set(matchedFiles.map((file) => file.id));
    const refsFromFiles = matchedFiles.map((file) => ({
      id: file.id,
      type: 'material' as const,
      title: file.name || '未命名来源',
      path: resolveFileUrl(file),
    }));

    const refsFromSnapshots = (activeOutput.source_paths || [])
      .map((path, index) => ({
        id: path,
        type: 'material' as const,
        title: activeOutput.source_names?.[index] || `来源 ${index + 1}`,
        path,
      }))
      .filter((ref) => ref.path && !matchedFileIds.has(ref.id));

    const deduped = new Map<string, ConversationSourceRef>();
    [...refsFromFiles, ...refsFromSnapshots].forEach((ref) => {
      const key = ref.path || ref.id;
      if (!deduped.has(key)) deduped.set(key, ref);
    });
    return Array.from(deduped.values());
  };

  const handleMindmapNodeClick = (question: string) => {
    const outputSourceRefs = buildActiveOutputMaterialRefs();
    if (outputSourceRefs.length > 0) {
      const existingMaterialKeys = new Set(
        conversationSourceRefs
          .filter((ref) => ref.type === 'material')
          .map((ref) => ref.path || ref.id),
      );
      const mergedRefs = [
        ...conversationSourceRefs,
        ...outputSourceRefs.filter((ref) => !existingMaterialKeys.has(ref.path || ref.id)),
      ];
      if (mergedRefs.length !== conversationSourceRefs.length) {
        setConversationSourceRefs(mergedRefs);
        setSelectedIds(new Set(mergedRefs.filter((ref) => ref.type === 'material').map((ref) => ref.id)));
        const addedCount = mergedRefs.length - conversationSourceRefs.length;
        setCaptureFeedback(`已自动选择该导图的 ${addedCount} 个来源`);
        void persistConversationWorkspaceState({ sourceRefs: mergedRefs }).catch((error: any) => {
          setGlobalError(error?.message || '同步导图来源失败');
        });
      }
    }
    setChatInput(question);
  };

  return (
    <div className="thinkflow-output-preview">
      <MermaidPreview
        mermaidCode={String(activeOutput.result?.mermaid_code || '')}
        title="导图预览"
        onNodeClick={handleMindmapNodeClick}
      />
    </div>
  );
}
