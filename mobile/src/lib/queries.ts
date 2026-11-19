import { QueryClient, useQuery, type QueryKey } from '@tanstack/react-query';

import type { ApiError } from '@/lib/api';
import { authApi } from '@/lib/auth/auth-api';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // Keep data long enough for the persisted offline copy (24 h) to be useful.
      gcTime: 24 * 60 * 60 * 1000,
      retry: (count, error) => {
        const e = error as ApiError;
        if (e?.code === 'offline') return false;
        const status = e?.status ?? 0;
        return status >= 500 || status === 0 ? count < 2 : false;
      },
      retryDelay: (n) => Math.min(800 * 2 ** n, 4000),
    },
    // An action must never sit "paused" offline: it fails at once with the offline message.
    mutations: { retry: false, networkMode: 'always' },
  },
});

/** Query keys. Roots listed in lib/offline/rules.ts PERSISTED_QUERY_ROOTS are saved offline. */
export const qk = {
  me: ['me'] as QueryKey,
  notifications: ['notifications'] as QueryKey,
};

/** The signed-in user (GET /me). Saved for offline reading. */
export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => authApi.me().then((r) => r.user) });
}
