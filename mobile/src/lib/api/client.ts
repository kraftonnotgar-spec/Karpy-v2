import { ApiError, errorFromResponse } from './errors.ts';

/**
 * The HTTP client (pure: fetch is injected, so tests/api-client.test.ts drives it with a fake).
 *
 * - Bearer: every non-public request carries `Authorization: Bearer <access token>`. With no
 *   valid access token in memory it refreshes first instead of waiting for a 401 round trip.
 * - 401: one shared refresh (single flight: ten parallel 401s cause one /refresh), then the
 *   request is retried once with the new token.
 * - `refresh()` resolves the new access token, resolves `null` when the server refused the
 *   session (then `onSessionLost()` runs: sign out), and rejects when the server could not be
 *   reached (the session is kept and the caller sees the network error).
 * - Offline: fails at once with code `offline` instead of waiting for a timeout.
 */
export type TokenSource = {
  getAccessToken: () => string | null;
  refresh: () => Promise<string | null>;
  onSessionLost: () => void;
};

export type ClientDeps = TokenSource & {
  baseUrl: string;
  fetch: typeof fetch;
  isOffline?: () => boolean;
  timeoutMs?: number;
  headers?: Record<string, string>;
};

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  /** No bearer, no refresh, no 401 handling (sign-in, refresh itself). */
  public?: boolean;
  timeoutMs?: number;
};

export function createApiClient(deps: ClientDeps) {
  let refreshing: Promise<string | null> | null = null;

  function refreshOnce(): Promise<string | null> {
    refreshing ??= deps.refresh().finally(() => {
      refreshing = null;
    });
    return refreshing;
  }

  async function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json', ...deps.headers, ...options.headers };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? deps.timeoutMs ?? 15000);
    try {
      return await deps.fetch(`${deps.baseUrl}${path}`, {
        method: options.method ?? 'GET',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      const aborted = controller.signal.aborted || (error as { name?: string })?.name === 'AbortError';
      throw new ApiError('', 0, aborted ? 'timeout' : 'network');
    } finally {
      clearTimeout(timer);
    }
  }

  async function readBody(response: Response): Promise<unknown> {
    const text = await response.text();
    if (!text) return undefined;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  async function fail(response: Response): Promise<never> {
    throw errorFromResponse(response.status, await readBody(response), response.headers.get('retry-after'));
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    if (deps.isOffline?.()) throw new ApiError('', 0, 'offline');
    let token: string | null = null;
    if (!options.public) {
      token = deps.getAccessToken() ?? (await refreshOnce());
      if (!token) {
        deps.onSessionLost();
        throw new ApiError('', 401, 'session_expired');
      }
    }
    let response = await send(path, options, token);
    if (response.status === 401 && !options.public) {
      const fresh = await refreshOnce();
      if (!fresh) {
        deps.onSessionLost();
        return fail(response);
      }
      response = await send(path, options, fresh);
    }
    if (!response.ok) return fail(response);
    return (await readBody(response)) as T;
  }

  return {
    request,
    refreshOnce,
    get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
    post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'POST', body: body ?? {} }),
    put: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'PUT', body: body ?? {} }),
    del: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'DELETE', body }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
