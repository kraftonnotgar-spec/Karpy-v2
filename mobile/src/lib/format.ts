/**
 * Formatting helpers (pure, tested in tests/format.test.ts).
 *
 * Words such as "Today" come from the caller (already translated) so this file stays free of
 * i18n and React Native imports.
 */
function pad(n: number) {
  return String(n).padStart(2, '0');
}

/**
 * Server instants as Dates. KARPy writes UTC; a date-time without an offset (Python naive
 * isoformat) is taken as UTC instead of device-local time. Missing or unparseable values give
 * null instead of an Invalid Date.
 */
export function toDate(iso: string | number | Date | null | undefined): Date | null {
  if (iso === null || iso === undefined || iso === '') return null;
  if (iso instanceof Date) return Number.isNaN(iso.getTime()) ? null : iso;
  let value = String(iso).trim();
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(value)) value = `${value.replace(' ', 'T')}Z`;
  const d = typeof iso === 'number' ? new Date(iso) : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();

/** Whole calendar days between `d` and `now` (0 = today, 1 = yesterday). */
export function daysAgo(d: Date, now: Date = new Date()) {
  return Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
}

export function timeOf(iso: string | null | undefined) {
  const d = toDate(iso);
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '';
}

export function dayKey(iso: string | null | undefined) {
  const d = toDate(iso);
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : 'unknown';
}

/** Seconds -> "0:59", "4:05" (resend countdowns). */
export function countdown(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

/** Part of the day for greetings: 'morning' | 'afternoon' | 'evening' (an i18n key suffix). */
export function partOfDay(now = new Date()): 'morning' | 'afternoon' | 'evening' {
  const h = now.getHours();
  if (h < 12) return 'morning';
  if (h < 17) return 'afternoon';
  return 'evening';
}

export function firstName(name?: string | null) {
  const first = (name ?? '').trim().split(/\s+/)[0] ?? '';
  return first ? first.charAt(0).toUpperCase() + first.slice(1) : '';
}

export function initials(name?: string | null, fallback = '?') {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || fallback;
}

export function humanize(value?: string | null) {
  if (!value) return '';
  return value.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
}

/** "a•••@example.com" for showing where a code was sent. */
export function maskEmail(email?: string | null) {
  if (!email) return '';
  const [user, domain] = email.split('@');
  if (!domain) return email;
  return `${user.slice(0, 1)}•••@${domain}`;
}
