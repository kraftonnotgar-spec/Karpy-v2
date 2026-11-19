import { api } from '@/lib/api';
import { paths } from '@/lib/config';
import { deviceFields } from '@/lib/device';
import { integrityHeaders } from '@/lib/security/integrity';
import type { Tokens } from './refresh';

/**
 * Mobile auth contract (KARPy `/api/plugins/auth/mobile/v1`, plugin docs MOBILE_AUTH.md).
 * All JSON; errors are FastAPI `{"detail": ...}` (parsed in lib/api/errors.ts).
 */
export type { Tokens };

export type SignedInUser = {
  id?: string | number;
  name?: string;
  email?: string;
  phone?: string | null;
  [key: string]: unknown;
};

export type SignedIn = Tokens & {
  user?: SignedInUser;
  device_token?: string;
  device_token_expires_in?: number;
};

export type OtpChallenge = {
  requiresOTP: true;
  channels: string[];
  resend_after?: number;
  challenge_token: string;
  challenge_expires_in?: number;
  resend_token: string;
  resend_expires_in?: number;
};

export type LoginResult = SignedIn | OtpChallenge;

export function needsOtp(result: LoginResult): result is OtpChallenge {
  return 'requiresOTP' in result && result.requiresOTP === true;
}

const base = paths.auth;

export const authApi = {
  login: async (body: { email: string; password: string; device_token?: string | null }) => {
    const device = await deviceFields();
    return api.post<LoginResult>(
      `${base}/login`,
      { email: body.email, password: body.password, ...device, ...(body.device_token ? { device_token: body.device_token } : {}) },
      { public: true, headers: await integrityHeaders('sign_in', device.device_id) },
    );
  },
  verifyLogin: async (body: { challenge_token: string; code: string }) => {
    const device = await deviceFields();
    return api.post<SignedIn>(
      `${base}/verify-login`,
      { challenge_token: body.challenge_token, code: body.code, ...device },
      { public: true, headers: await integrityHeaders('sign_in', device.device_id) },
    );
  },
  resendLogin: async (body: { resend_token: string }) => {
    const { device_id } = await deviceFields();
    return api.post<OtpChallenge>(`${base}/resend-login`, { resend_token: body.resend_token, device_id }, { public: true });
  },
  /** Rotates: the response carries a new refresh token that replaces the stored one. */
  refresh: async (body: { refresh_token: string; device_id: string }) =>
    api.post<Tokens>(`${base}/refresh`, body, {
      public: true,
      timeoutMs: 10000,
      headers: await integrityHeaders('session', body.device_id),
    }),
  /** Public on purpose: the access token may already be gone; the body names the session. */
  logout: (body: { refresh_token: string; device_id: string }, accessToken?: string | null) =>
    api.post<{ message?: string }>(`${base}/logout`, body, {
      public: true,
      timeoutMs: 8000,
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
    }),
  me: () => api.get<{ user: SignedInUser }>(`${base}/me`),
};
