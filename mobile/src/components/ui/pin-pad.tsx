import { Delete } from 'lucide-react-native';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withSequence, withSpring, withTiming } from 'react-native-reanimated';

import { t } from '@/i18n';
import { haptic } from '@/lib/haptics';
import { useTheme } from '@/theme/theme';
import { weight } from '@/theme/tokens';
import { ScalePressable } from './pressable';
import { Text } from './text';

/** PIN dots. A wrong PIN shakes the row (remount with a new `key` to replay). */
export function PinDots({ length, filled, error }: { length: number; filled: number; error?: boolean }) {
  const { c } = useTheme();
  const x = useSharedValue(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (error && !reduce) {
      x.set(withSequence(withTiming(-12, { duration: 45 }), withTiming(10, { duration: 55 }), withTiming(-6, { duration: 55 }), withSpring(0, { damping: 12, stiffness: 300 })));
    }
  }, [error, reduce, x]);
  const shake = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }] }));
  return (
    <Animated.View style={[styles.dots, shake]} accessibilityLabel={t('pin.progress', { filled, length })}>
      {Array.from({ length }, (_, i) => (
        <View key={i} style={[styles.box, { backgroundColor: c.surface, borderColor: error ? c.negative : i === filled ? c.accent : c.border }]}>
          {i < filled ? <View style={[styles.fill, { backgroundColor: error ? c.negative : c.text }]} /> : null}
        </View>
      ))}
    </Animated.View>
  );
}

/** Full-width keypad docked in the thumb zone. */
export function PinPad({ onDigit, onDelete, disabled }: { onDigit: (d: string) => void; onDelete: () => void; disabled?: boolean }) {
  const { c, scheme } = useTheme();
  const tile = scheme === 'dark' ? c.surfaceRaised : c.surface;
  const key = (label: string) => (
    <ScalePressable
      key={label}
      disabled={disabled}
      scaleTo={0.92}
      onPress={() => onDigit(label)}
      accessibilityLabel={label}
      style={[styles.key, { backgroundColor: tile, borderColor: c.border }]}>
      <Text style={[styles.digit, { color: c.text }]}>{label}</Text>
    </ScalePressable>
  );
  const digits = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
  return (
    <View style={styles.pad}>
      {[0, 1, 2].map((r) => (
        <View key={r} style={styles.padRow}>
          {digits.slice(r * 3, r * 3 + 3).map(key)}
        </View>
      ))}
      <View style={styles.padRow}>
        <View style={[styles.key, { backgroundColor: c.transparent, borderColor: c.transparent }]} />
        {key('0')}
        <ScalePressable
          onPress={() => {
            haptic.soft();
            onDelete();
          }}
          feedback="none"
          disabled={disabled}
          scaleTo={0.92}
          accessibilityLabel={t('pin.delete')}
          style={[styles.key, { backgroundColor: c.transparent, borderColor: c.transparent }]}>
          <Delete size={26} color={c.text} strokeWidth={1.7} />
        </ScalePressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  dots: { flexDirection: 'row', gap: 14, justifyContent: 'center' },
  box: { width: 54, height: 58, borderRadius: 16, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  fill: { width: 14, height: 14, borderRadius: 7 },
  pad: { gap: 10, paddingHorizontal: 16 },
  padRow: { flexDirection: 'row', gap: 10 },
  key: { flex: 1, height: 60, borderRadius: 18, alignItems: 'center', justifyContent: 'center', borderWidth: StyleSheet.hairlineWidth },
  digit: { fontSize: 26, lineHeight: 30, fontWeight: weight.medium },
});
