/**
 * Closed accounts (pure, tested in tests/session-refresh.test.ts).
 *
 * When an admin deactivates or bans an account, the server revokes every session. The app
 * learns why from a 403:
 *   - refresh:            {detail, code: "account_deactivated" | "account_banned", reason}
 *   - login/verify-login: {detail: {form, accountStatus, code, reason}}
 * Anything else (another status, another code) is not a closure.
 */
export type ClosedState = 'deactivated' | 'banned';
export type AccountClosure = { status: ClosedState; reason: string | null };

const CLOSED_CODES: Record<string, ClosedState> = { account_banned: 'banned', account_deactivated: 'deactivated' };

/** The admin's own words (whitespace-collapsed, at most 500 characters), or null. */
export function cleanReason(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.replace(/\s+/g, ' ').trim().slice(0, 500);
  return text || null;
}

export function closureFromResponse(status: number, body: unknown): AccountClosure | null {
  if (status !== 403 || !body || typeof body !== 'object') return null;
  const top = body as Record<string, unknown>;
  const detail = top.detail && typeof top.detail === 'object' ? (top.detail as Record<string, unknown>) : null;
  const code = typeof top.code === 'string' ? top.code : typeof detail?.code === 'string' ? detail.code : '';
  const fromStatus = typeof detail?.accountStatus === 'string' ? `account_${detail.accountStatus}` : '';
  const closed = CLOSED_CODES[code] ?? CLOSED_CODES[fromStatus];
  if (!closed) return null;
  return { status: closed, reason: cleanReason(top.reason ?? detail?.reason) };
}

/** Staff and admin accounts are refused on mobile: 403 {detail: {form, mobileAccess: "staff_not_allowed"}}. */
export function isStaffRefusal(status: number, body: unknown) {
  if (status !== 403 || !body || typeof body !== 'object') return false;
  const detail = (body as { detail?: unknown }).detail;
  return !!detail && typeof detail === 'object' && (detail as { mobileAccess?: unknown }).mobileAccess === 'staff_not_allowed';
}
