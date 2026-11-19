import { BellRing } from 'lucide-react-native';
import { useState } from 'react';
import { View } from 'react-native';

import { Button } from '@/components/ui/button';
import { IconBadge } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { useSession } from '@/lib/auth/session';
import { haptic } from '@/lib/haptics';
import { registerPushDevice, requestNotificationPermission } from '@/lib/push';
import { space } from '@/theme/tokens';

/**
 * Permission priming: explain first, show the OS prompt only after "Turn on". On grant the push
 * token is registered with the backend (POST /push-devices).
 */
export default function NotificationsIntro() {
  const finishSetup = useSession((s) => s.finishSetup);
  const [busy, setBusy] = useState(false);

  async function turnOn() {
    setBusy(true);
    if (await requestNotificationPermission()) {
      haptic.success();
      await registerPushDevice().catch(() => false);
    }
    setBusy(false);
    finishSetup();
  }

  return (
    <Screen
      edges={['top', 'bottom']}
      footer={
        <View style={{ gap: space.sm }}>
          <Button label={t('notificationsIntro.turnOn')} icon={BellRing} onPress={() => void turnOn()} loading={busy} />
          <Button label={t('common.notNow')} variant="ghost" onPress={finishSetup} />
        </View>
      }>
      <View style={{ alignItems: 'center', gap: space.lg, marginTop: '30%' }}>
        <IconBadge icon={BellRing} size={96} />
        <Text variant="title" align="center" accessibilityRole="header">
          {t('notificationsIntro.title')}
        </Text>
        <Text variant="callout" tone="muted" align="center" style={{ maxWidth: 320 }}>
          {t('notificationsIntro.body')}
        </Text>
      </View>
    </Screen>
  );
}
