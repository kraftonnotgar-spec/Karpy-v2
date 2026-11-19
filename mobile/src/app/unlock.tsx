import { usePreventScreenCapture } from 'expo-screen-capture';
import { Fingerprint, ScanFace } from 'lucide-react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppMark } from '@/components/app-mark';
import { PinDots, PinPad } from '@/components/ui/pin-pad';
import { ScalePressable } from '@/components/ui/pressable';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { api } from '@/lib/api';
import { biometricKind, biometricLabel, biometricsEnabled, promptBiometrics, type BiometricKind } from '@/lib/auth/biometrics';
import { checkPin, MAX_ATTEMPTS, PIN_LENGTH } from '@/lib/auth/pin';
import { useSession } from '@/lib/auth/session';
import { firstName } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import { useTheme } from '@/theme/theme';
import { space } from '@/theme/tokens';

/**
 * App lock. Biometrics (if turned on) prompt at once; the PIN always works. MAX_ATTEMPTS wrong
 * PINs sign this device out (the account is untouched; a password sign-in sets a new PIN).
 */
export default function Unlock() {
  usePreventScreenCapture();
  const { c } = useTheme();
  const user = useSession((s) => s.user);
  const unlock = useSession((s) => s.unlock);
  const signOut = useSession((s) => s.signOut);
  const [pin, setPin] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(0);
  const [checking, setChecking] = useState(false);
  const [bio, setBio] = useState<BiometricKind>(null);
  const prompted = useRef(false);
  const entered = useRef(false);

  const enter = useCallback(() => {
    if (entered.current) return;
    entered.current = true;
    haptic.success();
    // Warm the access token while the app opens (offline: rejected and ignored).
    void api.refreshOnce().catch(() => null);
    unlock();
  }, [unlock]);

  const tryBiometrics = useCallback(async () => {
    if (await promptBiometrics()) enter();
  }, [enter]);

  useEffect(() => {
    void (async () => {
      const kind = (await biometricsEnabled()) ? await biometricKind() : null;
      setBio(kind);
      if (kind && !prompted.current) {
        prompted.current = true;
        void tryBiometrics();
      }
    })();
  }, [tryBiometrics]);

  async function submit(value: string) {
    setChecking(true);
    const result = await checkPin(value);
    setChecking(false);
    if (result.ok) return enter();
    haptic.error();
    setShake((n) => n + 1);
    setPin('');
    if (result.remaining <= 0) {
      Alert.alert(t('unlock.lockedOutTitle'), t('unlock.lockedOutBody', { attempts: MAX_ATTEMPTS }));
      await signOut();
      return;
    }
    setError(result.remaining === 1 ? t('unlock.wrongPinLast') : t('unlock.wrongPin', { remaining: result.remaining }));
  }

  function digit(d: string) {
    if (pin.length >= PIN_LENGTH || checking) return;
    setError(null);
    const value = pin + d;
    setPin(value);
    if (value.length === PIN_LENGTH) setTimeout(() => void submit(value), 120);
  }

  function forgot() {
    Alert.alert(t('unlock.forgotTitle'), t('unlock.forgotBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('unlock.signInAgain'), style: 'destructive', onPress: () => void signOut() },
    ]);
  }

  const name = firstName(typeof user?.name === 'string' ? user.name : '');
  const BioIcon = bio === 'face' ? ScanFace : Fingerprint;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.page }} edges={['top', 'bottom']}>
      <View style={styles.middle}>
        <AppMark size={48} />
        <View style={{ alignItems: 'center', gap: 4, marginTop: space.lg }}>
          <Text variant="headline" align="center" accessibilityRole="header">
            {t('unlock.title')}
          </Text>
          <Text variant="callout" tone="muted" align="center">
            {name ? t('unlock.welcomeName', { name }) : t('unlock.welcome')}
          </Text>
        </View>
        <View style={{ marginTop: space.xl }}>
          <PinDots key={`d${shake}`} length={PIN_LENGTH} filled={pin.length} error={shake > 0 && !!error} />
        </View>
        <Text variant="footnote" tone="negative" align="center" style={styles.error} accessibilityLiveRegion="assertive">
          {error ?? ''}
        </Text>
        <Pressable onPress={forgot} hitSlop={12} accessibilityRole="button" style={styles.link}>
          <Text variant="callout" tone="primary">
            {t('unlock.forgot')}
          </Text>
        </Pressable>
        {bio ? (
          <ScalePressable
            onPress={() => void tryBiometrics()}
            disabled={checking}
            scaleTo={0.92}
            accessibilityLabel={t('unlock.withMethod', { method: biometricLabel(bio) })}
            style={[styles.bio, { backgroundColor: c.accentSurface, borderColor: c.border }]}>
            <BioIcon size={30} color={c.accent} strokeWidth={1.7} />
          </ScalePressable>
        ) : null}
      </View>
      <View style={{ paddingBottom: space.md }}>
        <PinPad onDigit={digit} onDelete={() => setPin((p) => p.slice(0, -1))} disabled={checking} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  middle: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.xl },
  error: { minHeight: 20, marginTop: space.sm },
  link: { minHeight: 44, justifyContent: 'center' },
  bio: { width: 64, height: 64, borderRadius: 20, alignItems: 'center', justifyContent: 'center', borderWidth: StyleSheet.hairlineWidth, marginTop: space.md },
});
