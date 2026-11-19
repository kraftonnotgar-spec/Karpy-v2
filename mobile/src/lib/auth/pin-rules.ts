/** App PIN rules (pure, tested in tests/pin.test.ts). */
export const PIN_LENGTH = 4;
export const MAX_ATTEMPTS = 5;

/** Sequences and repeats are refused: they are the first PINs anyone tries. */
export function weakPin(pin: string) {
  if (/^(\d)\1+$/.test(pin)) return true;
  const digits = pin.split('').map(Number);
  const asc = digits.every((d, i) => i === 0 || d === (digits[i - 1] + 1) % 10);
  const desc = digits.every((d, i) => i === 0 || d === (digits[i - 1] + 9) % 10);
  return asc || desc || ['1212', '2580', '0852', '1004', '2000', '1122'].includes(pin);
}

/** Remaining tries after `used` wrong entries (0 = sign out). */
export function remainingAttempts(used: number) {
  return Math.max(0, MAX_ATTEMPTS - used);
}

/** True when the app was in the background longer than the auto-lock window. */
export function shouldLock(backgroundAt: number | null, now: number, autoLockMs: number) {
  return backgroundAt !== null && now - backgroundAt >= autoLockMs;
}
