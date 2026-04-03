/**
 * API Settings Service - Manage user's LLM + Search API configuration
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

/**
 * Get API settings for a user (or global if userId is null)
 */
export function getApiSettings(userId: string | null): ApiSettings | null {
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

/**
 * Save API settings for a user
 */
export function saveApiSettings(userId: string | null, settings: ApiSettings): void {
  try {
    const key = userId ? `${STORAGE_KEY_PREFIX}${userId}` : `${STORAGE_KEY_PREFIX}global`;
    localStorage.setItem(key, JSON.stringify(settings));
  } catch (err) {
    console.error('Failed to save API settings:', err);
  }
}
