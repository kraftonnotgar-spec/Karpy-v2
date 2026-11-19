import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { defaultShouldDehydrateQuery, type Query } from '@tanstack/react-query';
import type { PersistQueryClientOptions } from '@tanstack/react-query-persist-client';
import { AESEncryptionKey, AESSealedData, aesDecryptAsync, aesEncryptAsync } from 'expo-crypto';
import { File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';

import { config } from '@/lib/config';
import { getItem, keys, removeItem, setItem } from '@/lib/storage';
import { OFFLINE_MAX_AGE_MS, shouldPersistKey, utf8Decode, utf8Encode } from './rules';

/**
 * The saved copy of read-only queries (see PERSISTED_QUERY_ROOTS in ./rules.ts) so screens open
 * offline with the last data.
 *
 * Storage: one file in the app's private documents folder (excluded from Android backups by
 * `allowBackup: false`), encrypted with AES-256-GCM. The key is random per install and lives in
 * the Keychain / Keystore. Wiping deletes both the file and the key (sign-out, PIN lockout,
 * closed account). If encryption is unavailable nothing is written.
 */
const FILE_NAME = 'offline-cache.bin';
const native = Platform.OS === 'ios' || Platform.OS === 'android';

let key: AESEncryptionKey | null = null;
let allowWrites = false;
/** Every file operation runs in order, so a wipe can never be overtaken by an older write. */
let queue: Promise<unknown> = Promise.resolve();

function serial<T>(op: () => Promise<T>): Promise<T> {
  const run = queue.then(op, op);
  queue = run.catch(() => undefined);
  return run;
}

function file() {
  return new File(Paths.document, FILE_NAME);
}

async function cacheKey(create: boolean): Promise<AESEncryptionKey | null> {
  if (key) return key;
  const stored = await getItem(keys.offlineKey);
  if (stored) {
    key = await AESEncryptionKey.import(stored, 'hex');
    return key;
  }
  if (!create) return null;
  const fresh = await AESEncryptionKey.generate();
  await setItem(keys.offlineKey, await fresh.encoded('hex'));
  key = fresh;
  return key;
}

const store = {
  getItem: (_name: string) =>
    serial(async () => {
      if (!native) return null;
      try {
        const f = file();
        if (!f.exists) return null;
        const k = await cacheKey(false);
        if (!k) return null;
        const sealed = AESSealedData.fromCombined(await f.bytes());
        return utf8Decode(await aesDecryptAsync(sealed, k));
      } catch {
        return null;
      }
    }),
  setItem: (_name: string, value: string) =>
    serial(async () => {
      if (!native || !allowWrites) return;
      try {
        const k = await cacheKey(true);
        if (!k) return;
        const sealed = await aesEncryptAsync(utf8Encode(value), k);
        await file().write(await sealed.combined('bytes'));
      } catch {
        // Best effort; the app works without it.
      }
    }),
  removeItem: (_name: string) =>
    serial(async () => {
      try {
        const f = file();
        if (f.exists) f.delete();
      } catch {
        // already gone
      }
    }),
};

export const offlinePersister = createAsyncStoragePersister({
  storage: store,
  key: 'offline-cache',
  throttleTime: 2000,
});

/** Options for PersistQueryClientProvider in the root layout. */
export const persistOptions: Omit<PersistQueryClientOptions, 'queryClient'> = {
  persister: offlinePersister,
  maxAge: OFFLINE_MAX_AGE_MS,
  // A new app version starts with a fresh cache, so shapes never mismatch.
  buster: `v${config.appVersion}`,
  dehydrateOptions: {
    shouldDehydrateQuery: (query: Query) => defaultShouldDehydrateQuery(query) && shouldPersistKey(query.queryKey),
    shouldDehydrateMutation: () => false,
  },
};

/** Writes are allowed only while someone is signed in on this device. */
export function allowOfflineCache(allowed: boolean) {
  allowWrites = allowed;
}

/** Forget everything saved for offline: the file and its key. */
export function wipeOfflineCache() {
  allowWrites = false;
  return serial(async () => {
    try {
      const f = file();
      if (f.exists) f.delete();
    } catch {
      // already gone
    }
    key = null;
    await removeItem(keys.offlineKey);
  });
}
