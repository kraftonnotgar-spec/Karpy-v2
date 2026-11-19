/**
 * Installation id (pure: randomness and storage are injected; tested in tests/device-id.test.ts).
 *
 * The backend binds sign-in codes, trusted-device tokens, refresh tokens and push registrations
 * to `device_id`: 32-128 characters of `A-Za-z0-9_-`, generated once per install and kept in
 * secure storage. Never derived from hardware ids.
 */
export const DEVICE_ID_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
export const DEVICE_ID_LENGTH = 43;

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

export function isValidDeviceId(value: unknown): value is string {
  return typeof value === 'string' && DEVICE_ID_PATTERN.test(value);
}

/** `randomBytes(n)` must be a cryptographic source (expo-crypto getRandomBytes in the app). */
export function makeDeviceId(randomBytes: (count: number) => Uint8Array, length: number = DEVICE_ID_LENGTH): string {
  if (length < 32 || length > 128) throw new RangeError('device id length must be 32-128');
  let out = '';
  for (const byte of randomBytes(length)) out += ALPHABET[byte & 63];
  return out;
}

export type KeyValueStore = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
};

/** Returns the stored id, or creates, stores and returns a new one (also replacing a malformed one). */
export async function getOrCreateDeviceId(store: KeyValueStore, key: string, randomBytes: (count: number) => Uint8Array): Promise<string> {
  const existing = await store.getItem(key);
  if (isValidDeviceId(existing)) return existing;
  const id = makeDeviceId(randomBytes);
  await store.setItem(key, id);
  return id;
}
