import type { z } from "zod";

// Same-origin client for the backend. next.config.ts rewrites /api/* to API_ORIGIN, so cookies
// stay first-party and the backend enforces CSRF by Origin. Responses can be validated with an
// optional zod schema; failures surface as a SafeError (status + stable code), never as raw
// upstream text.

export const API_BASE = "/api";
export const userAuthAPI = `${API_BASE}/plugins/auth/user`;
export const adminAuthAPI = `${API_BASE}/admin/auth`;

/** One attempt of a read; server-side budgets must fit inside it. */
export const READ_ATTEMPT_MS = 12000;
/** Token refresh budget. */
export const REFRESH_TIMEOUT_MS = 10000;

export type SafeError = {
  status: number;
  code: string;
  requestId?: string;
  retryAt?: number;
  /** Parsed JSON error body, for forms that map field errors. Never shown as-is. */
  body?: unknown;
};
export class ApiError extends Error {
  constructor(public detail: SafeError) {
    super(detail.code);
  }
}
export const toSafeError = (error: unknown): SafeError =>
  error instanceof ApiError ? error.detail : { status: 503, code: "unavailable" };

const parseJSON = (text: string): unknown => (text ? JSON.parse(text) : null);

let refreshing: Promise<boolean> | null = null;
async function refreshUserSession() {
  if (!refreshing)
    refreshing = fetch(`${userAuthAPI}/refresh`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  return refreshing;
}

const isIdempotent = (init: RequestInit) => ["GET", "HEAD"].includes((init.method ?? "GET").toUpperCase());

/**
 * A read (GET/HEAD) that timed out, in the browser or upstream (504), is retried once
 * automatically before any error is shown. Mutations are never retried here.
 */
export async function timedFetch(path: string, init: RequestInit, fetcher: typeof fetch = fetch): Promise<Response> {
  const attempts = isIdempotent(init) ? 2 : 1;
  for (let attempt = 1; ; attempt++) {
    const timeout = AbortSignal.timeout(READ_ATTEMPT_MS);
    const signal = attempts > 1 ? (init.signal ? AbortSignal.any([init.signal, timeout]) : timeout) : (init.signal ?? timeout);
    try {
      const response = await fetcher(path, { ...init, credentials: "same-origin", cache: "no-store", signal });
      if (response.status === 504 && attempt < attempts && !init.signal?.aborted) {
        await response.body?.cancel().catch(() => {});
        continue;
      }
      return response;
    } catch (error) {
      if (init.signal?.aborted || !timeout.aborted || attempt >= attempts) throw error;
    }
  }
}

function errorCode(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const record = body as { code?: unknown; error?: { code?: unknown } };
  if (typeof record.error?.code === "string") return record.error.code;
  if (typeof record.code === "string") return record.code;
  return undefined;
}

export type ApiOptions = {
  /** Retry once after refreshing the user session on 401 (user API only). */
  refreshOn401?: boolean;
};

export async function api<T>(
  path: string,
  schema?: z.ZodType<T>,
  init: RequestInit = {},
  options: ApiOptions = {},
): Promise<{ data: T; requestId?: string }> {
  let response: Response;
  try {
    response = await timedFetch(path, init);
    init.signal?.throwIfAborted();
    if (
      response.status === 401 &&
      options.refreshOn401 &&
      !path.endsWith("/login") &&
      !path.endsWith("/logout") &&
      (await refreshUserSession())
    )
      return api<T>(path, schema, init, { ...options, refreshOn401: false });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError({
      status: 503,
      code: error instanceof Error && error.name === "TimeoutError" ? "timeout" : "unavailable",
    });
  }
  const requestId = response.headers.get("x-request-id") ?? undefined;
  const text = await response.text();
  if (!response.ok) {
    let body: unknown;
    try {
      body = parseJSON(text);
    } catch {
      /* HTTP status still determines the safe state. */
    }
    const retryAfter = response.headers.get("retry-after");
    const retryAt = retryAfter
      ? /^\d+$/.test(retryAfter)
        ? Date.now() + Number(retryAfter) * 1000
        : Date.parse(retryAfter)
      : undefined;
    throw new ApiError({
      status: response.status,
      code: errorCode(body) ?? "unexpected_error",
      requestId,
      retryAt: retryAt && Number.isFinite(retryAt) ? retryAt : undefined,
      body,
    });
  }
  try {
    const parsed = parseJSON(text);
    return { data: schema ? schema.parse(parsed) : (parsed as T), requestId };
  } catch {
    throw new ApiError({ status: 503, code: "invalid_response", requestId });
  }
}

/** One key per user intent; reuse it when retrying that same intent. */
export const newIdempotencyKey = () => crypto.randomUUID();

/** Same-origin JSON mutation. */
export function postJSON<T>(path: string, body: unknown, schema?: z.ZodType<T>, idempotencyKey?: string) {
  return api<T>(path, schema, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(idempotencyKey ? { "idempotency-key": idempotencyKey } : {}),
    },
    body: JSON.stringify(body),
  });
}
