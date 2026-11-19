import { Tabs } from 'expo-router/js-tabs';
import { Bell, House, Settings } from 'lucide-react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme/theme';

/**
 * The tab shell. To add a feature tab: create `src/app/(app)/(tabs)/<name>.tsx`, add a
 * `<Tabs.Screen name="<name>" />` below with a title from en.json and a lucide icon.
 */
export default function TabsLayout() {
  const { c } = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: c.page },
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.textSubtle,
        tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border },
      }}>
      <Tabs.Screen name="home" options={{ title: t('tabs.home'), tabBarIcon: ({ color, size }) => <House color={color} size={size} /> }} />
      <Tabs.Screen
        name="notifications"
        options={{ title: t('tabs.notifications'), tabBarIcon: ({ color, size }) => <Bell color={color} size={size} /> }}
      />
      <Tabs.Screen name="settings" options={{ title: t('tabs.settings'), tabBarIcon: ({ color, size }) => <Settings color={color} size={size} /> }} />
    </Tabs>
  );
}
