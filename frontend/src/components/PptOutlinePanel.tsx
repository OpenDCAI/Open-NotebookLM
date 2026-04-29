import React, { useMemo, useState } from 'react';
import type { OutlineSection, ThinkFlowOutput, PptPipelineStage } from './thinkflow-types';
import { getPptStageLabel } from './usePptOutlineManager';
import { diffPptOutline } from './pptOutlineDiff';

type PptOutlinePanelProps = {
  activeOutput: ThinkFlowOutput;
  activePptOutline: (OutlineSection & { index?: number })[];
  activePptSlide: { slide: OutlineSection; index: number } | null;
  activePptStage: PptPipelineStage;
  activePptDraftPending: boolean;
  archivedOutlineChatSessions: unknown[];
  outlineSaving: boolean;
  generatingOutput: boolean;
  draftOutline?: OutlineSection[];
  globalDirectives?: any[];
  onSetRightMode: (mode: string) => void;
  onSaveOutline: () => Promise<void>;
  onConfirmPptOutline: () => Promise<void>;
  onDiscardPptOutlineDraft: () => Promise<void>;
  onUpdateOutlineSection: (index: number, patch: Partial<OutlineSection>) => void;
  onSetActivePptSlideIndex: (index: number) => void;
  onAddPptOutlineSection: () => void;
};

type PptStageRailProps = {
  activePptStage: PptPipelineStage;
};

function PptStageRail({ activePptStage }: PptStageRailProps) {
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

export function PptOutlinePanel({
  activeOutput,
  activePptOutline,
  activePptSlide,
  activePptStage,
  activePptDraftPending,
  archivedOutlineChatSessions,
  outlineSaving,
  generatingOutput,
  draftOutline,
  globalDirectives,
  onSetRightMode,
  onSaveOutline,
  onConfirmPptOutline,
  onDiscardPptOutlineDraft,
  onUpdateOutlineSection,
  onSetActivePptSlideIndex,
  onAddPptOutlineSection,
}: PptOutlinePanelProps) {
  const [directivesOpen, setDirectivesOpen] = useState(false);
  const slides = activePptOutline;
  const selectedSlide = activePptSlide?.slide || null;
  const selectedSlideIndex = activePptSlide?.index ?? 0;

  const outlineDiff = useMemo(() => {
    if (!activePptDraftPending || !draftOutline) return null;
    return diffPptOutline(activePptOutline, draftOutline);
  }, [activePptDraftPending, draftOutline, activePptOutline]);

  const getDraftClass = (index: number): string => {
    if (!outlineDiff) return '';
    const entry = outlineDiff.entries.find(e => e.pageNum === activePptOutline[index]?.pageNum);
    if (!entry) return '';
    switch (entry.kind) {
      case 'modified': return 'tf-outline-card--draft-modified';
      case 'added': return 'tf-outline-card--draft-added';
      case 'removed': return 'tf-outline-card--draft-removed';
      default: return '';
    }
  };
  return (
    <>
      <PptStageRail activePptStage={activePptStage} />
      <div className="thinkflow-ppt-stage-header">
        <div className="thinkflow-ppt-stage-copy">
          <h4>{getPptStageLabel(activePptStage)}</h4>
          <p>
            {activePptDraftPending
              ? '当前正在预览一版候选大纲。它还没有覆盖正式大纲，只有点击"推送改动"后才会真正生效。'
              : '这一步先确认整套页级大纲。中间对话先讨论出候选大纲，推送后再决定是否进入逐页生成。'}
          </p>
        </div>
        <div className="thinkflow-ppt-stage-actions">
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => onSetRightMode('doc')}>
            返回文档
          </button>
          <button type="button" className="thinkflow-doc-action-btn is-active" onClick={() => void onSaveOutline()} disabled={outlineSaving || activePptDraftPending}>
            {outlineSaving ? '保存中...' : '保存大纲'}
          </button>
          {activePptDraftPending ? (
            <button type="button" className="thinkflow-doc-action-btn is-danger" onClick={() => void onDiscardPptOutlineDraft()} disabled={outlineSaving}>
              放弃候选
            </button>
          ) : null}
          <button type="button" className="thinkflow-generate-btn" onClick={() => void onConfirmPptOutline()} disabled={outlineSaving || generatingOutput || activePptDraftPending}>
            确认大纲，进入逐页生成
          </button>
        </div>
      </div>
      <div className="thinkflow-ppt-refine-panel">
        <div className="thinkflow-doc-check-tip">
          中间对话区现在是当前 PPT 的主交互入口。系统会先识别你的修改意图，区分全局规则和页级修改，再在对话里生成候选改动卡片；只有点击对话里的"推送这版"后才会覆盖正式大纲。
        </div>
        {archivedOutlineChatSessions.length > 0 ? (
          <div className="thinkflow-doc-check-tip">已收起 {archivedOutlineChatSessions.length} 轮历史对话，当前只显示这次产出的最新一轮讨论。</div>
        ) : null}
      </div>
      <div className="thinkflow-ppt-outline-canvas">
        {selectedSlide ? (
          <div className="thinkflow-ppt-focus-shell">
            <article className="thinkflow-ppt-focus-preview">
              <div className="thinkflow-ppt-focus-preview-top">
                <span className="thinkflow-ppt-outline-summary-index">第 {selectedSlide.pageNum || selectedSlideIndex + 1} 页</span>
                <span className="thinkflow-ppt-focus-preview-label">当前页预览</span>
              </div>
              <div className="thinkflow-ppt-focus-slide">
                <div className="thinkflow-ppt-focus-slide-head">
                  <h4>{selectedSlide.title || `页面 ${selectedSlideIndex + 1}`}</h4>
                  <p>{selectedSlide.layout_description || '这页还没有填写布局说明。'}</p>
                </div>
                {(selectedSlide.key_points || selectedSlide.bullets || []).length > 0 ? (
                  <ul className="thinkflow-ppt-focus-points">
                    {(selectedSlide.key_points || selectedSlide.bullets || []).map((point, pointIndex) => (
                      <li key={`${selectedSlide.id || selectedSlideIndex}_${pointIndex}`}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
                )}
                {selectedSlide.asset_ref ? <div className="thinkflow-ppt-outline-card-asset">素材：{selectedSlide.asset_ref}</div> : null}
              </div>
            </article>
            <div className="thinkflow-ppt-slide-editor">
              <div className="thinkflow-ppt-slide-editor-head">
                <div>
                  <span className="thinkflow-output-workspace-kicker">{activePptDraftPending ? '候选大纲预览' : '单页编辑'}</span>
                  <h4>{activePptDraftPending ? `正在预览第 ${selectedSlide.pageNum || selectedSlideIndex + 1} 页候选内容` : `正在编辑第 ${selectedSlide.pageNum || selectedSlideIndex + 1} 页`}</h4>
                </div>
              </div>
              <input
                className="thinkflow-outline-input"
                value={selectedSlide.title || ''}
                onChange={(event) => onUpdateOutlineSection(selectedSlideIndex, { title: event.target.value })}
                placeholder="页面标题"
                disabled={activePptDraftPending}
              />
              <textarea
                className="thinkflow-outline-textarea"
                value={selectedSlide.layout_description || ''}
                onChange={(event) =>
                  onUpdateOutlineSection(selectedSlideIndex, {
                    layout_description: event.target.value,
                    summary: event.target.value,
                  })
                }
                placeholder="这一页的布局描述 / 页面角色"
                rows={3}
                disabled={activePptDraftPending}
              />
              <textarea
                className="thinkflow-outline-textarea"
                value={(selectedSlide.key_points || selectedSlide.bullets || []).join('\n')}
                onChange={(event) =>
                  onUpdateOutlineSection(selectedSlideIndex, {
                    key_points: event.target.value.split('\n').map((text) => text.trim()).filter(Boolean),
                    bullets: event.target.value.split('\n').map((text) => text.trim()).filter(Boolean),
                  })
                }
                placeholder="每行一个要点"
                rows={7}
                disabled={activePptDraftPending}
              />
              <input
                className="thinkflow-outline-input"
                value={selectedSlide.asset_ref || ''}
                onChange={(event) => onUpdateOutlineSection(selectedSlideIndex, { asset_ref: event.target.value || null })}
                placeholder="可选：来源素材引用（asset_ref）"
                disabled={activePptDraftPending}
              />
              {activePptDraftPending ? <div className="thinkflow-doc-check-tip">当前页面展示的是候选大纲。若认可这版内容，请在对话区点击"推送这版"。</div> : null}
            </div>
          </div>
        ) : null}

        {globalDirectives && globalDirectives.length > 0 && (
          <div className="tf-global-directives">
            <div className="tf-global-directives__header" onClick={() => setDirectivesOpen(!directivesOpen)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: '#495057' }}>全局规则</span>
                <span className="tf-global-directives__badge">{globalDirectives.length}</span>
              </div>
              <span style={{ fontSize: 11, color: '#868e96' }}>{directivesOpen ? '▲ 收起' : '▼ 展开'}</span>
            </div>
            {directivesOpen && (
              <>
                <div style={{ padding: '0 12px 8px', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {globalDirectives.map((d: any) => (
                    <span key={d.id} className="tf-global-directives__tag">{d.label}</span>
                  ))}
                </div>
                <div className="tf-global-directives__hint">通过左侧对话添加或修改</div>
              </>
            )}
          </div>
        )}

        <div className="thinkflow-ppt-outline-strip">
          {slides.map((item, index) => (
            <button
              key={item.id || `${activeOutput.id}_${index}`}
              type="button"
              className={`thinkflow-ppt-outline-card ${selectedSlideIndex === index ? 'is-active' : ''} ${getDraftClass(index)}`}
              onClick={() => onSetActivePptSlideIndex(index)}
            >
              <div className="thinkflow-ppt-outline-card-top">
                <span className="thinkflow-ppt-outline-summary-index">第 {item.pageNum || index + 1} 页</span>
                <span className="thinkflow-ppt-outline-card-cta">{selectedSlideIndex === index ? '编辑中' : '查看'}</span>
              </div>
              {getDraftClass(index) === 'tf-outline-card--draft-added' && (
                <span className="tf-outline-card__badge">新增</span>
              )}
              <h4>{item.title || `页面 ${index + 1}`}</h4>
              {item.layout_description ? <p>{item.layout_description}</p> : null}
              {(item.key_points || item.bullets || []).length > 0 ? (
                <ul>
                  {(item.key_points || item.bullets || []).slice(0, 3).map((point, pointIndex) => (
                    <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                  ))}
                </ul>
              ) : (
                <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
              )}
            </button>
          ))}
          <button type="button" className="thinkflow-outline-add-btn thinkflow-ppt-outline-add-card" onClick={onAddPptOutlineSection} disabled={activePptDraftPending}>
            + 添加页面
          </button>
        </div>
      </div>
      <div className="thinkflow-outline-footer">
        <div className="thinkflow-outline-actions">
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => onSetRightMode('doc')}>
            返回文档
          </button>
          <button type="button" className="thinkflow-doc-action-btn is-active" onClick={() => void onSaveOutline()} disabled={outlineSaving || activePptDraftPending}>
            {outlineSaving ? '保存中...' : '保存大纲'}
          </button>
          {activePptDraftPending ? (
            <button type="button" className="thinkflow-doc-action-btn is-danger" onClick={() => void onDiscardPptOutlineDraft()} disabled={outlineSaving}>
              放弃候选
            </button>
          ) : null}
          <button type="button" className="thinkflow-generate-btn" onClick={() => void onConfirmPptOutline()} disabled={outlineSaving || generatingOutput || activePptDraftPending}>
            确认大纲，进入逐页生成
          </button>
        </div>
      </div>
    </>
  );
}

type PptLockedOutlinePreviewProps = {
  activeOutput: ThinkFlowOutput;
  pptOutlineReadonlyOpen: boolean;
  onSetPptOutlineReadonlyOpen: (open: boolean) => void;
};

export function PptLockedOutlinePreview({
  activeOutput,
  pptOutlineReadonlyOpen,
  onSetPptOutlineReadonlyOpen,
}: PptLockedOutlinePreviewProps) {
  if (!pptOutlineReadonlyOpen) return null;
  const slides = activeOutput.outline || [];
  return (
    <div className="thinkflow-ppt-locked-outline">
      <div className="thinkflow-ppt-locked-outline-head">
        <div>
          <span className="thinkflow-output-workspace-kicker">已确认大纲</span>
          <h4>当前大纲只读</h4>
        </div>
        <button type="button" className="thinkflow-doc-action-btn" onClick={() => onSetPptOutlineReadonlyOpen(false)}>
          收起
        </button>
      </div>
      <div className="thinkflow-ppt-outline-summary-list">
        {slides.map((item, index) => (
          <article key={item.id || `${activeOutput.id}_${index}`} className="thinkflow-ppt-outline-summary-card">
            <span className="thinkflow-ppt-outline-summary-index">第 {item.pageNum || index + 1} 页</span>
            <h4>{item.title || `页面 ${index + 1}`}</h4>
            {item.layout_description ? <p>{item.layout_description}</p> : null}
            {(item.key_points || item.bullets || []).length > 0 ? (
              <ul>
                {(item.key_points || item.bullets || []).slice(0, 4).map((point, pointIndex) => (
                  <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                ))}
              </ul>
            ) : (
              <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
