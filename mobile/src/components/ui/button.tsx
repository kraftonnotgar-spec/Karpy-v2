import type { LucideIcon } from 'lucide-react-native';
import { ActivityIndicator, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme/theme';
import { radius } from '@/theme/tokens';
import { ScalePressable } from './pressable';
import { Text } from './text';

type Variant = 'primary' | 'secondary' | 'ghost' | 'destructive';

export type ButtonProps = {
  label: string;
  onPress?: () => void;
  variant?: Variant;
  size?: 'lg' | 'md' | 'sm';
  icon?: LucideIcon;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityHint?: string;
};

export function Button({ label, onPress, variant = 'primary', size = 'lg', icon: Icon, loading, disabled, style, accessibilityHint }: ButtonProps) {
  const { c } = useTheme();
  const palette = {
    primary: { bg: c.primary, fg: c.primaryText, border: c.primary },
    secondary: { bg: c.surface, fg: c.text, border: c.border },
    ghost: { bg: c.transparent, fg: c.accent, border: c.transparent },
    destructive: { bg: c.negativeSurface, fg: c.negative, border: c.transparent },
  }[variant];
  const height = { lg: 54, md: 46, sm: 36 }[size];
  return (
    <ScalePressable
      onPress={onPress}
      disabled={disabled || loading}
      feedback={variant === 'primary' ? 'soft' : 'tap'}
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
      style={[
        styles.base,
        { height, backgroundColor: palette.bg, borderColor: palette.border, borderRadius: size === 'sm' ? radius.pill : radius.md },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={palette.fg} />
      ) : (
        <View style={styles.row}>
          {Icon ? <Icon size={size === 'sm' ? 16 : 19} color={palette.fg} strokeWidth={2} /> : null}
          <Text variant={size === 'sm' ? 'caption' : 'bodyStrong'} style={{ color: palette.fg }}>
            {label}
          </Text>
        </View>
      )}
    </ScalePressable>
  );
}

const styles = StyleSheet.create({
  base: { alignItems: 'center', justifyContent: 'center', borderWidth: StyleSheet.hairlineWidth, paddingHorizontal: 20 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});
