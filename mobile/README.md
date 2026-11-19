# Karpy mobile starter (Expo)

A neutral iOS / Android app that every Karpy-v2 project starts from. It talks to the KARPy
backend (`../backend`) and ships the parts every app needs, with no product features:

- **Sign-in** with email and password, a **new-device code** screen (with resend), **trusted
  devices** (`device_token`), **token refresh with rotation**, sign-out, and an **"account
  closed"** screen for deactivated / banned accounts. Staff accounts are refused with the
  server's own message.
- **App lock**: a 4-digit PIN (salted and stretched hash in the Keychain / Keystore, weak PINs
  refused, 5 wrong tries sign the device out) plus optional **biometrics**
  (`expo-local-authentication`), and auto-lock after a configurable time in the background.
- **Secure storage** wrapper (`expo-secure-store`) and an **installation id** created once per
  install (43 chars of `A-Za-z0-9_-`).
- **Light / dark theme** from one token file, with a System / Light / Dark choice.
- **Offline**: TanStack Query cache persisted to an AES-GCM encrypted file (allow-listed queries
  only), NetInfo-driven online state, an offline / back-online banner, requests that fail fast
  offline.
- **Push registration** (`expo-notifications`): the token is sent to the backend after sign-in
  and removed on sign-out.
- **Crash capture** (local `app-crash` native module) with an opt-in upload, off by default.
- A **tab shell**: Home, Activity (placeholder), Settings (theme, app lock, notifications, sign
  out).
- **i18n-ready**: every string is in `src/i18n/en.json`, read through `t()`.

Expo SDK 58, React Native 0.88, Expo Router, TanStack Query, Zustand, react-hook-form + zod,
Reanimated, lucide icons. Derived from the TeePay merchant app; everything product-specific was
removed (see "What was removed").

## Commands

```bash
npm install
cp .env.example .env            # then set EXPO_PUBLIC_API_BASE_URL
npm run typecheck && npm run lint && npm test
npx expo start                  # press i / a for a development build
```

Secure storage, biometrics, push and the crash module need a **development build**, not Expo Go:

```bash
npx expo run:android            # or run:ios (local toolchain)
npx eas-cli@latest build --profile development --platform android   # cloud
```

Add packages with `npx expo install <package>` (never plain `npm install <package>`).

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| Backend origin | `EXPO_PUBLIC_API_BASE_URL` or `app.json` `extra.apiBaseUrl` | `https://api.example.com` |
| App name | `EXPO_PUBLIC_APP_NAME` or `app.json` `name` | `Karpy` |
| Auto-lock seconds | `EXPO_PUBLIC_AUTO_LOCK_SECONDS` or `extra.autoLockSeconds` | `60` |
| Push token kind | `EXPO_PUBLIC_PUSH_PROVIDER` (`native` = APNs/FCM, `expo`) | `native` |
| Crash upload URL | `EXPO_PUBLIC_CRASH_REPORT_URL` or `extra.crashReportUrl` | empty = off |
| Bundle ids, scheme | `app.json` `ios.bundleIdentifier`, `android.package`, `scheme` | `com.example.karpy`, `karpy` |
| Colours (UI, splash, icon bg, notification accent) | `src/theme/tokens.ts` | neutral blue |

`app.config.ts` merges the environment and the theme colours into `app.json` at build time.
`EXPO_PUBLIC_*` values end up in the JavaScript bundle: never put a secret there.

## Backend contract

Base `${API_BASE_URL}/api/plugins/auth/mobile/v1`, JSON, errors are FastAPI `{"detail": ...}`.

| Call | Used by |
| --- | --- |
| `POST /login` {email, password, device_id, device_name, platform, device_token?} | sign-in; answers tokens or `{requiresOTP: true, challenge_token, resend_token, ...}` |
| `POST /verify-login` {challenge_token, code, device_id, device_name, platform} | code screen; answers tokens + `device_token` (kept to skip the code next time) |
| `POST /resend-login` {resend_token, device_id} | "Send a new code" |
| `POST /refresh` {refresh_token, device_id} | automatic; rotates the refresh token. 401 = sign in again; 403 `account_deactivated` / `account_banned` = closed screen |
| `POST /logout` {refresh_token, device_id} + bearer | sign-out |
| `GET /me` (bearer) | Home greeting (saved offline) |
| `POST /push-devices` (bearer) {device_id, platform, provider, token, app_version} | after sign-in / unlock when notifications are allowed |
| `DELETE /push-devices` (bearer) {device_id} | sign-out (before logout) |

Staff accounts get `403 {"detail": {"form": "...", "mobileAccess": "staff_not_allowed"}}`; the
sign-in screen shows the `form` text.

The HTTP client (`src/lib/api/client.ts`) adds the bearer, refreshes before sending when the
in-memory access token is missing or about to expire, refreshes once on a 401 (one shared
refresh for parallel requests) and retries, signs out only when the server refuses the refresh,
and keeps the session when the server could not be reached.

## Folder map

```
app.json / app.config.ts   Expo config (+ env and theme colours merged at build time)
eas.json                   build profiles (no ids or secrets)
assets/images/             placeholder icon, adaptive icon, splash, notification icon, favicon
modules/app-crash/         local Expo module: keeps the last native / fatal JS crash on device
plugins/with-hardening.js  release network config (no cleartext, system CAs), optional pins
plugins/pins.json          certificate pins: empty by default
src/app/                   screens (Expo Router)
  _layout.tsx              providers, session gating (Stack.Protected), auto-lock, error boundary
  index.tsx                redirect for the current session state
  (auth)/                  sign-in, verify (new-device code)
  (setup)/                 first sign-in on a device: create PIN, biometrics, notifications
  unlock.tsx               PIN / biometrics
  account-closed.tsx       deactivated / banned
  (app)/(tabs)/            Home, Activity (notifications), Settings
src/components/            UI kit (ui/), app mark, offline banner, privacy cover, crash prompt
src/i18n/                  en.json catalog, t()
src/lib/api/               HTTP client (pure), error parsing (pure), app wiring + errorMessage()
src/lib/auth/              auth API, session store, refresh (pure), PIN, biometrics, closure
src/lib/offline/           network watch, encrypted query cache, pure rules
src/lib/                   config, storage, device id, push, crash, haptics, queries, format, validation
src/lib/security/          integrity.ts: hook point for Play Integrity / App Attest (off)
src/theme/                 tokens.ts (the only file with colours), theme provider
tests/                     node --test unit tests for the pure modules
```

## Start a project from it (rename and brand)

1. Copy the folder. In `package.json` set `name`.
2. In `app.json` set `name`, `slug`, `scheme`, `ios.bundleIdentifier`, `android.package`
   (and keep `allowBackup: false`). Update `extraProguardRules` only if you rename the crash
   module package.
3. Replace the PNGs in `assets/images/` (same file names: icon 1024x1024, adaptive foreground /
   monochrome 1024x1024 with the mark inside the safe zone, splash-icon, a white
   notification-icon, favicon). Replace `src/components/app-mark.tsx` with your logo.
4. Change `brand` and the two palettes in `src/theme/tokens.ts`. The native splash, the adaptive
   icon background and the notification accent follow automatically.
5. Edit the wording in `src/i18n/en.json` (`{app}` is replaced by the app name everywhere).
6. Set `.env` / EAS environment variables (`EXPO_PUBLIC_API_BASE_URL`, ...). For EAS, run
   `npx eas-cli@latest init` (adds your own `extra.eas.projectId`), and for push set up FCM
   (`google-services.json`, referenced from `android.googleServicesFile`) and APNs credentials.
7. Optional hardening: add CA-level SPKI pins for your API host to `plugins/pins.json`, and wire
   an app-integrity provider in `src/lib/security/integrity.ts` (see the comment there).

## Add a feature tab

1. Create `src/app/(app)/(tabs)/<feature>.tsx` (copy `notifications.tsx`).
2. Register it in `src/app/(app)/(tabs)/_layout.tsx`:
   `<Tabs.Screen name="<feature>" options={{ title: t('tabs.<feature>'), tabBarIcon: ... }} />`.
3. Add the strings to `src/i18n/en.json`.
4. Put the API calls in `src/lib/<feature>.ts` using `api.get/post/...` with paths from
   `src/lib/config.ts`, and the query keys in `src/lib/queries.ts`. Add the key root to
   `PERSISTED_QUERY_ROOTS` only if the data is read-only and safe to keep on the device.
5. Detail screens: `src/app/(app)/<feature>/[id].tsx`, declared in `src/app/(app)/_layout.tsx`.
6. Pure logic goes in its own module with a test in `tests/`.
7. If a tapped notification should open it, add the route to `PUSH_ROUTES` in
   `src/lib/push-rules.ts`.

## What was removed from the source app

- All money, send, payout, withdraw, commerce (links, pages, products, invoices, control
  numbers, tap devices), analytics, support and legal screens and libraries; the offline game.
- Product branding, fonts, images, scenes, sounds and copy; the launch animation.
- Native modules `send-key` (hardware signing key), `sms-consent` (Android SMS User Consent) and
  `device-signals` (root / jailbreak / hook signals). The crash module was kept and renamed
  `app-crash` (native module name `AppCrash`, package `starter.appcrash`).
- App integrity (Play Integrity / App Attest) and its package: replaced by the documented hook
  in `src/lib/security/integrity.ts`.
- Certificate pins, store / EAS / Google / Apple ids, production hosts. The hardening plugin was
  kept with an empty pin list; App Attest entitlement is opt-in.
- Feature access ("service access"), restricted / suspended account cards and the forgot
  password flow (add the latter with the backend's password-reset endpoints when needed).
