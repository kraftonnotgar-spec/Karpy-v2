/**
 * API errors (pure, tested in tests/api-client.test.ts).
 *
 * KARPy answers errors in FastAPI's shape: `{"detail": string | {field: message} | [{msg}]}`.
 * Some refusals add machine-readable keys, either beside `detail` (refresh:
 * `{detail, code, reason}`) or inside it (login: `{form, code, reason, accountStatus}`,
 * `{form, mobileAccess: "staff_not_allowed"}`). Everything becomes one ApiError:
 *
 * - `message`: the server's human text (form / message / the only field error), or '' when the
 *   server sent none. Screens show `errorMessage(e)` (lib/api/index.ts) which falls back to the
 *   translated text for `code`.
 * - `code`: a machine code: `offline`, `network`, `timeout`, `rate_limited`, `http_<status>`,
 *   or the server's own (`account_banned`, `staff_not_allowed`, ...).
 * - `fields`: per-field messages for forms (`email`, `password`, `code`, ...).
 */
export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  retryAfter?: number;
  body?: unknown;

  constructor(message: string, status: number, code: string, fields: Record<string, string> = {}, retryAfter?: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
    this.body = body;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** No answer from the server at all (offline, DNS, refused connection, timeout). */
export function isNetworkFailure(error: unknown) {
  const e = error as { status?: number; code?: string } | null;
  return !!e && (e.status ?? 0) === 0 && (e.code === 'network' || e.code === 'timeout' || e.code === 'offline');
}

function firstString(value: unknown): string | undefined {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(firstString).find(Boolean);
  if (value && typeof value === 'object' && typeof (value as { msg?: unknown }).msg === 'string') return (value as { msg: string }).msg;
  return undefined;
}

/** A machine code looks like `account_banned`; a field message ("The code is invalid.") does not. */
const MACHINE_CODE = /^[a-z][a-z0-9_]*$/;

/** Keys inside `detail` that describe the error instead of naming a form field. */
const META_KEYS = new Set(['form', 'message', 'code', 'reason', 'accountStatus', 'mobileAccess', 'requiresVerification']);

export function errorFromResponse(status: number, body: unknown, retryAfterHeader?: string | null): ApiError {
  const data = body && typeof body === 'object' ? (body as Record<string, unknown>) : undefined;
  const retryAfter = Number(retryAfterHeader) || undefined;
  const fields: Record<string, string> = {};
  let code = status === 429 ? 'rate_limited' : `http_${status}`;
  let message: string | undefined;

  if (typeof data?.code === 'string' && MACHINE_CODE.test(data.code)) code = data.code;
  const detail = data?.detail;
  if (typeof detail === 'string') message = detail;
  else if (Array.isArray(detail)) message = firstString(detail);
  else if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>;
    if (typeof d.mobileAccess === 'string') code = d.mobileAccess;
    if (typeof d.code === 'string' && MACHINE_CODE.test(d.code)) code = d.code;
    message = firstString(d.form) ?? firstString(d.message);
    for (const [key, value] of Object.entries(d)) {
      if (META_KEYS.has(key) && !(key === 'code' && typeof value === 'string' && !MACHINE_CODE.test(value))) continue;
      const text = firstString(value);
      if (text) fields[key] = text;
    }
    message = message ?? Object.values(fields)[0];
  }
  return new ApiError(message ?? '', status, code, fields, retryAfter, body);
}
