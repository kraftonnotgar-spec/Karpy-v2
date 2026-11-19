import { router } from 'expo-router';
import { usePreventScreenCapture } from 'expo-screen-capture';
import { useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PinDots, PinPad } from '@/components/ui/pin-pad';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { biometricKind } from '@/lib/auth/biometrics';
import { PIN_LENGTH, savePin, weakPin } from '@/lib/auth/pin';
import { useSession } from '@/lib/auth/session';
import { haptic } from '@/lib/haptics';
import { notificationPermission } from '@/lib/push';
import { useTheme } from '@/theme/theme';
import { space } from '@/theme/tokens';

/** First sign-in on this device, step 1: create and confirm the app PIN. */
export default function CreatePin() {
  usePreventScreenCapture();
  const { c } = useTheme();
  const finishSetup = useSession((s) => s.finishSetup);
  const [first, setFirst] = useState<string | null>(null);
  const [pin, setPin] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(0);
  const [saving, setSaving] = useState(false);

  function fail(message: string) {
    haptic.error();
    setError(message);
    setShake((n) => n + 1);
    setPin('');
  }

  async function next(value: string) {
    if (!first) {
      if (weakPin(value)) return fail(t('pin.weak'));
      setFirst(value);
      setPin('');
      return;
    }
    if (value !== first) {
      setFirst(null);
      return fail(t('pin.mismatch'));
    }
    setSaving(true);
    await savePin(value);
    haptic.success();
    // Offer only what this device supports.
    if (await biometricKind()) router.replace('/biometrics');
    else if ((await notificationPermission()) === 'undetermined') router.replace('/notifications-intro');
    else finishSetup();
  }

  function digit(d: string) {
    if (pin.length >= PIN_LENGTH || saving) return;
    setError(null);
    const value = pin + d;
    setPin(value);
    if (value.length === PIN_LENGTH) setTimeout(() => void next(value), 120);
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.page }} edges={['top', 'bottom']}>
      <View style={{ flex: 1, justifyContent: 'center', gap: space.xxl, paddingHorizontal: space.xl }}>
        <View style={{ gap: space.sm }}>
          <Text variant="title" align="center" accessibilityRole="header">
            {first ? t('pin.confirmTitle') : t('pin.createTitle')}
          </Text>
          <Text variant="callout" tone="muted" align="center">
            {first ? t('pin.confirmBody', { length: PIN_LENGTH }) : t('pin.createBody')}
          </Text>
        </View>
        <PinDots key={`dots-${shake}`} length={PIN_LENGTH} filled={pin.length} error={!!error && shake > 0} />
        <Text variant="footnote" tone="negative" align="center" style={{ minHeight: 18 }} accessibilityLiveRegion="assertive">
          {error ?? ''}
        </Text>
      </View>
      <View style={{ paddingBottom: space.lg }}>
        <PinPad onDigit={digit} onDelete={() => setPin((p) => p.slice(0, -1))} disabled={saving} />
      </View>
    </SafeAreaView>
  );
}
