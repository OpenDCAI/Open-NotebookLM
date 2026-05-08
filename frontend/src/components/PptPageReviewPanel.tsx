import React from 'react';
import { ArrowRight, CheckCircle2, ChevronLeft, Download, RefreshCw } from 'lucide-react';
import { PptLockedOutlinePreview } from './PptOutlinePanel';
import { getPptStageLabel } from './usePptOutlineManager';

// ---- Local type aliases (mirrors ThinkFlowWorkspace.tsx) ----

type PptPipelineStage = 'outline_ready' | 'pages_ready' | 'generated';

type OutlineSection = {
  id: string;
  pageNum?: number;
  title: string;
  summary?: string;
  bullets?: string[];
  layout_description?: string;
  key_points?: string[];
  asset_ref?: string | null;
  ppt_img_path?: string;
  generated_img_path?: string;
  generation_failed?: boolean;
  generation_error?: string;
  mode?: string;
};

type PptPageReview = {
  page_index: number;
  page_num?: number;
  confirmed: boolean;
  confirmed_at?: string;
  updated_at?: string;
};

type PptPageVersion = {
  id: string;
  page_index: number;
  page_num?: number;
  title?: string;
  source?: string;
  prompt?: string;
  preview_path?: string;
  selected?: boolean;
  created_at: string;
};

type ThinkFlowOutput = {
  id: string;
  document_id: string;
  title: string;
  target_type: string;
  status: string;
  pipeline_stage?: string;
  prompt?: string;
  page_count?: number;
  outline?: OutlineSection[];
  result?: Record<string, any>;
  enable_images?: boolean;
  updated_at: string;
  created_at: string;
  [key: string]: any;
};

// ---- PptStageRail (shared sub-component) ----

type PptStageRailProps = {
  activePptStage: PptPipelineStage;
};

export function PptStageRail({ activePptStage }: PptStageRailProps) {
  const steps: Array<{ key: PptPipelineStage; label: string }> = [
    { key: 'outline_ready', label: '大纲确认' },
    { key: 'pages_ready', label: '逐页生成确认' },
    { key: 'generated', label: '生成结果' },
  ];
  const currentIndex = steps.findIndex((step) => step.key === activePptStage);
  return (
    <div className="thinkflow-ppt-stage-rail">
      {steps.map((step, index) => (
        <div
          key={step.key}
          className={`thinkflow-ppt-stage-pill ${activePptStage === step.key ? 'is-active' : ''} ${index < currentIndex ? 'is-complete' : ''}`}
        >
          <span>{index + 1}</span>
          <strong>{step.label}</strong>
        </div>
      ))}
    </div>
  );
}

// ---- PptPageReviewPanel ----

export type PptPageReviewPanelProps = {
  activeOutput: ThinkFlowOutput;
  activePptStage: PptPipelineStage;
  activePptPreviewImages: string[];
  activePptSlide: { slide: OutlineSection; index: number } | null;
  activePptConfirmedCount: number;
  activePptPageVersions: PptPageVersion[];
  activePptCurrentPreview: string;
  activePptCurrentReview: PptPageReview | null;
  pptOutlineReadonlyOpen: boolean;
  pptPagePrompt: string;
  pptPageBusyAction: string;
  pptPageStatus: string;
  generatingOutput: boolean;
  onSetPptOutlineReadonlyOpen: React.Dispatch<React.SetStateAction<boolean>>;
  onSetPptPagePrompt: React.Dispatch<React.SetStateAction<string>>;
  onSetActivePptSlideIndex: React.Dispatch<React.SetStateAction<number>>;
  onGenerateOutputById: (id: string) => Promise<void>;
  onRegenerateActivePptPage: () => Promise<void>;
  onConfirmActivePptPage: () => Promise<void>;
  renderOutputPreview: () => React.ReactNode;
  onRevert?: () => void;
  onGenerate?: () => void;
  allConfirmed?: boolean;
};

export function PptPageReviewPanel({
  activeOutput,
  activePptStage,
  activePptPreviewImages,
  activePptSlide,
  activePptConfirmedCount,
  activePptPageVersions,
  activePptCurrentPreview,
  activePptCurrentReview,
  pptOutlineReadonlyOpen,
  pptPagePrompt,
  pptPageBusyAction,
  pptPageStatus,
  generatingOutput,
  onSetPptOutlineReadonlyOpen,
  onSetPptPagePrompt,
  onSetActivePptSlideIndex,
  onGenerateOutputById,
  onRegenerateActivePptPage,
  onConfirmActivePptPage,
  renderOutputPreview,
  onRevert,
  onGenerate,
  allConfirmed,
}: PptPageReviewPanelProps) {
  const hasDraftPages = activePptPreviewImages.some(Boolean);
  const currentSlideFailed = Boolean(activePptSlide?.slide.generation_failed || (activePptSlide?.slide.mode || '').includes('failed'));
  const totalSlides = (activeOutput.outline || []).length || activeOutput.page_count || 0;
  const currentPageNumber = activePptSlide?.slide.pageNum || (activePptSlide?.index ?? 0) + 1;

  return (
    <>
      <PptStageRail activePptStage={activePptStage} />
      <div className="thinkflow-ppt-stage-header">
        <div className="thinkflow-ppt-stage-copy">
          <h4>{getPptStageLabel(activePptStage)}</h4>
          <p>大纲已经确认完成。先生成每页结果，再逐页核对、改单页并确认通过；这一步不再支持改大纲。</p>
        </div>
        <div className="thinkflow-ppt-stage-actions">
          <button
            type="button"
            className="thinkflow-doc-action-btn"
            onClick={() => onSetPptOutlineReadonlyOpen((previous) => !previous)}
          >
            {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
          </button>
          <button type="button" className="thinkflow-generate-btn" onClick={() => void onGenerateOutputById(activeOutput.id)} disabled={generatingOutput}>
            {generatingOutput ? '生成页面结果中...' : hasDraftPages ? '重新生成每页结果' : '生成每页结果'}
          </button>
        </div>
      </div>
      <PptLockedOutlinePreview
        activeOutput={activeOutput}
        pptOutlineReadonlyOpen={pptOutlineReadonlyOpen}
        onSetPptOutlineReadonlyOpen={onSetPptOutlineReadonlyOpen}
      />
      <div className="thinkflow-ppt-generation-review">
        <div className="thinkflow-ppt-generation-card">
          <span className="thinkflow-ppt-generation-label">页面规模</span>
          <strong>{totalSlides} 页</strong>
        </div>
        <div className="thinkflow-ppt-generation-card">
          <span className="thinkflow-ppt-generation-label">确认进度</span>
          <strong>
            {activePptConfirmedCount} / {totalSlides}
          </strong>
        </div>
        <div className="thinkflow-ppt-generation-toggle is-readonly">
          <span>{activeOutput.enable_images !== false ? '已开启' : '已关闭'}</span>
          <strong>来源素材与自动插图 / 生图</strong>
        </div>
        <div className="thinkflow-ppt-generation-note">
          该配置已在确认大纲时锁定。若需修改，请新建一份新的 PPT 产出。
        </div>
        {pptPageStatus ? <div className="thinkflow-ppt-page-toast">{pptPageStatus}</div> : null}
      </div>
      {hasDraftPages ? (
        <div className="thinkflow-ppt-review-shell">
          <div className="thinkflow-ppt-review-main">
            {renderOutputPreview()}
            <div className="thinkflow-ppt-review-actions">
              <div className="thinkflow-ppt-review-copy">
                <span className="thinkflow-output-workspace-kicker">单页修改</span>
                <h4>第 {currentPageNumber} 页核对与改单页</h4>
                <p>这一页如果不对，就直接补一句修改要求，让模型只重做当前页。重做完成后会进入当前页历史版本，你可以切回旧版本再确认。</p>
              </div>
              <textarea
                className="thinkflow-outline-textarea"
                value={pptPagePrompt}
                onChange={(event) => onSetPptPagePrompt(event.target.value)}
                placeholder="例如：这页不要讲方法细节，改成问题背景 + 核心结论；配图换成更简洁的结构图。"
                rows={3}
              />
              <div className="thinkflow-ppt-review-btn-row">
                <button
                  type="button"
                  className="thinkflow-doc-action-btn"
                  onClick={() => onSetActivePptSlideIndex((previous) => Math.max(previous - 1, 0))}
                  disabled={(activePptSlide?.index ?? 0) === 0 || pptPageBusyAction !== '' || generatingOutput}
                >
                  <ChevronLeft size={14} />
                  上一页
                </button>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn"
                  onClick={() =>
                    onSetActivePptSlideIndex((previous) =>
                      Math.min(previous + 1, Math.max((activeOutput.outline || []).length - 1, 0)),
                    )
                  }
                  disabled={
                    (activePptSlide?.index ?? 0) >= Math.max((activeOutput.outline || []).length - 1, 0) ||
                    pptPageBusyAction !== '' ||
                    generatingOutput
                  }
                >
                  下一页
                  <ArrowRight size={14} />
                </button>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn is-active"
                  onClick={() => void onRegenerateActivePptPage()}
                  disabled={!pptPagePrompt.trim() || pptPageBusyAction !== '' || generatingOutput}
                >
                  <RefreshCw size={14} className={pptPageBusyAction === 'regenerate' ? 'is-spinning' : ''} />
                  {pptPageBusyAction === 'regenerate' ? '当前页重生成中...' : '按提示重做当前页'}
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void onConfirmActivePptPage()}
                  disabled={!activePptCurrentPreview || currentSlideFailed || pptPageBusyAction !== '' || generatingOutput}
                >
                  <CheckCircle2 size={14} />
                  {pptPageBusyAction === 'confirm'
                    ? '确认中...'
                    : (activePptSlide?.index ?? 0) >= Math.max((activeOutput.outline || []).length - 1, 0)
                      ? '确认当前页并完成'
                      : '确认当前页并继续'}
                </button>
              </div>
              <div className="thinkflow-ppt-inline-feedback">
                {pptPageBusyAction === 'regenerate' ? '正在调用后端重做当前页，请稍候...' : null}
                {pptPageBusyAction === 'select_version' ? '正在切换历史版本，请稍候...' : null}
                {currentSlideFailed ? '当前页上一次生成失败，先重新生成该页或整套页面，再确认。' : null}
                {!pptPageBusyAction && activePptPageVersions.length > 0 ? `当前页已有 ${activePptPageVersions.length} 个历史版本，可在预览图下方直接切换。` : null}
              </div>
              {activePptCurrentReview?.confirmed ? (
                <div className="thinkflow-ppt-page-toast is-confirmed">当前页已经确认通过，你也可以继续重做。</div>
              ) : null}
            </div>
          </div>
        </div>
      ) : (
        <div className="thinkflow-ppt-draft-empty">
          <div className="thinkflow-empty">
            这一步还没有页面草稿。左侧是刚刚确认的 PPT 大纲，先生成一版整套页图，再逐页查看、改单页、确认通过。
          </div>
        </div>
      )}
      <div className="thinkflow-outline-footer">
        <div className="thinkflow-outline-actions">
          <button
            type="button"
            className="thinkflow-doc-action-btn"
            onClick={() => onSetPptOutlineReadonlyOpen((previous) => !previous)}
          >
            {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
          </button>
          <button type="button" className="thinkflow-generate-btn" onClick={() => void onGenerateOutputById(activeOutput.id)} disabled={generatingOutput}>
            {generatingOutput ? '生成页面结果中...' : hasDraftPages ? '重新生成每页结果' : '生成每页结果'}
          </button>
        </div>
      </div>
      <div className="tf-page-review-actions">
        <button
          className="tf-page-review-actions__revert"
          onClick={() => {
            if (window.confirm('返回大纲编辑将保留当前页面为历史版本，确定继续？')) {
              onRevert?.();
            }
          }}
        >
          ← 返回大纲编辑
        </button>
        <button
          className="thinkflow-ppt-confirm-btn"
          onClick={onGenerate}
          disabled={!allConfirmed}
          style={{ padding: '5px 16px', borderRadius: 6, fontSize: 12, fontWeight: 500 }}
        >
          生成 PPT
        </button>
      </div>
    </>
  );
}

// ---- PptGeneratedResultPanel ----

export type PptGeneratedResultPanelProps = {
  activeOutput: ThinkFlowOutput;
  activePptStage: PptPipelineStage;
  pptOutlineReadonlyOpen: boolean;
  onSetPptOutlineReadonlyOpen: React.Dispatch<React.SetStateAction<boolean>>;
  onImportOutputToSource: () => Promise<void>;
  renderOutputPreview: () => React.ReactNode;
};

export function PptGeneratedResultPanel({
  activeOutput,
  activePptStage,
  pptOutlineReadonlyOpen,
  onSetPptOutlineReadonlyOpen,
  onImportOutputToSource,
  renderOutputPreview,
}: PptGeneratedResultPanelProps) {
  return (
    <>
      <PptStageRail activePptStage={activePptStage} />
      <div className="thinkflow-ppt-stage-header">
        <div className="thinkflow-ppt-stage-copy">
          <h4>{getPptStageLabel(activePptStage)}</h4>
          <p>全部页面都已确认通过，当前 PPT 产出状态已经确定。这里主要用于预览、下载和回流来源。</p>
        </div>
        <div className="thinkflow-ppt-stage-actions">
          <button
            type="button"
            className="thinkflow-doc-action-btn"
            onClick={() => onSetPptOutlineReadonlyOpen((previous) => !previous)}
          >
            {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
          </button>
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => void onImportOutputToSource()}>
            回流来源
          </button>
        </div>
      </div>
      <PptLockedOutlinePreview
        activeOutput={activeOutput}
        pptOutlineReadonlyOpen={pptOutlineReadonlyOpen}
        onSetPptOutlineReadonlyOpen={onSetPptOutlineReadonlyOpen}
      />
      <div className="thinkflow-outline-footer">
        <div className="thinkflow-outline-preview">{renderOutputPreview()}</div>
        {activeOutput.result?.download_url || activeOutput.result?.ppt_pdf_path || activeOutput.result?.ppt_pptx_path ? (
          <div className="thinkflow-ppt-download-row">
            {activeOutput.result?.ppt_pdf_path ? (
              <a href={activeOutput.result.ppt_pdf_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                <Download size={14} />
                打开 PDF
              </a>
            ) : null}
            {activeOutput.result?.ppt_pptx_path ? (
              <a href={activeOutput.result.ppt_pptx_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                <Download size={14} />
                下载 PPTX
              </a>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
