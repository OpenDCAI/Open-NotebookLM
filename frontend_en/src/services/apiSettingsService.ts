/**
 * API Settings Service - kept for per-user frontend defaults/backward compatibility.
 * Server-side env vars remain the primary source of truth.
 */

import { DEFAULT_LLM_API_URL } from '../config/api';

export type SearchProvider = 'serper' | 'serpapi' | 'bocha';
export type SearchEngine = 'google' | 'baidu';

export interface ApiSettings {
  apiUrl: string;
  apiKey: string;
  searchProvider?: SearchProvider;
  searchApiKey?: string;
  searchEngine?: SearchEngine;
}

const STORAGE_KEY_PREFIX = 'kb_api_settings_';

function normalizeApiSettings(settings: Partial<ApiSettings>): ApiSettings {
  const searchApiKey = settings.searchApiKey || '';
  let searchProvider = settings.searchProvider;

  if (!searchProvider) {
    searchProvider = 'bocha';
  }
  if (searchProvider === 'serper' && !searchApiKey.trim()) {
    searchProvider = 'bocha';
  }

  return {
    apiUrl: settings.apiUrl || DEFAULT_LLM_API_URL,
    apiKey: settings.apiKey || '',
    searchProvider,
    searchApiKey,
    searchEngine: settings.searchEngine || 'google',
  };
}

export function getApiSettings(userId: string | null): ApiSettings {
  try {
    const key = userId ? `${STORAGE_KEY_PREFIX}${userId}` : `${STORAGE_KEY_PREFIX}global`;
    const stored = localStorage.getItem(key);
    if (stored) {
      return normalizeApiSettings(JSON.parse(stored));
    }
  } catch (err) {
    console.error('Failed to load API settings:', err);
  }

  return normalizeApiSettings({});
}

export function saveApiSettings(userId: string | null, settings: ApiSettings): void {
  try {
    const key = userId ? `${STORAGE_KEY_PREFIX}${userId}` : `${STORAGE_KEY_PREFIX}global`;
    localStorage.setItem(key, JSON.stringify(settings));
  } catch (err) {
    console.error('Failed to save API settings:', err);
  }
}
