This is the product-neutral Expo / React Native starter of the Karpy-v2 platform. Every project
copies it and brands it. Prioritize mobile-first patterns, performance, and cross-platform
compatibility, and keep the starter neutral (see "Neutrality rules").

## Expo has changed — do not trust your training data

Expo ships breaking changes every SDK release. APIs you remember are likely renamed, moved, or removed. Before writing any code that touches an Expo, EAS, or React Native API:

1. Read the major version of the `expo` package in `package.json`.
2. Fetch the matching versioned docs: `https://docs.expo.dev/versions/v<major>.0.0/`
3. For anything else, fetch https://docs.expo.dev/llms.txt — an index of all Expo docs with corrections to common LLM misconceptions. Follow its links to the specific page you need; never answer from memory.

## Commands

Use `bunx` instead of `npx` if the project uses bun (`bun.lock` present).

```bash
npx expo install <package>  # ALWAYS use instead of npm/yarn/pnpm/bun add — resolves SDK-compatible versions
npx expo start              # start the dev server
npm run lint                # lint (eslint-config-expo)
npm run typecheck           # tsc --noEmit
npm test                    # node --test tests/*.test.ts
npx expo-doctor             # diagnose dependency and config issues
npx expo install --fix      # fix incompatible package versions
```

Run lint, typecheck and tests before declaring any task done.

## Navigation & Routing

- Use **Expo Router** for all navigation. Routes live in `src/app/` — every file there is a screen, `_layout.tsx` files define navigators. Keep non-route code (components, hooks, utils) outside `src/app/`.
- Import `Link`, `router`, and `useLocalSearchParams` from `expo-router`.
- Session gating is done with `Stack.Protected` in `src/app/_layout.tsx`; do not add redirects in screens.
- Docs: https://docs.expo.dev/router/introduction.md

## Building with EAS

Use EAS to build, sign, and submit the app in the cloud (`eas build`, `eas submit`) and to ship over-the-air updates (`eas update`) — no local Xcode or Android Studio required. Run EAS CLI as `bunx eas-cli <command>` in Bun projects, or `npx eas-cli@latest <command>` otherwise; substitute that for bare `eas` in docs examples.
Docs: https://docs.expo.dev/eas/index.md

## Rules

- If `ios/` and `android/` directories do not exist, they are generated (Continuous Native Generation). Never create or edit them by hand — configure native behavior in `app.json`, `app.config.ts` and config plugins (`plugins/`).
- Expo Go only includes its bundled native modules. After adding a library with native code, the app needs a development build: `npx expo run:ios|android` locally, or `eas build --profile development`.
- Prefer recommended Expo modules over third-party libraries, and check your available skills before adding dependencies. Docs: https://docs.expo.dev/versions/latest/index.md
- Colours live only in `src/theme/tokens.ts`. No hex colour anywhere else (screens read `useTheme().c`; native colours come through `app.config.ts`).
- Every user-facing string goes through `t()` (`src/i18n`) with the text in `src/i18n/en.json`.
- Pure logic (no React Native imports) goes in its own module with a `node --test` test in `tests/`. Pure modules import each other with an explicit `.ts` extension so node can run them.
- One HTTP client: `api` from `src/lib/api`. Never call `fetch` directly for the backend; never store the access token (memory only); never log tokens. No `console.*` in `src/`.
- Secure data goes through `src/lib/storage.ts` (expo-secure-store, `WHEN_UNLOCKED_THIS_DEVICE_ONLY`). Never AsyncStorage for anything sensitive. Add new keys to `keys` there.
- Only allow-listed read-only queries are persisted offline (`PERSISTED_QUERY_ROOTS` in `src/lib/offline/rules.ts`).
- No secrets in the app: `EXPO_PUBLIC_*` values are public. No API keys, signing keys, EAS project ids or store ids are committed in the starter.

## Neutrality rules (starter only)

- No product names, brand assets, store ids, bundle ids other than the `com.example.*` placeholders, certificate pins or EAS project ids in this folder. Projects add their own after copying it.
- No product features (payments, commerce, games, ...) in the starter: it ships auth, app lock, theming, offline cache, push registration, crash capture and an empty tab shell only.
- Backend contract: KARPy auth plugin, `/api/plugins/auth/mobile/v1` (login, verify-login, resend-login, refresh, logout, me, push-devices). Change the client and its tests together with the backend.
