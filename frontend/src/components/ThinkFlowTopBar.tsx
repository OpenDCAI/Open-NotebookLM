import { FolderOpen, History } from 'lucide-react';

type ThinkFlowTopBarProps = {
  notebookTitle: string;
  onBack: () => void;
  onOpenHistory: () => void;
};

export function ThinkFlowTopBar({ notebookTitle, onBack, onOpenHistory }: ThinkFlowTopBarProps) {
  return (
    <div className="thinkflow-topbar">
      <div className="thinkflow-brand" onClick={onBack}>
        <span className="thinkflow-brand-main">Think</span>
        <span className="thinkflow-brand-accent">Flow</span>
      </div>
      <div className="thinkflow-workspace-badge"><FolderOpen size={13} /> {notebookTitle} ▾</div>
      <div className="thinkflow-topbar-spacer" />
      <button type="button" className="thinkflow-topbar-btn" onClick={onOpenHistory}>
        <History size={14} />
        历史
      </button>
    </div>
  );
}
