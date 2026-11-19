import { requireOptionalNativeModule } from 'expo';
import { Platform } from 'react-native';

import { config } from './config';

/**
 * Crash reporter. The last crash (native, or a fatal JavaScript error) is kept only on this
 * device by the local `AppCrash` native module (modules/app-crash). On the next launch the app
 * offers to upload it, but only when `crashReportUrl` is configured (EXPO_PUBLIC_CRASH_REPORT_URL);
 * the default is off. Without the native module (Expo Go, web) everything is a no-op.
 *
 * Upload: POST <crashReportUrl> {app, version, platform, environment, report} as JSON. Point it at
 * your own endpoint, or replace `uploadCrashReport` with a vendor SDK call.
 */
type NativeCrash = { recordJs(text: string): boolean; read(): string; clear(): boolean };
const native = requireOptionalNativeModule<NativeCrash>('AppCrash');

type ErrorUtilsType = {
  getGlobalHandler(): (error: unknown, isFatal?: boolean) => void;
  setGlobalHandler(handler: (error: unknown, isFatal?: boolean) => void): void;
};

export const crashUploadEnabled = !!native && config.crashReportUrl.length > 0;

/** Writes `error` synchronously so it survives the app closing right after. */
export function recordCrash(error: unknown, where = 'app') {
  if (!native) return;
  const e = error instanceof Error ? error : new Error(String(error));
  const text = `app=${config.appVersion} ${Platform.OS}\nwhere=${where}\n${e.name}: ${e.message}\n${e.stack ?? ''}`;
  try {
    native.recordJs(text);
  } catch {
    // Never make a crash worse.
  }
}

let installed = false;

/** Catches fatal JavaScript errors app-wide (call once at startup). */
export function installCrashCapture() {
  if (installed || !native) return;
  installed = true;
  const utils = (globalThis as { ErrorUtils?: ErrorUtilsType }).ErrorUtils;
  if (!utils) return;
  const previous = utils.getGlobalHandler();
  utils.setGlobalHandler((error, isFatal) => {
    if (isFatal) recordCrash(error, 'fatal');
    previous(error, isFatal);
  });
}

/** The saved report, or '' when the app did not crash last time. */
export function lastCrash(): string {
  try {
    return native?.read() ?? '';
  } catch {
    return '';
  }
}

export function clearLastCrash() {
  try {
    native?.clear();
  } catch {
    // ignore
  }
}

export async function uploadCrashReport(report: string) {
  if (!config.crashReportUrl) return;
  const response = await fetch(config.crashReportUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      app: config.appName,
      version: config.appVersion,
      platform: config.platform,
      environment: config.appEnv,
      report: report.slice(0, 20000),
    }),
  });
  if (!response.ok) throw new Error(`crash upload failed: ${response.status}`);
}
