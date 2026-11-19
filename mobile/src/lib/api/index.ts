import { t, tHas } from '@/i18n';
import { config } from '@/lib/config';
import { networkOffline } from '@/lib/offline/network';
import { createApiClient, type TokenSource } from './client';
import { ApiError } from './errors';

export { ApiError, isNetworkFailure } from './errors';

/**
 * The app's one HTTP client. The session store (lib/auth/session.ts) installs the token
 * source at module load; until then every private call reports a lost session.
 */
let tokens: TokenSource = {
  getAccessToken: () => null,
  refresh: async () => null,
  onSessionLost: () => {},
};

export function installTokenSource(next: TokenSource) {
  tokens = next;
}

export const api = createApiClient({
  baseUrl: config.apiBaseUrl,
  fetch: (input, init) => fetch(input, init),
  isOffline: networkOffline,
  timeoutMs: 15000,
  headers: { 'X-Client': `mobile/${config.appVersion} (${config.platform})` },
  getAccessToken: () => tokens.getAccessToken(),
  refresh: () => tokens.refresh(),
  onSessionLost: () => tokens.onSessionLost(),
});

/** Codes whose app wording replaces whatever the server said. */
const APP_WORDING = new Set(['offline', 'network', 'timeout', 'session_expired']);

/** The text to show for any error: the server's message, else the translated text for its code. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return t('errors.generic');
  const key = `errors.${error.code}`;
  if (APP_WORDING.has(error.code) && tHas(key)) return t(key);
  if (error.message) return error.message;
  if (tHas(key)) return t(key);
  return t('errors.generic');
}
