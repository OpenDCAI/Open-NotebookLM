import { FolderOpen } from 'lucide-react';

type ThinkFlowTopBarProps = {
  notebookTitle: string;
  onBack: () => void;
};

export function ThinkFlowTopBar({ notebookTitle, onBack }: ThinkFlowTopBarProps) {
  return (
    <div className="thinkflow-topbar">
      <div className="thinkflow-brand" onClick={onBack}>
        <span className="thinkflow-brand-main">Think</span>
        <span className="thinkflow-brand-accent">Flow</span>
      </div>
      <div className="thinkflow-workspace-badge"><FolderOpen size={13} /> {notebookTitle} ▾</div>
      <div className="thinkflow-topbar-spacer" />
    </div>
  );
}
