import { ChevronLeft, FileText, PanelRightOpen, Pencil, Target } from 'lucide-react';

import type { ThinkFlowOutput, ThinkFlowOutputButton, WorkspaceMode } from './thinkflow-types';
import { DocumentPanelSection } from './DocumentPanelSection';
import { GuidancePanelSection } from './GuidancePanelSection';
import { OutputWorkspaceSection } from './OutputWorkspaceSection';
import { SummaryPanelSection } from './SummaryPanelSection';

type ThinkFlowRightPanelProps = {
  workspaceMode: WorkspaceMode;
  rightMode: 'summary' | 'doc' | 'guidance' | 'outline';
  activeOutput: ThinkFlowOutput | null;
  activeDocument: any;
  activeGuidance: any;
  activeSummary: any;
  generatingOutline: string | null;
  onExitOutputWorkspace: () => void;
  outputButtons: ThinkFlowOutputButton[];
  setRightMode: (mode: 'summary' | 'doc' | 'guidance' | 'outline') => void;
  onClose: () => void;
  summaryPanelProps: any;
  guidancePanelProps: any;
  documentPanelProps: any;
  outputPanelProps: any;
};

export function ThinkFlowRightPanel({
  workspaceMode,
  rightMode,
  activeOutput,
  onExitOutputWorkspace,
  setRightMode,
  onClose,
  summaryPanelProps,
  guidancePanelProps,
  documentPanelProps,
  outputPanelProps,
}: ThinkFlowRightPanelProps) {
  if (workspaceMode === 'normal') {
    return (
      <aside className="thinkflow-right-panel">
        <div className="thinkflow-right-workbench-head">
          <button type="button" className="thinkflow-collapse-btn" onClick={onClose}>
            <ChevronLeft size={14} />
          </button>
          <span>文档工作台</span>
        </div>
        <DocumentPanelSection {...documentPanelProps} />
      </aside>
    );
  }

  return (
    <aside className={`thinkflow-right-panel ${workspaceMode !== 'normal' ? 'is-output-workspace' : ''}`}>
      <div className="thinkflow-right-mode-bar">
        <button
          type="button"
          className="thinkflow-collapse-btn"
          onClick={() => {
            if (workspaceMode !== 'normal') {
              onExitOutputWorkspace();
              return;
            }
            onClose();
          }}
        >
          <ChevronLeft size={14} />
        </button>
        <button type="button" className={`thinkflow-mode-btn ${rightMode === 'summary' ? 'is-active' : ''}`} onClick={() => setRightMode('summary')}>
          <FileText size={14} />
          摘要
        </button>
        <button type="button" className={`thinkflow-mode-btn ${rightMode === 'doc' ? 'is-active' : ''}`} onClick={() => setRightMode('doc')}>
          <PanelRightOpen size={14} />
          梳理文档
        </button>
        <button type="button" className={`thinkflow-mode-btn ${rightMode === 'guidance' ? 'is-active' : ''}`} onClick={() => setRightMode('guidance')}>
          <Target size={14} />
          产出指导
        </button>
        {activeOutput ? (
          <button type="button" className={`thinkflow-mode-btn ${rightMode === 'outline' ? 'is-active' : ''}`} onClick={() => setRightMode('outline')}>
            <Pencil size={14} />
            {activeOutput.target_type === 'mindmap' ? '导图预览' : '大纲编排'}
          </button>
        ) : null}
      </div>

      {rightMode === 'summary'
        ? <SummaryPanelSection {...summaryPanelProps} />
        : rightMode === 'guidance'
          ? <GuidancePanelSection {...guidancePanelProps} />
          : rightMode === 'doc'
            ? <DocumentPanelSection {...documentPanelProps} />
            : <OutputWorkspaceSection {...outputPanelProps} />}
    </aside>
  );
}
