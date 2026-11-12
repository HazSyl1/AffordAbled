const DEFAULT_PRODUCTION_API_BASE_URL = 'https://affordabled-api-c8ewaeajgjf0ehhf.centralindia-01.azurewebsites.net';
const defaultApiBaseUrl = import.meta.env.DEV
  ? 'http://localhost:8000'
  : DEFAULT_PRODUCTION_API_BASE_URL;

export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl
).replace(/\/+$/, '');
