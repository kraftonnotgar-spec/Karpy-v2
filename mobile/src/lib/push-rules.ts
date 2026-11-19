/** Push rules (pure, tested in tests/push.test.ts). */
export type PushProvider = 'expo' | 'fcm' | 'apns';
export type PushMode = 'native' | 'expo';

/** expo-notifications DevicePushToken.type ('ios' | 'android' | 'web') -> backend provider. */
export function providerForNativeToken(tokenType: string): PushProvider | null {
  if (tokenType === 'ios') return 'apns';
  if (tokenType === 'android') return 'fcm';
  return null;
}

export function pushMode(value: unknown): PushMode {
  return value === 'expo' ? 'expo' : 'native';
}

/**
 * In-app routes a tapped notification may open (`data.href`). Anything else opens the
 * notifications tab, so a push can never deep-link to an arbitrary screen. Extend per project.
 */
export const PUSH_ROUTES: readonly RegExp[] = [/^\/(home|notifications|settings)$/];

export function safePushHref(href: unknown, routes: readonly RegExp[] = PUSH_ROUTES): string | null {
  if (typeof href !== 'string' || href.length > 200) return null;
  return routes.some((r) => r.test(href)) ? href : null;
}
