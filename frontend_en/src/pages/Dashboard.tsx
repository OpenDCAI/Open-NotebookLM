import React, { useState, useEffect } from 'react';
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
        // 本地笔记本的 sources 已由后端从 outputs 扫描返回，无需再读 localStorage
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
        setCreateError(data?.message || 'Create failed');
      }
    } catch (err: any) {
      setCreateError(err?.message || 'Create failed');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8">
      <header className="flex justify-between items-center mb-12">
        <div className="flex items-center gap-2">
          <img src="/logo.png" alt="Logo" className="w-8 h-8 object-contain" />
          <h1 className="text-2xl font-semibold text-gray-800">open NoteBookLM</h1>
        </div>
        <div className="flex items-center gap-6">
          <button
            type="button"
            onClick={() => setConfigOpen((o) => !o)}
            className="text-gray-600 hover:text-gray-900 flex items-center gap-2"
          >
            <Settings size={20} />
            <span>API Settings</span>
          </button>
          <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-white">
            <User size={18} />
          </div>
        </div>
      </header>

      {configOpen && (
        <section className="mb-8 p-6 bg-white rounded-2xl border border-gray-200 shadow-sm">
          <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <Key size={20} />
            Home config (used when you open a notebook)
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <h4 className="text-sm font-medium text-gray-600 flex items-center gap-1.5">LLM API</h4>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">API URL</label>
                <select
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  {[apiUrl, ...API_URL_OPTIONS].filter((v, i, a) => a.indexOf(v) === i).map((url: string) => (
                    <option key={url} value={url}>{url}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>
            <div className="space-y-4">
              <h4 className="text-sm font-medium text-gray-600 flex items-center gap-1.5">Search API</h4>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Search provider</label>
                <select
                  value={searchProvider}
                  onChange={(e) => setSearchProvider(e.target.value as SearchProvider)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="serper">Serper (Google, env)</option>
                  <option value="serpapi">SerpAPI (Google/Baidu)</option>
                  <option value="bocha">Bocha</option>
                </select>
              </div>
              {(searchProvider === 'serpapi' || searchProvider === 'bocha') && (
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Search API Key</label>
                  <input
                    type="password"
                    value={searchApiKey}
                    onChange={(e) => setSearchApiKey(e.target.value)}
                    placeholder={searchProvider === 'bocha' ? 'Bocha API Key' : 'SerpAPI Key'}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              )}
              {searchProvider === 'serpapi' && (
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Search engine</label>
                  <select
                    value={searchEngine}
                    onChange={(e) => setSearchEngine(e.target.value as SearchEngine)}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="google">Google</option>
                    <option value="baidu">Baidu</option>
                  </select>
                </div>
              )}
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={handleSaveConfig}
              disabled={configSaving}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2 text-sm font-medium"
            >
              {configSaving ? <Loader2 size={16} className="animate-spin" /> : configSaved ? <CheckCircle2 size={16} /> : <Key size={16} />}
              {configSaving ? 'Saving...' : configSaved ? 'Saved' : 'Save config'}
            </button>
          </div>
        </section>
      )}

      <section>
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-semibold">Notebooks</h2>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading...
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div
              className="cursor-pointer bg-white rounded-2xl border-2 border-dashed border-gray-200 aspect-[4/3] flex flex-col items-center justify-center gap-4 hover:border-blue-300 hover:bg-blue-50/50 transition-all"
              onClick={() => setCreateModalOpen(true)}
            >
              <div className="w-12 h-12 bg-blue-50 rounded-full flex items-center justify-center text-blue-500">
                <Plus size={24} />
              </div>
              <span className="font-medium text-gray-700">New notebook</span>
            </div>

            {notebooks.map((nb) => (
              <div
                key={nb.id}
                className="cursor-pointer bg-white rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow aspect-[4/3] flex flex-col justify-between"
                onClick={() => onOpenNotebook(nb)}
              >
                <div className="flex justify-between items-start">
                  <div className="w-10 h-10 bg-amber-50 rounded-lg flex items-center justify-center text-amber-600">
                    <BookOpen size={20} />
                  </div>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900 line-clamp-2 mb-2">
                    {nb.title || nb.name || 'Untitled'}
                  </h3>
                  <p className="text-gray-400 text-xs">
                    {nb.date || (nb.updated_at ? new Date(nb.updated_at).toLocaleDateString('zh-CN') : '')}
                    {typeof nb.sources === 'number' ? ` · ${nb.sources} sources` : ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {createModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => !creating && setCreateModalOpen(false)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">New notebook</h3>
            <input
              type="text"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 mb-2"
              placeholder="Notebook name"
              value={newNotebookName}
              onChange={e => setNewNotebookName(e.target.value)}
            />
            {createError && <p className="text-red-500 text-sm mb-2">{createError}</p>}
            <div className="flex justify-end gap-2">
              <button
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
                onClick={() => !creating && setCreateModalOpen(false)}
                disabled={creating}
              >
                Cancel
              </button>
              <button
                className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2"
                onClick={handleCreateNotebook}
                disabled={creating || !newNotebookName.trim()}
              >
                {creating && <Loader2 className="w-4 h-4 animate-spin" />}
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
