import { useEffect, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';

import { AppMark } from '@/components/app-mark';
import { useTheme } from '@/theme/theme';

/** Covers the screen while the app is inactive so the app-switcher snapshot shows no data. */
export function PrivacyCover() {
  const { c } = useTheme();
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => setHidden(s !== 'active'));
    return () => sub.remove();
  }, []);
  if (!hidden) return null;
  return (
    <View style={[StyleSheet.absoluteFill, { backgroundColor: c.page, alignItems: 'center', justifyContent: 'center' }]} pointerEvents="none">
      <AppMark size={64} />
    </View>
  );
}
