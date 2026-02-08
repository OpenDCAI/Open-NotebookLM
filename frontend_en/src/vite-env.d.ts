/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string
  readonly VITE_SUPABASE_ANON_KEY?: string
  readonly VITE_API_KEY?: string
  readonly VITE_DEFAULT_LLM_API_URL?: string
  readonly VITE_LLM_API_URLS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

