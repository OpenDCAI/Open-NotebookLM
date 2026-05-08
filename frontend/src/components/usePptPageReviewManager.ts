import { useState, useMemo, useEffect, useCallback } from 'react';
import { apiFetch } from '../config/api';
import type {
  ThinkFlowOutput, PptPageReview, PptPageVersion, OutlineSection,
} from './thinkflow-types';

async function parseJson<T>(response: Response): Promise<T> {
  const raw = await response.text();
  let data: any = null;

  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      if (!response.ok) {
        throw new Error(raw.trim() || `Request failed: ${response.status}`);
      }
      throw new Error(`Invalid JSON response: ${raw.slice(0, 160)}`);
    }
  }

  if (!response.ok) {
    const message = data?.detail || data?.message || data?.error || `Request failed: ${response.status}`;
    throw new Error(message);
  }

  return data as T;
}

type PptPageReviewManagerDeps = {
  activeOutput: ThinkFlowOutput | null;
  activePptSlideIndex: number;
  activePptSlide: { slide: OutlineSection; index: number } | null;
  activePptOutline: OutlineSection[];
  activePptPreviewImages: Record<number, string>;
  setOutputs: React.Dispatch<React.SetStateAction<ThinkFlowOutput[]>>;
  setActivePptSlideIndex: React.Dispatch<React.SetStateAction<number>>;
  pushToast: (msg: string, type?: string) => void;
  setGlobalError: (err: string | null) => void;
  refreshOutputs: () => Promise<void>;
  notebook: { id: string; title?: string; name?: string };
  notebookTitle: string;
  effectiveUser: { id: string; email: string };
  generatingOutput: boolean;
};

export function usePptPageReviewManager(deps: PptPageReviewManagerDeps) {
  const {
    activeOutput,
    activePptSlide,
    activePptPreviewImages,
    setOutputs,
    setActivePptSlideIndex,
    setGlobalError,
    notebook,
    notebookTitle,
    effectiveUser,
  } = deps;

  const [pptPagePrompt, setPptPagePrompt] = useState('');
  const [pptPageBusyAction, setPptPageBusyAction] = useState<'regenerate' | 'confirm' | 'select_version' | ''>('');
  const [pptPageStatus, setPptPageStatus] = useState('');
  const [pageReviewFilter, setPageReviewFilter] = useState<number | null>(null);

  const pageReviewChatContext = useMemo(() => {
    if (!deps.activeOutput || deps.activeOutput.pipeline_stage !== 'pages_ready') return null;
    const slides = deps.activePptOutline;
    const slide = slides[deps.activePptSlideIndex];
    if (!slide) return null;
    const idx = (slide as any).index ?? deps.activePptSlideIndex;
    return {
      title: `逐页审阅 · 第 ${idx + 1} 页`,
      placeholder: `描述第${idx + 1}页需要怎么调整...`,
      pageIndex: idx,
      pageTitle: (slide as any).title || slide.title || '',
    };
  }, [deps.activeOutput, deps.activePptOutline, deps.activePptSlideIndex]);

  const activePptPageReviews = useMemo<PptPageReview[]>(() => {
    if (!activeOutput || activeOutput.target_type !== 'ppt') return [];
    const existing = Array.isArray(activeOutput.page_reviews) ? activeOutput.page_reviews : [];
    if (existing.length > 0) return existing;
    return (activeOutput.outline || []).map((item, index) => ({
      page_index: index,
      page_num: item.pageNum || index + 1,
      confirmed: false,
    }));
  }, [activeOutput]);

  const activePptConfirmedCount = useMemo(
    () => activePptPageReviews.filter((item) => item.confirmed).length,
    [activePptPageReviews],
  );

  const activePptCurrentReview = useMemo(() => {
    if (!activePptSlide) return null;
    return activePptPageReviews.find((item) => item.page_index === activePptSlide.index) || null;
  }, [activePptPageReviews, activePptSlide]);

  const activePptPageVersions = useMemo<PptPageVersion[]>(() => {
    if (!activeOutput || activeOutput.target_type !== 'ppt' || !activePptSlide) return [];
    const versions = Array.isArray(activeOutput.page_versions) ? activeOutput.page_versions : [];
    return versions
      .filter((item) => item.page_index === activePptSlide.index)
      .sort((left, right) => {
        if (Boolean(left.selected) !== Boolean(right.selected)) {
          return left.selected ? -1 : 1;
        }
        return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
      });
  }, [activeOutput, activePptSlide]);

  const activePptCurrentPreview = useMemo(() => {
    if (!activePptSlide) return '';
    return (
      activePptSlide.slide.generated_img_path ||
      activePptSlide.slide.ppt_img_path ||
      activePptPreviewImages[activePptSlide.index] ||
      ''
    );
  }, [activePptPreviewImages, activePptSlide]);
  const activePptCurrentFailed = useMemo(() => {
    if (!activePptSlide) return false;
    return Boolean(activePptSlide.slide.generation_failed || (activePptSlide.slide.mode || '').includes('failed'));
  }, [activePptSlide]);

  useEffect(() => {
    if (!pptPageStatus) return;
    if (pptPageBusyAction) return;
    const timer = window.setTimeout(() => setPptPageStatus(''), 2400);
    return () => window.clearTimeout(timer);
  }, [pptPageBusyAction, pptPageStatus]);

  const regenerateActivePptPage = async () => {
    if (!activeOutput || activeOutput.target_type !== 'ppt' || !activePptSlide) return;
    const prompt = String(pptPagePrompt || '').trim();
    if (!prompt) {
      setGlobalError('请先输入你想修改当前页的要求。');
      return;
    }
    if (!activePptCurrentPreview) {
      setGlobalError('请先生成一版页面草稿，再改单页。');
      return;
    }
    setPptPageBusyAction('regenerate');
    setPptPageStatus(`第 ${activePptSlide.index + 1} 页正在按提示重做...`);
    console.info('[ThinkFlow] regeneratePptPage:start', {
      outputId: activeOutput.id,
      pageIndex: activePptSlide.index,
      prompt,
    });
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          prompt,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setPptPagePrompt('');
      console.info('[ThinkFlow] regeneratePptPage:success', {
        outputId: data.output.id,
        pageIndex: activePptSlide.index,
        updatedAt: data.output.updated_at,
      });
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页已重新生成，可在预览图下方切换历史版本`);
    } catch (error: any) {
      console.error('[ThinkFlow] regeneratePptPage:error', {
        outputId: activeOutput.id,
        pageIndex: activePptSlide.index,
        error: error?.message || String(error || ''),
      });
      setGlobalError(error?.message || '当前页重生成失败');
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页重生成失败`);
    } finally {
      setPptPageBusyAction('');
    }
  };

  const selectActivePptPageVersion = async (versionId: string) => {
    if (!activeOutput || activeOutput.target_type !== 'ppt' || !activePptSlide || !versionId) return;
    setPptPageBusyAction('select_version');
    setPptPageStatus(`第 ${activePptSlide.index + 1} 页正在切换历史版本...`);
    console.info('[ThinkFlow] selectPptPageVersion:start', {
      outputId: activeOutput.id,
      pageIndex: activePptSlide.index,
      versionId,
    });
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/versions/${versionId}/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页已切换到所选历史版本`);
      console.info('[ThinkFlow] selectPptPageVersion:success', {
        outputId: data.output.id,
        pageIndex: activePptSlide.index,
        versionId,
      });
    } catch (error: any) {
      console.error('[ThinkFlow] selectPptPageVersion:error', {
        outputId: activeOutput.id,
        pageIndex: activePptSlide.index,
        versionId,
        error: error?.message || String(error || ''),
      });
      setGlobalError(error?.message || '切换历史版本失败');
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页切换历史版本失败`);
    } finally {
      setPptPageBusyAction('');
    }
  };

  const confirmActivePptPage = async () => {
    if (!activeOutput || activeOutput.target_type !== 'ppt' || !activePptSlide) return;
    if (activePptCurrentFailed) {
      setGlobalError('当前页上一次生成失败，请先重新生成该页或整套页面。');
      return;
    }
    if (!activePptCurrentPreview) {
      setGlobalError('当前页还没有生成结果，无法确认。');
      return;
    }
    setPptPageBusyAction('confirm');
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      if (data.output.pipeline_stage !== 'generated') {
        setActivePptSlideIndex((previous) => {
          const maxIndex = (data.output.outline || []).length - 1;
          return Math.min(previous + 1, Math.max(maxIndex, 0));
        });
        setPptPageStatus(`第 ${activePptSlide.index + 1} 页已确认`);
      } else {
        setPptPageStatus('全部页面已确认，已进入结果页');
      }
    } catch (error: any) {
      setGlobalError(error?.message || '确认当前页失败');
    } finally {
      setPptPageBusyAction('');
    }
  };

  const revertToOutlineStage = useCallback(async () => {
    if (!deps.activeOutput) return;
    try {
      const resp = await apiFetch(`/api/v1/kb/outputs/${deps.activeOutput.id}/revert-stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: deps.notebook?.id || '',
          user_id: 'local',
        }),
      });
      if (resp.ok) {
        await deps.refreshOutputs();
        deps.pushToast('已返回大纲编辑阶段');
      } else {
        deps.setGlobalError('回退失败');
      }
    } catch (err: any) {
      deps.setGlobalError(err?.message || '回退失败');
    }
  }, [deps.activeOutput, deps.notebook, deps.refreshOutputs, deps.pushToast, deps.setGlobalError]);

  return {
    pptPagePrompt,
    setPptPagePrompt,
    pptPageBusyAction,
    pptPageStatus,
    activePptPageReviews,
    activePptConfirmedCount,
    activePptCurrentReview,
    activePptPageVersions,
    activePptCurrentPreview,
    regenerateActivePptPage,
    selectActivePptPageVersion,
    confirmActivePptPage,
    revertToOutlineStage,
    pageReviewFilter,
    setPageReviewFilter,
    pageReviewChatContext,
  };
}
