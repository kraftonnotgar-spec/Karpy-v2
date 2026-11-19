import { Stack } from 'expo-router';

import { useTheme } from '@/theme/theme';

export const unstable_settings = { initialRouteName: 'sign-in' };

export default function AuthLayout() {
  const { c } = useTheme();
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.page }, animation: 'slide_from_right' }} />;
}
