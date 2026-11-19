import { StyleSheet, View } from 'react-native';

import { useTheme } from '@/theme/theme';
import { weight } from '@/theme/tokens';
import { ScalePressable } from './pressable';
import { Text } from './text';

/** Segmented control (theme picker and similar short choices). */
export function Segmented<T extends string>({ options, value, onChange }: { options: { key: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  const { c } = useTheme();
  return (
    <View style={[styles.track, { backgroundColor: c.surfaceSunken }]} accessibilityRole="tablist">
      {options.map((o) => {
        const active = o.key === value;
        return (
          <ScalePressable
            key={o.key}
            scaleTo={0.98}
            onPress={() => onChange(o.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            style={[styles.item, { borderColor: c.transparent }, active && { backgroundColor: c.surfaceRaised, borderColor: c.border }]}>
            <Text variant="footnote" style={{ fontWeight: active ? weight.semibold : weight.medium, color: active ? c.text : c.textMuted }}>
              {o.label}
            </Text>
          </ScalePressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  track: { flexDirection: 'row', height: 36, borderRadius: 10, padding: 2 },
  item: { flex: 1, alignItems: 'center', justifyContent: 'center', borderRadius: 8, borderWidth: StyleSheet.hairlineWidth },
});
