import { Wifi, WifiOff } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { AccessibilityInfo, StyleSheet, View } from 'react-native';
import Animated, { FadeInUp, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { haptic } from '@/lib/haptics';
import { useNetwork } from '@/lib/offline/network';
import { queryClient } from '@/lib/queries';
import { useTheme } from '@/theme/theme';
import { radius } from '@/theme/tokens';

const BACK_ONLINE_MS = 1800;

/**
 * Thin pill under the status bar: "You're offline · Showing saved data" while offline, then
 * "Back online" for a moment (and everything refetches). Taps pass through.
 */
export function OfflineBanner() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const online = useNetwork((s) => s.online);
  const [mode, setMode] = useState<'hidden' | 'offline' | 'back'>(online ? 'hidden' : 'offline');
  const [seen, setSeen] = useState(online);

  // Connectivity changed: pick the pill during render (no effect-driven state).
  if (online !== seen) {
    setSeen(online);
    setMode(online ? 'back' : 'offline');
  }

  useEffect(() => {
    if (mode === 'offline') {
      AccessibilityInfo.announceForAccessibility(t('offline.banner'));
      return;
    }
    if (mode !== 'back') return;
    haptic.soft();
    AccessibilityInfo.announceForAccessibility(t('offline.back'));
    // Paused queries resume on their own (onlineManager); refetch everything else too.
    void queryClient.invalidateQueries();
    const timer = setTimeout(() => setMode('hidden'), BACK_ONLINE_MS);
    return () => clearTimeout(timer);
  }, [mode]);

  if (mode === 'hidden') return null;
  const back = mode === 'back';
  const fg = back ? c.positive : c.pending;
  const Icon = back ? Wifi : WifiOff;
  return (
    <View style={[styles.dock, { top: insets.top + 6 }]} pointerEvents="none">
      <Animated.View
        entering={FadeInUp.duration(280)}
        exiting={FadeOutUp.duration(220)}
        style={[styles.pill, { backgroundColor: back ? c.positiveSurface : c.pendingSurface, borderColor: c.border }]}
        accessibilityRole="alert">
        <Icon size={14} color={fg} strokeWidth={2.2} />
        <Text variant="caption" style={{ color: fg }}>
          {back ? t('offline.back') : t('offline.banner')}
        </Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  dock: { position: 'absolute', left: 0, right: 0, alignItems: 'center', zIndex: 900, elevation: 900 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, borderWidth: StyleSheet.hairlineWidth },
});
