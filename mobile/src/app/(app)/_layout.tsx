import { Stack } from 'expo-router';
import { View } from 'react-native';

import { CrashReportPrompt } from '@/components/crash-report';
import { OfflineBanner } from '@/components/offline-banner';
import { useTheme } from '@/theme/theme';

export const unstable_settings = { initialRouteName: '(tabs)' };

/**
 * Signed-in and unlocked area. The tabs are the root; push detail screens of a feature here
 * with `<Stack.Screen name="feature/[id]" options={{ headerShown: true, title: ... }} />`.
 */
export default function AppLayout() {
  const { c } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: c.page }}>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.page } }}>
        <Stack.Screen name="(tabs)" />
      </Stack>
      <CrashReportPrompt />
      <OfflineBanner />
    </View>
  );
}
