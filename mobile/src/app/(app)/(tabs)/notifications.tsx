import { Bell } from 'lucide-react-native';
import { View } from 'react-native';

import { IconBadge } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { space } from '@/theme/tokens';

/**
 * Placeholder for an activity / notifications feed. Wire a `useQuery({ queryKey: qk.notifications })`
 * to the project's endpoint; the key is already in the offline allow-list.
 */
export default function Notifications() {
  return (
    <Screen>
      <View style={{ gap: space.xl, paddingTop: space.xl }}>
        <Text variant="title" accessibilityRole="header">
          {t('notifications.title')}
        </Text>
        <View style={{ alignItems: 'center', gap: space.md, paddingTop: space.xxxl }}>
          <IconBadge icon={Bell} size={64} />
          <Text variant="subhead" align="center">
            {t('notifications.emptyTitle')}
          </Text>
          <Text variant="callout" tone="muted" align="center">
            {t('notifications.emptyBody')}
          </Text>
        </View>
      </View>
    </Screen>
  );
}
