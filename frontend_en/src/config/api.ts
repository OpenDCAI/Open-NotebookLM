/**
 * API configuration - 所有配置在后端管理
 */

import { getAccessToken } from '../stores/authStore';

function getApiBaseUrl(): string {
  const configuredUrl = import.meta.env.VITE_API_BASE_URL || '';

  if (configuredUrl.includes('localhost') || configuredUrl.includes('127.0.0.1')) {
    const currentHost = window.location.hostname;
    if (currentHost !== 'localhost' && currentHost !== '127.0.0.1') {
      console.info('[API] detected remote access, using relative path instead of localhost');
      return '';
    }
  }

  return configuredUrl;
}

// 前端优先走相对路径，通过 Vite 代理访问后端
export const API_BASE_URL = getApiBaseUrl();

// API key 从后端获取
export const API_KEY = import.meta.env.VITE_API_KEY || 'df-internal-2024-workflow-key';

export const DEFAULT_LLM_API_URL = import.meta.env.VITE_DEFAULT_LLM_API_URL || 'https://api.apiyi.com/v1';

export const API_URL_OPTIONS = (import.meta.env.VITE_LLM_API_URLS || 'https://api.apiyi.com/v1,http://b.apiyi.com:16888/v1,http://123.129.219.111:3000/v1')
  .split(',')
  .map((url: string) => url.trim());


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

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set('X-API-Key', API_KEY);
  const token = getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(url, { ...options, headers });
}
