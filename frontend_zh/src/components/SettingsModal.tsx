import React, { useEffect, useState } from 'react';
import { X, Key, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import { API_URL_OPTIONS, DEFAULT_LLM_API_URL } from '../config/api';
import { getApiSettings, saveApiSettings, type SearchProvider, type SearchEngine } from '../services/apiSettingsService';
import { useAuthStore } from '../stores/authStore';

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ open, onClose }) => {
  const { user } = useAuthStore();
  const userIdForSettings = user?.id ?? 'default';
  const [apiUrl, setApiUrl] = useState(DEFAULT_LLM_API_URL);
  const [apiKey, setApiKey] = useState('');
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('serper');
  const [searchApiKey, setSearchApiKey] = useState('');
  const [searchEngine, setSearchEngine] = useState<SearchEngine>('google');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (open) {
      const settings = getApiSettings(userIdForSettings);
      if (settings) {
        setApiUrl(settings.apiUrl || DEFAULT_LLM_API_URL);
        setApiKey(settings.apiKey || '');
        setSearchProvider((settings.searchProvider as SearchProvider) || 'serper');
        setSearchApiKey(settings.searchApiKey || '');
        setSearchEngine((settings.searchEngine as SearchEngine) || 'google');
      } else {
        setApiUrl(DEFAULT_LLM_API_URL);
        setApiKey('');
        setSearchProvider('serper');
        setSearchApiKey('');
        setSearchEngine('google');
      }
    }
  }, [open, userIdForSettings]);

  const handleSave = () => {
    setSaving(true);
    setSaved(false);
    saveApiSettings(userIdForSettings, {
      apiUrl: apiUrl.trim(),
      apiKey: apiKey.trim(),
      searchProvider,
      searchApiKey: searchApiKey.trim(),
      searchEngine,
    });
    setSaved(true);
    setTimeout(() => {
      setSaving(false);
      setSaved(false);
    }, 1500);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-800">API 设置</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-gray-700 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-500">
            配置 LLM API 的地址和密钥，用于智能问答、思维导图、PPT 生成等功能。请求时会随请求体传给后端使用。
          </p>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">API URL</label>
            <select
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
            >
              {[apiUrl, ...API_URL_OPTIONS].filter((v, i, a) => a.indexOf(v) === i).map((url: string) => (
                <option key={url} value={url}>{url}</option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-400">OpenAI 兼容接口地址，如 api.openai.com/v1 或自建服务</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
            />
            <p className="mt-1 text-xs text-gray-400">用于调用 LLM 的密钥，仅保存在本机浏览器中</p>
            {!apiKey.trim() && (
              <p className="mt-1.5 text-xs text-amber-600">请填写 API Key 并保存，否则「生成向量」将不可用</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">搜索来源</label>
            <select
              value={searchProvider}
              onChange={(e) => setSearchProvider(e.target.value as SearchProvider)}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="serper">Serper (Google)</option>
              <option value="serpapi">SerpAPI (Google/百度)</option>
              <option value="bocha">博查 Bocha</option>
            </select>
          </div>
          {(searchProvider === 'serpapi' || searchProvider === 'bocha') && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Search API Key</label>
              <input
                type="password"
                value={searchApiKey}
                onChange={(e) => setSearchApiKey(e.target.value)}
                placeholder={searchProvider === 'bocha' ? '博查 API Key' : 'SerpAPI Key'}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}
          {searchProvider === 'serpapi' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">搜索引擎</label>
              <select
                value={searchEngine}
                onChange={(e) => setSearchEngine(e.target.value as SearchEngine)}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="google">Google</option>
                <option value="baidu">百度</option>
              </select>
            </div>
          )}

          <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" />
            <p>
              API 配置仅保存在当前设备的浏览器本地存储中，不会上传到服务器。请在安全环境下使用。
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-100 rounded-xl transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2.5 text-sm font-medium text-white bg-blue-500 hover:bg-blue-600 rounded-xl disabled:opacity-50 flex items-center gap-2 transition-colors"
          >
            {saving ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                保存中...
              </>
            ) : saved ? (
              <>
                <CheckCircle2 size={16} />
                已保存
              </>
            ) : (
              <>
                <Key size={16} />
                保存配置
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
