import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { AndroidImportance, AndroidNotificationVisibility } from 'expo-notifications';
import { router, type Href } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { t } from '@/i18n';
import { api } from '@/lib/api';
import { config, paths } from '@/lib/config';
import { deviceId } from '@/lib/device';
import { providerForNativeToken, safePushHref, type PushProvider } from './push-rules';

/**
 * Push registration with the backend:
 *   POST   /push-devices {device_id, platform, provider, token, app_version} -> {registered: true}
 *   DELETE /push-devices {device_id}                                         -> {removed: true}
 * Registered after sign-in / unlock when permission is granted (and again when the OS rotates the
 * token); removed on sign-out. The server also drops the registration when it closes an account.
 *
 * Provider: config.pushMode "native" sends the APNs (iOS) / FCM (Android) device token;
 * "expo" sends an Expo push token (needs extra.eas.projectId). Push needs a development build.
 */
const native = Platform.OS === 'ios' || Platform.OS === 'android';

export async function configureChannels() {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync('default', {
    name: t('push.channelDefault'),
    importance: AndroidImportance.DEFAULT,
    lockscreenVisibility: AndroidNotificationVisibility.PRIVATE,
  });
}

if (native) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  });
}

export async function notificationPermission(): Promise<'granted' | 'undetermined' | 'denied'> {
  if (!native) return 'denied';
  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  if (status === 'granted') return 'granted';
  return canAskAgain ? 'undetermined' : 'denied';
}

/** Shows the OS prompt (only after the user chose to turn notifications on). */
export async function requestNotificationPermission() {
  if (!native) return false;
  const { status } = await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowSound: true, allowBadge: false } });
  return status === 'granted';
}

async function pushToken(): Promise<{ provider: PushProvider; token: string } | null> {
  try {
    if (config.pushMode === 'expo') {
      if (!config.easProjectId) return null;
      const token = await Notifications.getExpoPushTokenAsync({ projectId: config.easProjectId });
      return { provider: 'expo', token: token.data };
    }
    const token = await Notifications.getDevicePushTokenAsync();
    const provider = providerForNativeToken(token.type);
    return provider ? { provider, token: String(token.data) } : null;
  } catch {
    // No token in this build (e.g. FCM not configured).
    return null;
  }
}

/** Registers (or refreshes) this installation's push token. Resolves false when it could not. */
export async function registerPushDevice(): Promise<boolean> {
  if (!native || !Device.isDevice) return false;
  if ((await notificationPermission()) !== 'granted') return false;
  await configureChannels();
  const token = await pushToken();
  if (!token) return false;
  await api.post<{ registered: boolean }>(`${paths.auth}/push-devices`, {
    device_id: await deviceId(),
    platform: config.platform === 'android' ? 'android' : 'ios',
    provider: token.provider,
    token: token.token,
    app_version: config.appVersion,
  });
  return true;
}

/** Best effort: signing out must still succeed offline. */
export async function unregisterPushDevice() {
  if (!native) return;
  try {
    await api.del<{ removed: boolean }>(`${paths.auth}/push-devices`, { device_id: await deviceId() }, { timeoutMs: 8000 });
  } catch {
    // The server drops dead tokens itself.
  }
}

const handled = new Set<string>();

/** Registers once unlocked and routes a tapped notification (cold start included). */
function useNativePush(unlocked: boolean) {
  const last = Notifications.useLastNotificationResponse();
  useEffect(() => {
    if (!unlocked) return;
    void registerPushDevice().catch(() => false);
    const sub = Notifications.addPushTokenListener(() => void registerPushDevice().catch(() => false));
    return () => sub.remove();
  }, [unlocked]);

  useEffect(() => {
    if (!unlocked || !last || last.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const id = last.notification.request.identifier;
    if (handled.has(id)) return;
    handled.add(id);
    const href = safePushHref((last.notification.request.content.data as { href?: unknown } | undefined)?.href);
    router.push((href ?? '/notifications') as Href);
  }, [last, unlocked]);
}

/** Native only: the web preview has no notification module. */
export const usePush: (unlocked: boolean) => void = native ? useNativePush : () => {};
