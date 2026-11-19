# Mobile starter

`mobile/` is a neutral **Expo (React Native) starter**: Expo Router, TypeScript, TanStack Query.
It is derived from a production app and keeps its security and offline patterns, without any product
screens. Read [`mobile/AGENTS.md`](../mobile/AGENTS.md) before changing it (Expo changes every SDK).

## What is in it

| Area | Where |
|---|---|
| Routes (Expo Router) | `src/app/`: `(auth)/sign-in`, `(auth)/verify` (new-device code), `(setup)/create-pin`, `(setup)/biometrics`, `(setup)/notifications-intro`, `unlock`, `account-closed`, `(app)/(tabs)/home · notifications · settings` |
| API client | `src/lib/api/` — base URL from config, bearer token, single-flight refresh on `401`, typed errors |
| Auth | `src/lib/auth/` — sign-in/verify/resend/refresh/logout calls, session store, pending challenge, closed-account handling |
| App lock | `src/lib/auth/pin.ts`, `pin-rules.ts`, `biometrics.ts`; `unlock` screen; lock after background timeout |
| Secure storage, device id | `src/lib/storage.ts`, `src/lib/device-id.ts` (one random id per install, 32–128 chars) |
| Theme | `src/theme/tokens.ts` (the only file with colours), `theme.tsx` (light/dark) |
| Offline | `src/lib/offline/` (persisted query cache, rules), `components/offline-banner.tsx` |
| Push | `src/lib/push.ts`, `push-rules.ts` — device push token (native APNs/FCM by default, or Expo with `EXPO_PUBLIC_PUSH_PROVIDER=expo`) sent to the backend after sign-in/unlock, removed on sign-out |
| Crash reporter | `modules/app-crash` (native module) + `src/lib/crash.ts`; upload endpoint configurable, off by default |
| App integrity | `src/lib/security/integrity.ts` — optional hook point (Play Integrity / App Attest) matching the backend's `auth.mobile.integrity` hook |
| Strings | `src/i18n/en.json` + `t()` |
| Tests | `tests/*.test.ts` (Node test runner) |

## Backend contract

Base `${EXPO_PUBLIC_API_BASE_URL}/api/plugins/auth/mobile/v1` — full contract:
[`backend/karpy_platform/plugins/auth/MOBILE_AUTH.md`](../backend/karpy_platform/plugins/auth/MOBILE_AUTH.md).

`POST /login` → tokens or `requiresOTP` · `POST /verify-login` → tokens + `device_token` ·
`POST /resend-login` · `POST /refresh` (rotates; `401` = sign in again; `403 account_*` = closed account) ·
`POST /logout` · `GET /me` · `POST|DELETE /push-devices`.

Other plugin APIs accept the same bearer token (`Authorization: Bearer <access token>`).

## Commands

```bash
cd mobile
cp .env.example .env            # EXPO_PUBLIC_API_BASE_URL=http://<your machine's LAN IP>:9000 for a phone
npm install
npx expo start                  # Expo Go / dev build
npm run typecheck && npm run lint && npm test
```

Native modules (crash reporter) need a development build (`npx expo run:android|ios` or EAS).
`android/` and `ios/` are generated (Continuous Native Generation) and git-ignored.

## Making it a product app

1. `app.json`: `name`, `slug`, `scheme`, `ios.bundleIdentifier`, `android.package`, icons/splash.
2. `src/theme/tokens.ts`: brand colours; `src/i18n/en.json`: copy.
3. `eas.json` + EAS project id (in your product repo, not in Karpy-v2).
4. Add feature tabs under `src/app/(app)/(tabs)/` and API calls under `src/lib/`; reuse the API client.
5. Push sending: add a push provider plugin on the backend that reads `auth_push_devices`.
