import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Small key/value store backed by the iOS Keychain / Android Keystore (expo-secure-store).
 * Everything uses WHEN_UNLOCKED_THIS_DEVICE_ONLY so secrets never leave the device through
 * backups. On web (local previews only) it falls back to memory, so nothing sensitive lands in
 * localStorage.
 */
const memory = new Map<string, string>();
const web = Platform.OS === 'web';

const options: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function getItem(key: string): Promise<string | null> {
  if (web) return memory.get(key) ?? null;
  try {
    return await SecureStore.getItemAsync(key, options);
  } catch {
    return null;
  }
}

export async function setItem(key: string, value: string): Promise<void> {
  if (web) {
    memory.set(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, options);
}

export async function removeItem(key: string): Promise<void> {
  if (web) {
    memory.delete(key);
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key, options);
  } catch {
    // already gone
  }
}

export async function getJSON<T>(key: string): Promise<T | null> {
  const raw = await getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function setJSON(key: string, value: unknown) {
  return setItem(key, JSON.stringify(value));
}

/** Every secure-storage key in one place (bump the version suffix to migrate a shape). */
export const keys = {
  session: 'app.session.v1',
  deviceId: 'app.device-id.v1',
  trustedDevice: 'app.trusted-device.v1',
  pin: 'app.pin.v1',
  pinAttempts: 'app.pin-attempts.v1',
  biometrics: 'app.biometrics.v1',
  theme: 'app.theme.v1',
  offlineKey: 'app.offline-cache-key.v1',
} as const;
