import { create } from 'zustand';

import { installTokenSource } from '@/lib/api';
import { deviceId } from '@/lib/device';
import { allowOfflineCache, wipeOfflineCache } from '@/lib/offline/cache';
import { unregisterPushDevice } from '@/lib/push';
import { queryClient } from '@/lib/queries';
import { getItem, getJSON, keys, removeItem, setItem, setJSON } from '@/lib/storage';
import type { AccountClosure } from './account-status';
import { authApi, type SignedInUser, type Tokens } from './auth-api';
import { setBiometricsEnabled } from './biometrics';
import { useClosure } from './closure';
import { clearPin, hasPin } from './pin';
import { createRefresher, usableAccessToken } from './refresh';

/**
 * Session state machine:
 *   booting   -> signedOut   (no refresh token on this device)
 *   booting   -> locked      (signed in before; PIN / biometrics opens it)
 *   signedOut -> setup       (first sign-in on this device: create PIN, offer biometrics, push)
 *   setup | locked -> unlocked
 *   unlocked  -> locked      (background longer than config.autoLockMs)
 *
 * Tokens: the access token lives in memory only; the refresh token (rotated on every refresh)
 * and the trusted-device token live in secure storage. Boot reads only secure storage, so the
 * app opens offline.
 */
export type SessionStatus = 'booting' | 'signedOut' | 'setup' | 'locked' | 'unlocked';

type StoredSession = { refresh_token: string; user?: SignedInUser };

type SessionState = {
  status: SessionStatus;
  user: SignedInUser | null;
  accessToken: string | null;
  accessExpiresAt: number;
  boot: () => Promise<void>;
  completeSignIn: (tokens: Tokens, user?: SignedInUser, trustedDeviceToken?: string) => Promise<void>;
  finishSetup: () => void;
  unlock: () => void;
  lock: () => void;
  signOut: (options?: { revoke?: boolean }) => Promise<void>;
  /** Deactivated or banned: wipe this device and show the "account closed" screen. */
  closeAccount: (closure: AccountClosure) => Promise<void>;
  setUser: (user: SignedInUser) => void;
};

/** Sent with the next /login so a trusted device skips the code. */
export function trustedDeviceToken() {
  return getItem(keys.trustedDevice);
}

async function wipeDevice(options: { forgetTrustedDevice: boolean }) {
  allowOfflineCache(false);
  queryClient.clear();
  await Promise.all([
    removeItem(keys.session),
    options.forgetTrustedDevice ? removeItem(keys.trustedDevice) : Promise.resolve(),
    clearPin(),
    setBiometricsEnabled(false),
    wipeOfflineCache(),
  ]);
}

export const useSession = create<SessionState>((set, get) => ({
  status: 'booting',
  user: null,
  accessToken: null,
  accessExpiresAt: 0,

  boot: async () => {
    const stored = await getJSON<StoredSession>(keys.session);
    if (!stored?.refresh_token) {
      void wipeOfflineCache();
      set({ status: 'signedOut' });
      return;
    }
    const pin = await hasPin();
    allowOfflineCache(pin);
    set({ user: stored.user ?? null, status: pin ? 'locked' : 'signedOut' });
    if (!pin) {
      // Signed in but setup never finished: start again from the password.
      await removeItem(keys.session);
      void wipeOfflineCache();
    }
  },

  completeSignIn: async (tokens, user, trusted) => {
    if (trusted) await setItem(keys.trustedDevice, trusted);
    await setJSON(keys.session, { refresh_token: tokens.refresh_token, user } satisfies StoredSession);
    allowOfflineCache(true);
    set({
      accessToken: tokens.access_token,
      accessExpiresAt: Date.now() + tokens.expires_in * 1000,
      user: user ?? null,
      status: (await hasPin()) ? 'unlocked' : 'setup',
    });
  },

  finishSetup: () => set({ status: 'unlocked' }),
  unlock: () => set({ status: 'unlocked' }),
  lock: () => {
    if (get().status === 'unlocked') set({ status: 'locked' });
  },

  setUser: (user) => {
    set({ user });
    void getJSON<StoredSession>(keys.session).then((stored) => {
      if (stored) void setJSON(keys.session, { ...stored, user });
    });
  },

  signOut: async ({ revoke = true } = {}) => {
    const stored = await getJSON<StoredSession>(keys.session);
    if (revoke && stored?.refresh_token) {
      // Remove push first: it needs the bearer, which logout revokes.
      await unregisterPushDevice();
      try {
        await authApi.logout({ refresh_token: stored.refresh_token, device_id: await deviceId() }, get().accessToken);
      } catch {
        // The server session expires on its own; local sign-out must not fail.
      }
    }
    await wipeDevice({ forgetTrustedDevice: false });
    set({ status: 'signedOut', accessToken: null, accessExpiresAt: 0 });
  },

  closeAccount: async (closure) => {
    // Shown first, so the sign-out redirect lands on the closed screen, not on sign-in.
    useClosure.getState().show(closure);
    await wipeDevice({ forgetTrustedDevice: true });
    set({ status: 'signedOut', user: null, accessToken: null, accessExpiresAt: 0 });
  },
}));

const refresh = createRefresher({
  readRefreshToken: async () => (await getJSON<StoredSession>(keys.session))?.refresh_token ?? null,
  saveRefreshToken: async (token) => {
    const stored = await getJSON<StoredSession>(keys.session);
    await setJSON(keys.session, { ...stored, refresh_token: token } satisfies StoredSession);
  },
  deviceId,
  callRefresh: (body) => authApi.refresh(body),
  onTokens: (tokens) => useSession.setState({ accessToken: tokens.access_token, accessExpiresAt: Date.now() + tokens.expires_in * 1000 }),
  onClosed: (closure) => useSession.getState().closeAccount(closure),
});

installTokenSource({
  getAccessToken: () => {
    const { accessToken, accessExpiresAt } = useSession.getState();
    return usableAccessToken(accessToken, accessExpiresAt);
  },
  refresh,
  onSessionLost: () => {
    // closeAccount already moved to signedOut; only sign out a session that is still around.
    if (useSession.getState().status !== 'signedOut') void useSession.getState().signOut({ revoke: false });
  },
});
