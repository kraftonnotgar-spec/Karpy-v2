import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { pushMode } from './push-rules';

/**
 * Runtime configuration. Sources, first match wins:
 *   1. EXPO_PUBLIC_* environment variables (inlined at build time, see .env.example);
 *   2. app.json `expo.extra` (also filled from the same variables by app.config.ts);
 *   3. the safe defaults below.
 */
type Extra = {
  apiBaseUrl?: string;
  autoLockSeconds?: number;
  pushProvider?: string;
  crashReportUrl?: string;
  eas?: { projectId?: string };
};

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

function trimSlash(value: string) {
  return value.replace(/\/+$/, '');
}

const autoLockSeconds = Number(process.env.EXPO_PUBLIC_AUTO_LOCK_SECONDS || extra.autoLockSeconds || 60);

export const config = {
  appName: Constants.expoConfig?.name ?? 'App',
  appVersion: Constants.expoConfig?.version ?? '1.0.0',
  appEnv: process.env.EXPO_PUBLIC_APP_ENV ?? 'development',
  /** Backend origin, e.g. https://api.example.com (no trailing slash). */
  apiBaseUrl: trimSlash(process.env.EXPO_PUBLIC_API_BASE_URL || extra.apiBaseUrl || 'https://api.example.com'),
  /** Background time after which the app asks for the PIN / biometrics again. */
  autoLockMs: (Number.isFinite(autoLockSeconds) && autoLockSeconds > 0 ? autoLockSeconds : 60) * 1000,
  pushMode: pushMode(process.env.EXPO_PUBLIC_PUSH_PROVIDER || extra.pushProvider),
  /** Empty = crash upload off (the default). */
  crashReportUrl: (process.env.EXPO_PUBLIC_CRASH_REPORT_URL || extra.crashReportUrl || '').trim(),
  easProjectId: extra.eas?.projectId,
  platform: Platform.OS === 'ios' ? ('ios' as const) : Platform.OS === 'android' ? ('android' as const) : ('web' as const),
} as const;

/** API path prefixes on the backend. */
export const paths = {
  auth: '/api/plugins/auth/mobile/v1',
} as const;
