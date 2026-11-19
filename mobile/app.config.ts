import type { ConfigContext, ExpoConfig } from 'expo/config';

import { brand } from './src/theme/tokens.ts';

/**
 * Dynamic config on top of app.json:
 * - colours for the native splash, adaptive icon and notification accent come from the theme
 *   tokens (src/theme/tokens.ts), so no colour is written twice;
 * - EXPO_PUBLIC_* environment variables (see .env.example) override `extra`, so one build
 *   profile can point at staging and another at production without editing app.json.
 */
function env(name: string): string | undefined {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : undefined;
}

export default ({ config }: ConfigContext): ExpoConfig => {
  const extra = config.extra ?? {};
  const autoLock = Number(env('EXPO_PUBLIC_AUTO_LOCK_SECONDS'));
  return {
    ...config,
    name: env('EXPO_PUBLIC_APP_NAME') ?? config.name ?? 'Karpy',
    slug: config.slug ?? 'karpy',
    backgroundColor: brand.splashLight,
    android: {
      ...config.android,
      adaptiveIcon: { ...config.android?.adaptiveIcon, backgroundColor: brand.splashLight },
    },
    plugins: [
      ...(config.plugins ?? []),
      ['expo-notifications', { icon: './assets/images/notification-icon.png', color: brand.primary }],
      [
        'expo-splash-screen',
        {
          image: './assets/images/splash-icon.png',
          imageWidth: 96,
          backgroundColor: brand.splashLight,
          dark: { image: './assets/images/splash-icon.png', backgroundColor: brand.splashDark },
        },
      ],
    ],
    extra: {
      ...extra,
      apiBaseUrl: env('EXPO_PUBLIC_API_BASE_URL') ?? extra.apiBaseUrl,
      autoLockSeconds: Number.isFinite(autoLock) && autoLock > 0 ? autoLock : extra.autoLockSeconds,
      pushProvider: env('EXPO_PUBLIC_PUSH_PROVIDER') ?? extra.pushProvider,
      crashReportUrl: env('EXPO_PUBLIC_CRASH_REPORT_URL') ?? extra.crashReportUrl,
    },
  };
};
