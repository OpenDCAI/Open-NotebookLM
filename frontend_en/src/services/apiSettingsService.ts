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
const TRIAL_STORAGE_SUFFIXES = ['default', 'local', 'global'] as const;

function isTrialStorageUser(userId: string | null): boolean {
  return !userId || TRIAL_STORAGE_SUFFIXES.includes(userId as typeof TRIAL_STORAGE_SUFFIXES[number]);
}

function getStorageKeys(userId: string | null): string[] {
  if (isTrialStorageUser(userId)) {
    return TRIAL_STORAGE_SUFFIXES.map((suffix) => `${STORAGE_KEY_PREFIX}${suffix}`);
  }
  return [`${STORAGE_KEY_PREFIX}${userId}`];
}

/**
 * Get API settings for a user (or global if userId is null)
 */
export function getApiSettings(userId: string | null): ApiSettings | null {
  try {
    for (const key of getStorageKeys(userId)) {
      const stored = localStorage.getItem(key);
      if (stored) {
        return JSON.parse(stored);
      }
    }
  } catch (err) {
    console.error('Failed to load API settings:', err);
  }
  
  return {
    apiUrl: DEFAULT_LLM_API_URL,
    apiKey: '',
    searchProvider: 'serper',
    searchApiKey: '',
    searchEngine: 'google',
  };
}

/**
 * Save API settings for a user
 */
export function saveApiSettings(userId: string | null, settings: ApiSettings): void {
  try {
    const serialized = JSON.stringify(settings);
    for (const key of getStorageKeys(userId)) {
      localStorage.setItem(key, serialized);
    }
  } catch (err) {
    console.error('Failed to save API settings:', err);
  }
}
