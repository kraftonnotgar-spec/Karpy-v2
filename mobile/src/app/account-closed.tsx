import { Redirect, router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { AppMark } from '@/components/app-mark';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { useClosure } from '@/lib/auth/closure';
import { space } from '@/theme/tokens';

/**
 * Shown when the account was deactivated or banned (403 account_deactivated | account_banned
 * from refresh, login or verify-login). Outside every protected group: the device is already
 * signed out and wiped. Add the project's support contacts here.
 */
export default function AccountClosed() {
  const closure = useClosure((s) => s.closure);
  const clear = useClosure((s) => s.clear);

  if (!closure) return <Redirect href="/" />;
  const banned = closure.status === 'banned';

  return (
    <Screen
      edges={['top', 'bottom']}
      contentStyle={styles.content}
      footer={
        <Button
          label={t('closed.back')}
          variant="secondary"
          onPress={() => {
            clear();
            router.replace('/sign-in');
          }}
        />
      }>
      <View style={styles.stack}>
        <AppMark size={56} />
        <View style={{ gap: space.sm }}>
          <Text variant="title" align="center" accessibilityRole="header">
            {t(banned ? 'closed.bannedTitle' : 'closed.deactivatedTitle')}
          </Text>
          <Text variant="callout" tone="muted" align="center">
            {t(banned ? 'closed.bannedBody' : 'closed.deactivatedBody')}
          </Text>
        </View>
        {closure.reason ? (
          <Card style={{ alignSelf: 'stretch', gap: space.xs }}>
            <Text variant="caption" tone="muted">
              {t('closed.reason')}
            </Text>
            <Text variant="body">{closure.reason}</Text>
          </Card>
        ) : null}
        <Text variant="footnote" tone="muted" align="center">
          {t('closed.contact')}
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { flexGrow: 1, justifyContent: 'center', paddingVertical: space.xxxl },
  stack: { alignItems: 'center', gap: space.xxl },
});
