/**
 * API configuration for backend calls.
 */

import { getAccessToken } from '../stores/authStore';

// Backend API base URL with smart detection
function getApiBaseUrl(): string {
  const configuredUrl = import.meta.env.VITE_API_BASE_URL || '';

  // If configured URL is localhost but we're not accessing from localhost,
  // use relative path (current domain) instead
  if (configuredUrl.includes('localhost') || configuredUrl.includes('127.0.0.1')) {
    const currentHost = window.location.hostname;
    if (currentHost !== 'localhost' && currentHost !== '127.0.0.1') {
      // Public network access detected, using relative path instead of localhost
      return ''; // Use relative path (current domain)
    }
  }

  return configuredUrl;
}

export const API_BASE_URL = getApiBaseUrl();

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

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail.trim();
  }

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => formatApiErrorDetail(item))
      .filter(Boolean);
    return parts.join('; ');
  }

  if (detail && typeof detail === 'object') {
    const detailRecord = detail as Record<string, unknown>;
    const message = typeof detailRecord.msg === 'string' ? detailRecord.msg.trim() : '';
    const location = Array.isArray(detailRecord.loc)
      ? detailRecord.loc.map((part) => String(part)).join('.')
      : '';
    const nestedDetail = formatApiErrorDetail(detailRecord.detail);

    if (message && location) return `${location}: ${message}`;
    if (message) return message;
    if (nestedDetail) return nestedDetail;
  }

  return '';
}

/**
 * Parse a JSON response, throwing a descriptive error on failure or non-OK status.
 */
export async function parseJson<T>(response: Response): Promise<T> {
  const raw = await response.text();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

  if (!response.ok || data?.success === false) {
    const detail = formatApiErrorDetail(data?.detail);
    const message = typeof data?.message === 'string' ? data.message.trim() : '';
    const nestedErrorMessage =
      typeof data?.error?.message === 'string' ? data.error.message.trim() : '';
    const fallback = raw.trim() || response.statusText || `Request failed: ${response.status}`;
    throw new Error(detail || message || nestedErrorMessage || fallback);
  }
  return data as T;
}
