import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, Plus, User, Loader2, BookOpen, Key, CheckCircle2 } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { apiFetch } from '../config/api';
import { API_URL_OPTIONS, DEFAULT_LLM_API_URL } from '../config/api';
import { getApiSettings, saveApiSettings, type ApiSettings, type SearchProvider, type SearchEngine } from '../services/apiSettingsService';

export interface Notebook {
  id: string;
  title?: string;
  name?: string;
  author?: string;
  date?: string;
  sources?: number;
  image?: string;
  isFeatured?: boolean;
  description?: string;
  created_at?: string;
  updated_at?: string;
}

const Dashboard = ({ onOpenNotebook, refreshTrigger = 0 }: { onOpenNotebook: (n: Notebook) => void; refreshTrigger?: number }) => {
  const { user } = useAuthStore();
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [loading, setLoading] = useState(true);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newNotebookName, setNewNotebookName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [configOpen, setConfigOpen] = useState(false);
  const [apiUrl, setApiUrl] = useState(DEFAULT_LLM_API_URL);
  const [apiKey, setApiKey] = useState('');
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('serper');
  const [searchApiKey, setSearchApiKey] = useState('');
  const [searchEngine, setSearchEngine] = useState<SearchEngine>('google');
  const [configSaving, setConfigSaving] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);

  // 不做用户管理时用默认用户，数据从 outputs 取
  const effectiveUserId = user?.id || 'default';

  useEffect(() => {
    const s = getApiSettings(effectiveUserId);
    if (s) {
      setApiUrl(s.apiUrl || DEFAULT_LLM_API_URL);
      setApiKey(s.apiKey || '');
      setSearchProvider((s.searchProvider as SearchProvider) || 'serper');
      setSearchApiKey(s.searchApiKey || '');
      setSearchEngine((s.searchEngine as SearchEngine) || 'google');
    }
  }, [effectiveUserId]);

  const handleSaveConfig = () => {
    setConfigSaving(true);
    setConfigSaved(false);
    const settings: ApiSettings = {
      apiUrl: apiUrl.trim(),
      apiKey: apiKey.trim(),
      searchProvider,
      searchApiKey: searchApiKey.trim(),
      searchEngine,
    };
    saveApiSettings(effectiveUserId, settings);
    setConfigSaved(true);
    setTimeout(() => {
      setConfigSaving(false);
      setConfigSaved(false);
    }, 1500);
  };

  const fetchNotebooks = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/api/v1/kb/notebooks?user_id=${encodeURIComponent(effectiveUserId)}`);
      const data = await res.json();
      if (data?.success && Array.isArray(data.notebooks)) {
        const list: Notebook[] = data.notebooks.map((row: any) => ({
          id: row.id,
          title: row.name,
          name: row.name,
          description: row.description,
          created_at: row.created_at,
          updated_at: row.updated_at,
          date: row.updated_at ? new Date(row.updated_at).toLocaleDateString('zh-CN') : '',
          sources: typeof row.sources === 'number' ? row.sources : 0,
        }));
        setNotebooks(list);
      } else {
        setNotebooks([]);
      }
    } catch (err) {
      console.error('Failed to fetch notebooks:', err);
      setNotebooks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotebooks();
  }, [effectiveUserId, refreshTrigger]);

  const handleCreateNotebook = async () => {
    const name = newNotebookName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError('');
    try {
      const res = await apiFetch('/api/v1/kb/notebooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: '', user_id: effectiveUserId }),
      });
      const data = await res.json();
      if (data?.success && data?.notebook) {
        const nb = data.notebook;
        const newNb: Notebook = {
          id: nb.id,
          title: nb.name,
          name: nb.name,
          description: nb.description,
          created_at: nb.created_at,
          updated_at: nb.updated_at,
          date: nb.updated_at ? new Date(nb.updated_at).toLocaleDateString('zh-CN') : '',
          sources: 0,
        };
        setNotebooks(prev => [newNb, ...prev]);
        setCreateModalOpen(false);
        setNewNotebookName('');
        onOpenNotebook(newNb);
      } else {
        setCreateError(data?.message || '创建失败');
      }
    } catch (err: any) {
      setCreateError(err?.message || '创建失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8">
      {/* Glass Header */}
      <header className="sticky top-0 z-30 glass rounded-b-ios-xl -mx-6 px-6 py-4 mb-12 border-b border-white/30">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <img src="/logo_small.png" alt="Logo" className="h-8 w-auto object-contain" />
            <h1 className="text-2xl font-semibold text-ios-gray-900">open NoteBookLM</h1>
          </div>
          <div className="flex items-center gap-4">
            <motion.button
              whileTap={{ scale: 0.95 }}
              type="button"
              onClick={() => setConfigOpen((o) => !o)}
              className="text-ios-gray-600 hover:text-ios-gray-900 flex items-center gap-2 px-3 py-2 rounded-ios hover:bg-white/50 transition-colors"
            >
              <Settings size={20} />
              <span className="text-sm font-medium">API 配置</span>
            </motion.button>
            <div className="w-8 h-8 bg-gradient-to-br from-primary to-blue-600 rounded-full flex items-center justify-center text-white shadow-ios-sm">
              <User size={18} />
            </div>
          </div>
        </div>
      </header>

      {configOpen && (
        <section className="mb-8 p-6 bg-white rounded-ios-xl border border-ios-gray-100 shadow-ios">
          <h3 className="text-lg font-semibold text-ios-gray-900 mb-4 flex items-center gap-2">
            <Key size={20} />
            首页配置（进入笔记本后直接使用）
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <h4 className="text-sm font-medium text-ios-gray-600 flex items-center gap-1.5">LLM 调用</h4>
              <div>
                <label className="block text-xs font-medium text-ios-gray-500 mb-1">API URL</label>
                <select
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  className="w-full px-3 py-2.5 border border-ios-gray-200 rounded-ios text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                >
                  {[apiUrl, ...API_URL_OPTIONS].filter((v, i, a) => a.indexOf(v) === i).map((url: string) => (
                    <option key={url} value={url}>{url}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-ios-gray-500 mb-1">API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                  className="w-full px-3 py-2.5 border border-ios-gray-200 rounded-ios text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                />
              </div>
            </div>
            <div className="space-y-4">
              <h4 className="text-sm font-medium text-ios-gray-600 flex items-center gap-1.5">搜索来源 API</h4>
              <div>
                <label className="block text-xs font-medium text-ios-gray-500 mb-1">搜索服务</label>
                <select
                  value={searchProvider}
                  onChange={(e) => setSearchProvider(e.target.value as SearchProvider)}
                  className="w-full px-3 py-2.5 border border-ios-gray-200 rounded-ios text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                >
                  <option value="serper">Serper (Google，环境变量)</option>
                  <option value="serpapi">SerpAPI (Google/百度)</option>
                  <option value="bocha">博查 Bocha</option>
                </select>
              </div>
              {(searchProvider === 'serpapi' || searchProvider === 'bocha') && (
                <div>
                  <label className="block text-xs font-medium text-ios-gray-500 mb-1">Search API Key</label>
                  <input
                    type="password"
                    value={searchApiKey}
                    onChange={(e) => setSearchApiKey(e.target.value)}
                    placeholder={searchProvider === 'bocha' ? '博查 API Key' : 'SerpAPI Key'}
                    className="w-full px-3 py-2.5 border border-ios-gray-200 rounded-ios text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                  />
                </div>
              )}
              {searchProvider === 'serpapi' && (
                <div>
                  <label className="block text-xs font-medium text-ios-gray-500 mb-1">搜索引擎</label>
                  <select
                    value={searchEngine}
                    onChange={(e) => setSearchEngine(e.target.value as SearchEngine)}
                    className="w-full px-3 py-2.5 border border-ios-gray-200 rounded-ios text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                  >
                    <option value="google">Google</option>
                    <option value="baidu">百度</option>
                  </select>
                </div>
              )}
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <motion.button
              whileTap={{ scale: 0.97 }}
              type="button"
              onClick={handleSaveConfig}
              disabled={configSaving}
              className="px-5 py-2.5 bg-primary text-white rounded-ios hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2 text-sm font-medium shadow-ios-sm transition-colors"
            >
              {configSaving ? <Loader2 size={16} className="animate-spin" /> : configSaved ? <CheckCircle2 size={16} /> : <Key size={16} />}
              {configSaving ? '保存中...' : configSaved ? '已保存' : '保存配置'}
            </motion.button>
          </div>
        </section>
      )}

      <section>
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-semibold text-ios-gray-900">笔记本</h2>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-12 text-ios-gray-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            加载中...
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* New Notebook Card */}
            <motion.div
              whileHover={{ scale: 1.02, y: -4 }}
              whileTap={{ scale: 0.98 }}
              className="cursor-pointer bg-white rounded-ios-xl border-2 border-dashed border-ios-gray-200 aspect-[4/3] flex flex-col items-center justify-center gap-4 hover:border-primary/40 transition-colors shadow-ios-sm"
              onClick={() => setCreateModalOpen(true)}
            >
              <div className="w-12 h-12 bg-gradient-to-br from-primary/10 to-primary/20 rounded-full flex items-center justify-center">
                <Plus size={24} className="text-primary" />
              </div>
              <span className="font-medium text-ios-gray-700">新建笔记本</span>
            </motion.div>

            {/* Notebook Cards */}
            {notebooks.map((nb) => (
              <motion.div
                key={nb.id}
                whileHover={{ scale: 1.02, y: -4 }}
                whileTap={{ scale: 0.98 }}
                className="cursor-pointer bg-white rounded-ios-xl p-6 shadow-ios hover:shadow-ios-lg transition-shadow aspect-[4/3] flex flex-col justify-between"
                onClick={() => onOpenNotebook(nb)}
              >
                <div className="flex justify-between items-start">
                  <div className="w-10 h-10 bg-gradient-to-br from-amber-100 to-orange-100 rounded-ios flex items-center justify-center text-amber-600">
                    <BookOpen size={20} />
                  </div>
                </div>
                <div>
                  <h3 className="font-medium text-ios-gray-900 line-clamp-2 mb-2">
                    {nb.title || nb.name || '未命名'}
                  </h3>
                  <p className="text-ios-gray-400 text-xs">
                    {nb.date || (nb.updated_at ? new Date(nb.updated_at).toLocaleDateString('zh-CN') : '')}
                    {typeof nb.sources === 'number' ? ` · ${nb.sources} 个来源` : ''}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </section>

      {/* Create Modal — iOS Sheet */}
      <AnimatePresence>
        {createModalOpen && (
          <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" onClick={() => !creating && setCreateModalOpen(false)}>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 glass-dark"
            />
            <motion.div
              initial={{ y: 100, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 100, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 30 }}
              className="relative bg-white rounded-t-ios-2xl sm:rounded-ios-2xl p-6 w-full max-w-md shadow-ios-xl"
              onClick={e => e.stopPropagation()}
            >
              {/* iOS Drag Indicator */}
              <div className="flex justify-center mb-4 sm:hidden">
                <div className="w-9 h-1 rounded-full bg-ios-gray-300" />
              </div>
              <h3 className="text-lg font-semibold text-ios-gray-900 mb-4">新建笔记本</h3>
              <input
                type="text"
                className="w-full border border-ios-gray-200 rounded-ios px-4 py-3 mb-3 text-sm focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
                placeholder="笔记本名称"
                value={newNotebookName}
                onChange={e => setNewNotebookName(e.target.value)}
              />
              {createError && <p className="text-red-500 text-sm mb-2">{createError}</p>}
              <div className="flex justify-end gap-2">
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  className="px-5 py-2.5 text-ios-gray-600 hover:bg-ios-gray-100 rounded-ios font-medium text-sm transition-colors"
                  onClick={() => !creating && setCreateModalOpen(false)}
                  disabled={creating}
                >
                  取消
                </motion.button>
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  className="px-5 py-2.5 bg-primary text-white rounded-ios hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2 font-medium text-sm shadow-ios-sm transition-colors"
                  onClick={handleCreateNotebook}
                  disabled={creating || !newNotebookName.trim()}
                >
                  {creating && <Loader2 className="w-4 h-4 animate-spin" />}
                  创建
                </motion.button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default Dashboard;
