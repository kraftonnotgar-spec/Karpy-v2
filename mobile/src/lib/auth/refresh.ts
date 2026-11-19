import { closureFromResponse, type AccountClosure } from './account-status.ts';

/**
 * Session refresh with rotation (pure: storage and network are injected; tested in
 * tests/session-refresh.test.ts).
 *
 * POST /refresh {refresh_token, device_id} returns a NEW refresh token every time. The new one is
 * stored BEFORE the new access token is used: if the app dies in between, the stored token is
 * still the valid one (presenting an already-rotated token ends the session on the server).
 *
 * Outcomes:
 *   resolves the access token        -> success
 *   resolves null                    -> the server refused (401, or 403 not a closure): sign in again
 *   resolves null + onClosed(...)    -> 403 account_deactivated | account_banned
 *   rejects                          -> no answer / 5xx: keep the session, report the error
 */
export type Tokens = {
  token_type?: string;
  access_token: string;
  expires_in: number;
  refresh_token: string;
  refresh_expires_in?: number;
};

export type RefresherDeps = {
  readRefreshToken: () => Promise<string | null>;
  saveRefreshToken: (token: string) => Promise<void>;
  deviceId: () => Promise<string>;
  callRefresh: (body: { refresh_token: string; device_id: string }) => Promise<Tokens>;
  onTokens: (tokens: Tokens) => void;
  onClosed: (closure: AccountClosure) => Promise<void> | void;
};

export function createRefresher(deps: RefresherDeps) {
  return async function refresh(): Promise<string | null> {
    const refreshToken = await deps.readRefreshToken();
    if (!refreshToken) return null;
    let tokens: Tokens;
    try {
      tokens = await deps.callRefresh({ refresh_token: refreshToken, device_id: await deps.deviceId() });
    } catch (error) {
      const status = (error as { status?: number })?.status ?? 0;
      const closure = closureFromResponse(status, (error as { body?: unknown })?.body);
      if (closure) {
        await deps.onClosed(closure);
        return null;
      }
      if (status === 401 || status === 403) return null;
      throw error;
    }
    await deps.saveRefreshToken(tokens.refresh_token);
    deps.onTokens(tokens);
    return tokens.access_token;
  };
}

/** Access tokens are treated as expired a little early so a request never races the expiry. */
export const ACCESS_TOKEN_SKEW_MS = 10_000;

export function usableAccessToken(token: string | null, expiresAt: number, now: number = Date.now()) {
  return token && expiresAt - now > ACCESS_TOKEN_SKEW_MS ? token : null;
}
