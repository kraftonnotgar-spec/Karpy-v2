import { View } from 'react-native';

import { useTheme } from '@/theme/theme';

/**
 * Placeholder app mark (a ring with a dot, matching assets/images/icon.png). Replace with the
 * project's logo (an SVG component via react-native-svg, or expo-image with an asset).
 */
export function AppMark({ size = 48 }: { size?: number }) {
  const { c } = useTheme();
  const ring = Math.max(2, Math.round(size * 0.09));
  const dot = size * 0.32;
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no"
      style={{ width: size, height: size, borderRadius: size / 2, borderWidth: ring, borderColor: c.primary, alignItems: 'center', justifyContent: 'center' }}>
      <View style={{ width: dot, height: dot, borderRadius: dot / 2, backgroundColor: c.primary }} />
    </View>
  );
}
