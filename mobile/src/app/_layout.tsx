import { focusManager } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, router } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef } from 'react';
import { AppState, View, type AppStateStatus } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { PrivacyCover } from '@/components/privacy-cover';
import { Button } from '@/components/ui/button';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { useClosure } from '@/lib/auth/closure';
import { shouldLock } from '@/lib/auth/pin-rules';
import { useSession } from '@/lib/auth/session';
import { config } from '@/lib/config';
import { installCrashCapture, recordCrash } from '@/lib/crash';
import { persistOptions } from '@/lib/offline/cache';
import { startNetworkWatch } from '@/lib/offline/network';
import { usePush } from '@/lib/push';
import { queryClient } from '@/lib/queries';
import { AppThemeProvider, useTheme } from '@/theme/theme';
import { space } from '@/theme/tokens';

export const unstable_settings = { initialRouteName: 'index' };

// Fatal errors are kept on the device (modules/app-crash) for an opt-in report on next launch.
installCrashCapture();

// The native splash stays until the session has booted (local reads only, never the network).
void SplashScreen.preventAutoHideAsync();

// Connectivity drives TanStack Query (offline queries pause on saved data) and the HTTP client.
startNetworkWatch();

/** Any screen error lands here instead of closing the app. */
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => Promise<void> }) {
  const { c } = useTheme();
  useEffect(() => {
    recordCrash(error, 'screen');
  }, [error]);
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.xxxl, gap: space.md, backgroundColor: c.page }}>
      <Text variant="headline" align="center">
        {t('errorScreen.title')}
      </Text>
      <Text variant="callout" tone="muted" align="center">
        {t('errorScreen.body')}
      </Text>
      <View style={{ alignSelf: 'stretch', gap: space.sm, marginTop: space.sm }}>
        <Button label={t('common.tryAgain')} onPress={() => void retry()} />
        <Button label={t('errorScreen.home')} variant="ghost" onPress={() => router.replace('/')} />
      </View>
    </View>
  );
}

/** Locks the app after config.autoLockMs in the background; tells TanStack Query about focus. */
function useAppLifecycle() {
  const lock = useSession((s) => s.lock);
  const backgroundAt = useRef<number | null>(null);
  useEffect(() => {
    const onChange = (state: AppStateStatus) => {
      focusManager.setFocused(state === 'active');
      if (state === 'background') backgroundAt.current = Date.now();
      if (state === 'active') {
        if (shouldLock(backgroundAt.current, Date.now(), config.autoLockMs)) lock();
        backgroundAt.current = null;
      }
    };
    const sub = AppState.addEventListener('change', onChange);
    return () => sub.remove();
  }, [lock]);
}

function RootNavigator() {
  const { c, scheme } = useTheme();
  const status = useSession((s) => s.status);
  const boot = useSession((s) => s.boot);
  useAppLifecycle();
  usePush(status === 'unlocked');

  useEffect(() => {
    void boot().finally(() => void SplashScreen.hideAsync());
  }, [boot]);

  // Deactivated or banned (session.closeAccount): the closed screen, never a silent sign-in.
  const closed = useClosure((s) => !!s.closure);
  useEffect(() => {
    if (closed && status === 'signedOut') router.replace('/account-closed');
  }, [closed, status]);

  if (status === 'booting') return null;

  const nav = scheme === 'dark' ? DarkTheme : DefaultTheme;
  return (
    <ThemeProvider value={{ ...nav, colors: { ...nav.colors, background: c.page, card: c.page, primary: c.accent, text: c.text, border: c.border } }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.page }, animation: 'fade' }}>
        <Stack.Screen name="index" options={{ animation: 'none' }} />
        <Stack.Screen name="account-closed" options={{ gestureEnabled: false }} />
        <Stack.Protected guard={status === 'signedOut'}>
          <Stack.Screen name="(auth)" />
        </Stack.Protected>
        <Stack.Protected guard={status === 'setup'}>
          <Stack.Screen name="(setup)" />
        </Stack.Protected>
        <Stack.Protected guard={status === 'locked'}>
          <Stack.Screen name="unlock" options={{ gestureEnabled: false }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'unlocked'}>
          <Stack.Screen name="(app)" />
        </Stack.Protected>
      </Stack>
      <PrivacyCover />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      {/* Restores the encrypted offline copy (lib/offline/cache.ts) and keeps it saved. */}
      <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
        <AppThemeProvider>
          <RootNavigator />
        </AppThemeProvider>
      </PersistQueryClientProvider>
    </GestureHandlerRootView>
  );
}
