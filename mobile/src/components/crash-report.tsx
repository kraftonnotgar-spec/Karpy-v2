import { Bug } from 'lucide-react-native';
import { useState } from 'react';
import { Modal, StyleSheet, View } from 'react-native';

import { Button } from '@/components/ui/button';
import { IconBadge } from '@/components/ui/card';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { clearLastCrash, crashUploadEnabled, lastCrash, uploadCrashReport } from '@/lib/crash';
import { useTheme } from '@/theme/theme';
import { radius, space } from '@/theme/tokens';

/** After a crash, asks once whether to send the details. Only when crash upload is configured. */
export function CrashReportPrompt() {
  const { c } = useTheme();
  const [report, setReport] = useState(() => (crashUploadEnabled ? lastCrash() : ''));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!report) return null;

  const dismiss = () => {
    clearLastCrash();
    setReport('');
  };

  const send = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await uploadCrashReport(report);
      dismiss();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={dismiss} statusBarTranslucent>
      <View style={[styles.backdrop, { backgroundColor: c.overlay }]}>
        <View style={[styles.card, { backgroundColor: c.surface }]}>
          <IconBadge icon={Bug} size={56} />
          <Text variant="headline" align="center">
            {t('crash.title')}
          </Text>
          <Text variant="callout" tone="muted" align="center">
            {t('crash.body')}
          </Text>
          {failed ? (
            <Text variant="footnote" tone="negative" align="center">
              {t('crash.failed')}
            </Text>
          ) : null}
          <View style={{ alignSelf: 'stretch', gap: space.sm, marginTop: space.sm }}>
            <Button label={t('crash.send')} onPress={() => void send()} loading={busy} />
            <Button label={t('common.notNow')} variant="ghost" onPress={dismiss} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.xl },
  card: { alignSelf: 'stretch', borderRadius: radius.xl, padding: space.xl, alignItems: 'center', gap: space.sm },
});
