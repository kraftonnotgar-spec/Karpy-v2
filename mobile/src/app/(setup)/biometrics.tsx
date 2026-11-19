import { router } from 'expo-router';
import { Fingerprint, ScanFace } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { Button } from '@/components/ui/button';
import { IconBadge } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { biometricKind, biometricLabel, promptBiometrics, setBiometricsEnabled, type BiometricKind } from '@/lib/auth/biometrics';
import { useSession } from '@/lib/auth/session';
import { haptic } from '@/lib/haptics';
import { notificationPermission } from '@/lib/push';
import { space } from '@/theme/tokens';

async function nextStep(finish: () => void) {
  if ((await notificationPermission()) === 'undetermined') router.replace('/notifications-intro');
  else finish();
}

/** Step 2: offer Face ID / Touch ID / fingerprint. Optional, never forced. */
export default function BiometricsSetup() {
  const finishSetup = useSession((s) => s.finishSetup);
  const [kind, setKind] = useState<BiometricKind>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void biometricKind().then(setKind);
  }, []);
  const label = biometricLabel(kind);

  async function enable() {
    setBusy(true);
    const ok = await promptBiometrics(t('biometrics.enablePrompt', { method: label }));
    setBusy(false);
    if (!ok) return;
    await setBiometricsEnabled(true);
    haptic.success();
    await nextStep(finishSetup);
  }

  return (
    <Screen
      edges={['top', 'bottom']}
      footer={
        <View style={{ gap: space.sm }}>
          <Button label={t('biometrics.use', { method: label })} onPress={() => void enable()} loading={busy} />
          <Button label={t('common.notNow')} variant="ghost" onPress={() => void setBiometricsEnabled(false).then(() => nextStep(finishSetup))} />
        </View>
      }>
      <View style={{ alignItems: 'center', gap: space.lg, marginTop: '30%' }}>
        <IconBadge icon={kind === 'face' ? ScanFace : Fingerprint} size={96} />
        <Text variant="title" align="center" accessibilityRole="header">
          {t('biometrics.title', { method: label })}
        </Text>
        <Text variant="callout" tone="muted" align="center" style={{ maxWidth: 320 }}>
          {t('biometrics.body')}
        </Text>
      </View>
    </Screen>
  );
}
