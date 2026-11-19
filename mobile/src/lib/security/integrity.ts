/**
 * App integrity hook point (OFF in the starter).
 *
 * A project that needs a genuine-app check (Google Play Integrity, Apple App Attest) wires it
 * here and nowhere else:
 *   1. add the provider package (e.g. `npx expo install @expo/app-integrity`) and, for App
 *      Attest, pass `{ "appAttestEnvironment": "production" }` to ./plugins/with-hardening in
 *      app.json;
 *   2. make `integrityHeaders` fetch a server challenge, produce the platform proof and return
 *      it as headers (the backend decides the header names and the off / monitor / enforce
 *      policy);
 *   3. nothing else changes: lib/auth/auth-api.ts already sends these headers on login,
 *      verify-login and refresh.
 *
 * Never let a failed proof block sign-in on the client: the server owns the policy.
 */
export type IntegrityPurpose = 'sign_in' | 'session' | 'sensitive_action';

export async function integrityHeaders(_purpose: IntegrityPurpose, _deviceId: string): Promise<Record<string, string>> {
  return {};
}
