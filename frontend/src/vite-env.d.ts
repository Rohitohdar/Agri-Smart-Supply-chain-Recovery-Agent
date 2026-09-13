/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, e.g. http://127.0.0.1:8000. */
  readonly VITE_API_BASE_URL?: string;
  /** Display-only currency symbol; the backend has no currency concept. */
  readonly VITE_CURRENCY_SYMBOL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
