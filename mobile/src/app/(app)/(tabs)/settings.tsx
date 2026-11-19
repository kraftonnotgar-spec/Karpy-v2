import { Bell, Fingerprint, Lock, LogOut, Moon } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { Alert, Linking, Switch, View } from 'react-native';

import { Card, Divider, Row } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Segmented } from '@/components/ui/segmented';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { biometricKind, biometricLabel, biometricsEnabled, promptBiometrics, setBiometricsEnabled, type BiometricKind } from '@/lib/auth/biometrics';
import { useSession } from '@/lib/auth/session';
import { config } from '@/lib/config';
import { notificationPermission, registerPushDevice, requestNotificationPermission } from '@/lib/push';
import { useTheme, useThemeStore, type ThemePreference } from '@/theme/theme';
import { space } from '@/theme/tokens';

/** Settings: theme, app lock (biometrics, lock now), notifications, sign out. */
export default function SettingsScreen() {
  const { c } = useTheme();
  const preference = useThemeStore((s) => s.preference);
  const setPreference = useThemeStore((s) => s.setPreference);
  const lock = useSession((s) => s.lock);
  const signOut = useSession((s) => s.signOut);
  const [bioKind, setBioKind] = useState<BiometricKind>(null);
  const [bioOn, setBioOn] = useState(false);
  const [push, setPush] = useState<'granted' | 'undetermined' | 'denied'>('denied');

  useEffect(() => {
    void biometricKind().then(setBioKind);
    void biometricsEnabled().then(setBioOn);
    void notificationPermission().then(setPush);
  }, []);

  async function toggleBiometrics(next: boolean) {
    if (next && !(await promptBiometrics(t('biometrics.enablePrompt', { method: biometricLabel(bioKind) })))) return;
    await setBiometricsEnabled(next);
    setBioOn(next);
  }

  async function enablePush() {
    if (push === 'denied') {
      void Linking.openSettings();
      return;
    }
    if (await requestNotificationPermission()) await registerPushDevice().catch(() => false);
    setPush(await notificationPermission());
  }

  function confirmSignOut() {
    Alert.alert(t('settings.signOutTitle'), t('settings.signOutBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('settings.signOut'), style: 'destructive', onPress: () => void signOut() },
    ]);
  }

  const themes: { key: ThemePreference; label: string }[] = [
    { key: 'system', label: t('settings.themeSystem') },
    { key: 'light', label: t('settings.themeLight') },
    { key: 'dark', label: t('settings.themeDark') },
  ];

  return (
    <Screen>
      <View style={{ gap: space.xl, paddingTop: space.xl }}>
        <Text variant="title" accessibilityRole="header">
          {t('settings.title')}
        </Text>

        <Card style={{ gap: space.md }}>
          <Row icon={Moon} title={t('settings.appearance')} />
          <Segmented options={themes} value={preference} onChange={setPreference} />
        </Card>

        <Card padded={false} style={{ paddingHorizontal: space.lg, paddingVertical: space.xs }}>
          {bioKind ? (
            <>
              <Row
                icon={Fingerprint}
                title={t('settings.biometrics', { method: biometricLabel(bioKind) })}
                trailing={<Switch value={bioOn} onValueChange={(v) => void toggleBiometrics(v)} trackColor={{ true: c.primary, false: c.borderStrong }} />}
              />
              <Divider />
            </>
          ) : null}
          <Row icon={Lock} title={t('settings.lockNow')} detail={t('settings.autoLock', { seconds: Math.round(config.autoLockMs / 1000) })} onPress={lock} />
          <Divider />
          <Row
            icon={Bell}
            title={t('settings.notifications')}
            detail={push === 'granted' ? t('settings.notificationsOn') : t('settings.notificationsOff')}
            onPress={push === 'granted' ? undefined : () => void enablePush()}
          />
        </Card>

        <Card padded={false} style={{ paddingHorizontal: space.lg, paddingVertical: space.xs }}>
          <Row icon={LogOut} title={t('settings.signOut')} destructive onPress={confirmSignOut} />
        </Card>

        <Text variant="caption" tone="subtle" align="center">
          {t('settings.version', { version: config.appVersion })}
        </Text>
      </View>
    </Screen>
  );
}
