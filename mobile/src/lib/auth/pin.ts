import * as Crypto from 'expo-crypto';

import { getJSON, keys, removeItem, setJSON } from '@/lib/storage';
import { MAX_ATTEMPTS, remainingAttempts } from './pin-rules';

export { MAX_ATTEMPTS, PIN_LENGTH, weakPin } from './pin-rules';

/**
 * The app PIN only unlocks this app on this device. It is never sent to the server. The raw PIN
 * is never stored: only a salted, stretched SHA-256 lives in the Keychain / Keystore, and
 * MAX_ATTEMPTS wrong entries sign the device out (a password sign-in sets a new PIN).
 */
const ROUNDS = 1000;

type StoredPin = { salt: string; hash: string; rounds: number };

function hex(bytes: Uint8Array) {
  let out = '';
  for (const b of bytes) out += b.toString(16).padStart(2, '0');
  return out;
}

async function derive(pin: string, salt: string, rounds: number) {
  let value = `${salt}:${pin}`;
  for (let i = 0; i < rounds; i++) {
    value = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, `${salt}${value}`);
  }
  return value;
}

export async function hasPin() {
  return (await getJSON<StoredPin>(keys.pin)) !== null;
}

export async function savePin(pin: string) {
  const salt = hex(Crypto.getRandomBytes(16));
  const hash = await derive(pin, salt, ROUNDS);
  await setJSON(keys.pin, { salt, hash, rounds: ROUNDS } satisfies StoredPin);
  await setJSON(keys.pinAttempts, 0);
}

export type PinCheck = { ok: true } | { ok: false; remaining: number };

export async function checkPin(pin: string): Promise<PinCheck> {
  const stored = await getJSON<StoredPin>(keys.pin);
  if (!stored) return { ok: false, remaining: 0 };
  const attempts = (await getJSON<number>(keys.pinAttempts)) ?? 0;
  if (attempts >= MAX_ATTEMPTS) return { ok: false, remaining: 0 };
  const hash = await derive(pin, stored.salt, stored.rounds);
  if (hash === stored.hash) {
    await setJSON(keys.pinAttempts, 0);
    return { ok: true };
  }
  const used = attempts + 1;
  await setJSON(keys.pinAttempts, used);
  return { ok: false, remaining: remainingAttempts(used) };
}

export async function clearPin() {
  await removeItem(keys.pin);
  await removeItem(keys.pinAttempts);
}
