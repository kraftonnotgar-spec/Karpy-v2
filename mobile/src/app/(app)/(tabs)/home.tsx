import { View } from 'react-native';

import { Card } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { errorMessage } from '@/lib/api';
import { firstName, partOfDay } from '@/lib/format';
import { lastUpdatedTime } from '@/lib/offline/rules';
import { useMe } from '@/lib/queries';
import { space } from '@/theme/tokens';

/**
 * Home: a greeting from GET /me (saved for offline reading) as the example of a server-backed,
 * offline-capable screen. Replace the card with the project's own dashboard.
 */
export default function Home() {
  const me = useMe();
  const name = firstName(typeof me.data?.name === 'string' ? me.data.name : '');
  const updated = lastUpdatedTime(me.dataUpdatedAt);
  return (
    <Screen onRefresh={() => void me.refetch()} refreshing={me.isRefetching}>
      <View style={{ gap: space.xl, paddingTop: space.xl }}>
        <Text variant="title" accessibilityRole="header">
          {name ? t(`home.greetingName.${partOfDay()}`, { name }) : t(`home.greeting.${partOfDay()}`)}
        </Text>
        <Card style={{ gap: space.sm }}>
          <Text variant="subhead">{t('home.cardTitle')}</Text>
          <Text variant="callout" tone="muted">
            {t('home.cardBody')}
          </Text>
          {typeof me.data?.email === 'string' ? <Text variant="footnote">{me.data.email}</Text> : null}
          {me.error && !me.data ? (
            <Text variant="footnote" tone="negative">
              {errorMessage(me.error)}
            </Text>
          ) : null}
          {updated ? (
            <Text variant="caption" tone="subtle">
              {t('offline.lastUpdated', { time: updated })}
            </Text>
          ) : null}
        </Card>
      </View>
    </Screen>
  );
}
