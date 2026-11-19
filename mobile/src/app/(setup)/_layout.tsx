import { Stack } from 'expo-router';

import { useTheme } from '@/theme/theme';

export const unstable_settings = { initialRouteName: 'create-pin' };

export default function SetupLayout() {
  const { c } = useTheme();
  return <Stack screenOptions={{ headerShown: false, gestureEnabled: false, contentStyle: { backgroundColor: c.page }, animation: 'slide_from_right' }} />;
}
