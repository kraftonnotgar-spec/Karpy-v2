/**
 * Pure offline rules (no React Native imports, tested in tests/offline.test.ts).
 *
 *  - when the phone counts as offline;
 *  - which queries are saved on the device for offline reading;
 *  - UTF-8 bytes for the encrypted cache file.
 */

/** The fields of a NetInfo state that matter here. */
export type NetSnapshot = { isConnected: boolean | null; isInternetReachable?: boolean | null };

/**
 * Offline only when the OS is sure: no network at all, or a network that definitely cannot
 * reach the internet. `null` (still checking) counts as online, so a slow first check never
 * blocks the app.
 */
export function isOfflineState(state: NetSnapshot): boolean {
  return state.isConnected === false || state.isInternetReachable === false;
}

/** Saved queries live at most this long on the device. */
export const OFFLINE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Query keys whose data is saved for offline reading. Opt-in: anything not listed stays in
 * memory only. Add your read-only feature lists here (and never secrets or one-time data).
 */
export const PERSISTED_QUERY_ROOTS: readonly string[] = ['me', 'notifications'];

export function shouldPersistKey(queryKey: readonly unknown[], roots: readonly string[] = PERSISTED_QUERY_ROOTS): boolean {
  const [head] = queryKey;
  return typeof head === 'string' && roots.includes(head) && queryKey.length === 1;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** "14:32" today, otherwise "3/11 14:32" (day/month). Used for "Last updated" labels. */
export function lastUpdatedTime(updatedAt: number, now: number = Date.now()): string | null {
  if (!updatedAt || !Number.isFinite(updatedAt)) return null;
  const at = new Date(updatedAt);
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  const today = new Date(now);
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  return updatedAt >= startToday ? time : `${at.getDate()}/${at.getMonth() + 1} ${time}`;
}

/** The newest of several `dataUpdatedAt` values (0 when nothing has loaded). */
export function newest(...times: (number | undefined)[]): number {
  return times.reduce<number>((max, t) => (t && t > max ? t : max), 0);
}

/** UTF-8 encode without relying on TextEncoder (kept explicit for every JS engine). */
export function utf8Encode(text: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let code = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00);
        i++;
      }
    }
    if (code < 0x80) out.push(code);
    else if (code < 0x800) out.push(0xc0 | (code >> 6), 0x80 | (code & 63));
    else if (code < 0x10000) out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
    else out.push(0xf0 | (code >> 18), 0x80 | ((code >> 12) & 63), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
  }
  return Uint8Array.from(out);
}

export function utf8Decode(bytes: Uint8Array): string {
  let out = '';
  let chunk: number[] = [];
  const flush = () => {
    out += String.fromCharCode(...chunk);
    chunk = [];
  };
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i];
    let code: number;
    if (b < 0x80) {
      code = b;
      i += 1;
    } else if (b >= 0xf0) {
      code = ((b & 7) << 18) | ((bytes[i + 1] & 63) << 12) | ((bytes[i + 2] & 63) << 6) | (bytes[i + 3] & 63);
      i += 4;
    } else if (b >= 0xe0) {
      code = ((b & 15) << 12) | ((bytes[i + 1] & 63) << 6) | (bytes[i + 2] & 63);
      i += 3;
    } else {
      code = ((b & 31) << 6) | (bytes[i + 1] & 63);
      i += 2;
    }
    if (code >= 0x10000) {
      code -= 0x10000;
      chunk.push(0xd800 + (code >> 10), 0xdc00 + (code & 1023));
    } else chunk.push(code);
    if (chunk.length > 4096) flush();
  }
  flush();
  return out;
}
