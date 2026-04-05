// Knowledge Base Types
export type MaterialType = 'image' | 'doc' | 'video' | 'link' | 'audio' | 'dataset';

export interface KnowledgeFile {
  id: string;
  name: string;
  type: MaterialType;
  url?: string;
  file?: File;
  desc?: string;
  size?: string;
  uploadTime: string;
  isEmbedded?: boolean;
  kbFileId?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  details?: {
    filename: string;
    analysis: string;
  }[];
  sourceMapping?: Record<string, string>;
  sourcePreviewMapping?: Record<string, string>;
  sourceReferenceMapping?: Record<string, {
    fileName: string;
    filePath?: string;
    preview?: string;
    chunkIndex?: number | null;
  }>;
}

export type SectionType = 'library' | 'upload' | 'output' | 'settings';
export type ToolType = 'chat' | 'ppt' | 'mindmap' | 'podcast' | 'video' | 'search' | 'drawio' | 'flashcard' | 'quiz' | 'note' | 'data_extract' | 'table_processing';
