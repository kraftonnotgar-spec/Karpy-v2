import NetInfo, { type NetInfoState } from '@react-native-community/netinfo';
import { onlineManager } from '@tanstack/react-query';
import { create } from 'zustand';

import { isOfflineState } from './rules';

/**
 * One source of truth for "can this device reach the internet right now".
 *
 * NetInfo drives TanStack Query's onlineManager, so offline queries pause (keeping cached data
 * on screen) instead of retrying into timeouts, and resume plus refetch when the connection
 * returns. `networkOffline()` is a synchronous read for the HTTP client, which fails fast.
 */
type NetworkState = { online: boolean; offlineSince: number };

export const useNetwork = create<NetworkState>(() => ({ online: true, offlineSince: 0 }));

let offline = false;

export function networkOffline() {
  return offline;
}

function apply(state: Pick<NetInfoState, 'isConnected' | 'isInternetReachable'>) {
  const next = isOfflineState(state);
  if (next === offline) return;
  offline = next;
  useNetwork.setState({ online: !next, offlineSince: next ? Date.now() : 0 });
}

let started = false;

/** Called once at module load of the root layout. Safe to call again. */
export function startNetworkWatch() {
  if (started) return;
  started = true;
  onlineManager.setEventListener((setOnline) =>
    NetInfo.addEventListener((state) => {
      apply(state);
      setOnline(!offline);
    }),
  );
}

/** "Try again": asks the OS for a fresh answer. Resolves true when online. */
export async function recheckNetwork(): Promise<boolean> {
  try {
    apply(await NetInfo.refresh());
    onlineManager.setOnline(!offline);
  } catch {
    // Keep the last known answer.
  }
  return !offline;
}
