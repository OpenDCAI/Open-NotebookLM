/**
 * API configuration for backend calls.
 */

import { getAccessToken } from '../stores/authStore';

// Backend API base URL with smart detection
function getApiBaseUrl(): string {
  const configuredUrl = import.meta.env.VITE_API_BASE_URL || '';

  if (configuredUrl.includes('localhost') || configuredUrl.includes('127.0.0.1')) {
    const currentHost = window.location.hostname;
    if (currentHost !== 'localhost' && currentHost !== '127.0.0.1') {
      console.info('[API] Public access detected, using relative path instead of localhost');
      return '';
    }
  }

  return configuredUrl;
}

export const API_BASE_URL = getApiBaseUrl();

export const GRAPHRAG_KB_BASE = '/api/v1/graphrag-kb';

// API key for backend authentication
export const API_KEY = import.meta.env.VITE_API_KEY || 'df-internal-2024-workflow-key';

// LLM Provider Default Configuration
export const DEFAULT_LLM_API_URL = import.meta.env.VITE_DEFAULT_LLM_API_URL || 'https://api.apiyi.com/v1';

// List of available LLM API URLs
export const API_URL_OPTIONS = (import.meta.env.VITE_LLM_API_URLS || 'https://api.apiyi.com/v1,http://b.apiyi.com:16888/v1,http://123.129.219.111:3000/v1').split(',').map((url: string) => url.trim());

/**
 * Get headers for API calls including the API key.
 */
export function getApiHeaders(): HeadersInit {
  const token = getAccessToken();
  const headers: HeadersInit = {
    'X-API-Key': API_KEY,
  };
  if (token) {
    (headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Create a fetch wrapper that includes the API key.
 */
export async function apiFetch(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set('X-API-Key', API_KEY);
  const token = getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const fullUrl = url.startsWith('http') ? url : `${API_BASE_URL}${url}`;

  return fetch(fullUrl, {
    ...options,
    headers,
  });
}
