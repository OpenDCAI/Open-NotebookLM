import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  BookOpen,
  Loader2,
  LogOut,
  Plus,
  Search,
  Sparkles,
  User,
} from 'lucide-react';

import { apiFetch, parseJson } from '../config/api';
import type { Notebook } from '../components/thinkflow-types';
import { useAuthStore } from '../stores/authStore';

const glassPanel =
  'rounded-[30px] border border-white/60 bg-white/65 shadow-[0_24px_60px_rgba(22,38,66,0.10)] backdrop-blur-2xl';

type DashboardProps = {
  onOpenNotebook: (notebook: Notebook) => void;
  refreshTrigger?: number;
  supabaseConfigured: boolean | null;
};

export default function Dashboard({
  onOpenNotebook,
  refreshTrigger = 0,
  supabaseConfigured,
}: DashboardProps) {
  const { user, signOut } = useAuthStore();
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchValue, setSearchValue] = useState('');
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newNotebookName, setNewNotebookName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const effectiveUserId = user?.id || 'local';
  const effectiveEmail = user?.email || '';

  const loadNotebooks = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiFetch(
        `/api/v1/kb/notebooks?user_id=${encodeURIComponent(effectiveUserId)}&email=${encodeURIComponent(effectiveEmail)}`,
      );
      const data = await parseJson<{ notebooks?: any[] } | null>(response);
      const next = Array.isArray(data?.notebooks)
        ? data.notebooks.map((row: any) => ({
            id: row.id,
            title: row.name || row.title || '未命名笔记本',
            name: row.name || row.title || '未命名笔记本',
            created_at: row.created_at,
            updated_at: row.updated_at,
          }))
        : [];
      setNotebooks(next);
    } catch (fetchError: any) {
      setNotebooks([]);
      setError(fetchError?.message || '获取笔记本列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadNotebooks();
  }, [effectiveEmail, effectiveUserId, refreshTrigger]);

  const filteredNotebooks = useMemo(() => {
    const keyword = searchValue.trim().toLowerCase();
    if (!keyword) {
      return notebooks;
    }
    return notebooks.filter((item) => {
      const title = item.name || item.title || '';
      return title.toLowerCase().includes(keyword);
    });
  }, [notebooks, searchValue]);

  const handleCreateNotebook = async () => {
    const name = newNotebookName.trim();
    if (!name) {
      return;
    }
    setCreating(true);
    setError('');
    try {
      const response = await apiFetch('/api/v1/kb/notebooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: '',
          user_id: effectiveUserId,
          email: effectiveEmail,
        }),
      });
      const data = await parseJson<{ success?: boolean; message?: string; notebook?: { id?: string; name?: string } } | null>(response);
      if (!data?.success || !data?.notebook?.id) {
        throw new Error(data?.message || '创建笔记本失败');
      }
      const notebook: Notebook = {
        id: data.notebook.id,
        title: data.notebook.name || name,
        name: data.notebook.name || name,
      };
      setNotebooks((current) => [notebook, ...current.filter((item) => item.id !== notebook.id)]);
      setCreateModalOpen(false);
      setNewNotebookName('');
      onOpenNotebook(notebook);
    } catch (createError: any) {
      setError(createError?.message || '创建笔记本失败');
    } finally {
      setCreating(false);
    }
  };

  const notebookCount = notebooks.length;

  return (
    <div className="mx-auto flex min-h-screen max-w-[1560px] flex-col gap-5 px-4 py-4 md:px-6 md:py-5">
      <header className={`${glassPanel} sticky top-3 z-20 px-5 py-5 md:px-6`}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/75 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                <Sparkles size={14} />
                ThinkFlow
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <img src="/logo_small.png" alt="Logo" className="h-10 w-auto object-contain" />
              <h1 className="text-3xl font-semibold tracking-[-0.04em] text-slate-900 md:text-5xl">
                知识工作台
              </h1>
            </div>

            <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-600 md:text-[15px]">
              管理你的知识库，随时进入工作区开始探索。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 lg:justify-end">
            <div className="hidden items-center gap-2 rounded-full border border-white/70 bg-white/70 px-3 py-2 text-sm text-slate-600 md:inline-flex">
              <User size={16} />
              {user?.email || user?.id || 'local'}
            </div>
            {supabaseConfigured ? (
              <button
                type="button"
                onClick={() => void signOut()}
                className="inline-flex items-center gap-2 rounded-[18px] border border-white/70 bg-white/75 px-4 py-3 text-sm font-medium text-slate-700 shadow-[0_10px_24px_rgba(37,53,81,0.08)] transition hover:-translate-y-0.5"
              >
                <LogOut size={16} />
                退出登录
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setCreateModalOpen(true)}
              className="inline-flex items-center gap-2 rounded-[18px] bg-[linear-gradient(135deg,#17467a_0%,#3f84cc_100%)] px-5 py-3 text-sm font-medium text-white shadow-[0_16px_32px_rgba(43,94,160,0.26)] transition hover:-translate-y-0.5"
            >
              <Plus size={16} />
              新建笔记本
            </button>
          </div>
        </div>
      </header>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_360px]">
        <div className={`${glassPanel} p-5 md:p-6`}>
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">工作区</div>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-900">
                选择一个笔记本继续工作
              </h2>
            </div>
            <label className="flex items-center gap-3 rounded-[20px] border border-white/70 bg-white/78 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] md:min-w-[320px]">
              <Search size={16} className="text-slate-400" />
              <input
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder="搜索笔记本"
                className="w-full border-0 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
              />
            </label>
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {loading ? (
              <div className="col-span-full flex min-h-[260px] items-center justify-center rounded-[26px] border border-dashed border-white/70 bg-white/52">
                <Loader2 size={24} className="animate-spin text-slate-400" />
              </div>
            ) : null}

            {!loading && filteredNotebooks.length === 0 ? (
              <div className="col-span-full rounded-[28px] border border-dashed border-white/70 bg-white/58 px-6 py-10 text-center">
                <div className="text-lg font-semibold text-slate-900">
                  {notebooks.length === 0 ? '还没有笔记本' : '没有匹配结果'}
                </div>
                <p className="mt-2 text-sm leading-7 text-slate-500">
                  {notebooks.length === 0
                    ? '先创建一个笔记本，再进入 ThinkFlow 工作台。'
                    : '换个关键词试试，或者直接创建新的笔记本。'}
                </p>
              </div>
            ) : null}

            {!loading &&
              filteredNotebooks.map((notebook, index) => {
                const title = notebook.name || notebook.title || '未命名笔记本';
                return (
                  <motion.button
                    key={notebook.id}
                    type="button"
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.22, delay: index * 0.03 }}
                    onClick={() => onOpenNotebook(notebook)}
                    className="group rounded-[28px] border border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(244,248,255,0.8))] p-5 text-left shadow-[0_20px_45px_rgba(26,43,72,0.08)] transition hover:-translate-y-1"
                  >
                    <div className="inline-flex items-center gap-2 rounded-full border border-sky-100 bg-sky-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-sky-700">
                      <BookOpen size={13} />
                      知识库
                    </div>
                    <h3 className="mt-4 line-clamp-2 text-2xl font-semibold tracking-[-0.04em] text-slate-900">
                      {title}
                    </h3>
                    <p className="mt-3 text-sm leading-7 text-slate-500">
                      点击进入，开始你的知识探索之旅。
                    </p>
                    <div className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-sky-700">
                      打开笔记本
                      <ArrowRight size={16} className="transition group-hover:translate-x-1" />
                    </div>
                  </motion.button>
                );
              })}
          </div>
        </div>

        <aside className={`${glassPanel} p-5 md:p-6`}>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Overview</div>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-900">工作区概览</h2>

          <div className="mt-5 grid gap-3">
            <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-400">知识空间</div>
              <div className="mt-2 flex items-baseline gap-1">
                <div className="text-3xl font-semibold tracking-[-0.05em] text-slate-900">{notebookCount}</div>
                <div className="text-xs text-slate-400">个工作区</div>
              </div>
            </div>
            <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-400">模式</div>
              <div className="mt-2 text-lg font-semibold text-slate-900">
                {supabaseConfigured ? '云端同步' : '本地试用'}
              </div>
            </div>
            <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-400">核心能力</div>
              <div className="mt-2 text-lg font-semibold text-slate-900">来源 · 对话 · 产出</div>
              <p className="mt-2 text-sm leading-7 text-slate-500">
                完整知识工作闭环
              </p>
            </div>
          </div>

          {error ? (
            <div className="mt-5 rounded-[22px] border border-rose-100 bg-rose-50/80 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}
        </aside>
      </section>

      {createModalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/22 px-4">
          <div className="absolute inset-0" onClick={() => setCreateModalOpen(false)} />
          <div className={`${glassPanel} relative z-10 w-full max-w-md p-6`}>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Create</div>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-900">新建笔记本</h3>
            <p className="mt-2 text-sm leading-7 text-slate-500">创建后会直接进入该笔记本的 ThinkFlow 工作台。</p>

            <input
              autoFocus
              value={newNotebookName}
              onChange={(event) => setNewNotebookName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  void handleCreateNotebook();
                }
              }}
              placeholder="输入笔记本名称"
              className="mt-5 w-full rounded-[20px] border border-white/70 bg-white/84 px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
            />

            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="rounded-[18px] border border-white/70 bg-white/80 px-4 py-3 text-sm font-medium text-slate-600"
              >
                取消
              </button>
              <button
                type="button"
                disabled={creating || !newNotebookName.trim()}
                onClick={() => void handleCreateNotebook()}
                className="rounded-[18px] bg-[linear-gradient(135deg,#17467a_0%,#3f84cc_100%)] px-4 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-55"
              >
                {creating ? '创建中...' : '创建并进入'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
