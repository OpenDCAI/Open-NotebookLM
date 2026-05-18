import type { ReactNode } from 'react';

type OutputWorkspaceSectionProps = {
  activeOutput: { target_type: string } | null;
  generatingOutline: string | null;
  generatingOutlineLabel: string;
  outputWorkspaceHeader: ReactNode;
  storyboardWorkspace: ReactNode;
  directOutputWorkspace: ReactNode;
  isOutputHeaderCollapsed: boolean;
  onOutputWorkspaceScroll: (scrollTop: number) => void;
};

export function OutputWorkspaceSection({
  activeOutput,
  generatingOutline,
  generatingOutlineLabel,
  outputWorkspaceHeader,
  storyboardWorkspace,
  directOutputWorkspace,
  isOutputHeaderCollapsed,
  onOutputWorkspaceScroll,
}: OutputWorkspaceSectionProps) {
  return (
    <div className="thinkflow-outline-editor">
      {activeOutput ? (
        <>
          {outputWorkspaceHeader}
          {activeOutput.target_type === 'ppt' || activeOutput.target_type === 'video' ? (
            <div
              className={`thinkflow-output-workspace-body ${isOutputHeaderCollapsed ? 'is-header-collapsed' : ''}`}
              data-testid="output-workspace-body"
              onScroll={(event) => onOutputWorkspaceScroll(event.currentTarget.scrollTop)}
            >
              {storyboardWorkspace}
            </div>
          ) : (
            <div
              className={`thinkflow-output-workspace-body is-direct-output ${isOutputHeaderCollapsed ? 'is-header-collapsed' : ''}`}
              data-testid="output-workspace-body"
              onScroll={(event) => onOutputWorkspaceScroll(event.currentTarget.scrollTop)}
            >
              {directOutputWorkspace}
            </div>
          )}
        </>
      ) : generatingOutline ? (
        <div className="thinkflow-empty">正在准备并生成{generatingOutlineLabel || '产出'}...</div>
      ) : (
        <div className="thinkflow-empty">从文档页点击一个产出按钮后，这里会直接显示当前结果工作台。</div>
      )}
    </div>
  );
}
