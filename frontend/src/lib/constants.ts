import { getEnvConfig } from '@/lib/env';

export const API_BASE = getEnvConfig().API_BASE_URL || '/api';
export const DEFAULT_PAGE_SIZE = 10;
export const DEFAULT_ROWS_PAGE_SIZE = 50;
export const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
