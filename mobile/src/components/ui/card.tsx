import type { LucideIcon } from 'lucide-react-native';
import { ChevronRight } from 'lucide-react-native';
import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { shadow, useTheme } from '@/theme/theme';
import { radius, space } from '@/theme/tokens';
import { ScalePressable } from './pressable';
import { Text } from './text';

/** A grouped surface on the page background. */
export function Card({ children, style, padded = true }: { children: ReactNode; style?: StyleProp<ViewStyle>; padded?: boolean }) {
  const { c, scheme } = useTheme();
  return (
    <View
      style={[
        { backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, borderColor: c.border },
        padded && { padding: space.lg },
        shadow(scheme, c),
        style,
      ]}>
      {children}
    </View>
  );
}

/** Small round tinted container for icons. */
export function IconBadge({ icon: Icon, size = 40 }: { icon: LucideIcon; size?: number }) {
  const { c } = useTheme();
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: c.accentSurface, alignItems: 'center', justifyContent: 'center' }}>
      <Icon size={size * 0.48} color={c.accent} strokeWidth={1.9} />
    </View>
  );
}

/** A settings-style row: icon, title, optional detail, and a trailing control or chevron. */
export function Row({
  icon: Icon,
  title,
  detail,
  trailing,
  onPress,
  destructive,
}: {
  icon?: LucideIcon;
  title: string;
  detail?: string;
  trailing?: ReactNode;
  onPress?: () => void;
  destructive?: boolean;
}) {
  const { c } = useTheme();
  const body = (
    <View style={styles.row}>
      {Icon ? <Icon size={20} color={destructive ? c.negative : c.textMuted} /> : null}
      <View style={{ flex: 1 }}>
        <Text variant="bodyStrong" tone={destructive ? 'negative' : 'default'}>
          {title}
        </Text>
        {detail ? (
          <Text variant="footnote" tone="muted">
            {detail}
          </Text>
        ) : null}
      </View>
      {trailing ?? (onPress ? <ChevronRight size={18} color={c.textSubtle} /> : null)}
    </View>
  );
  if (!onPress) return body;
  return (
    <ScalePressable onPress={onPress} scaleTo={0.99} accessibilityLabel={title}>
      {body}
    </ScalePressable>
  );
}

export function Divider() {
  const { c } = useTheme();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: c.border, marginVertical: space.xs }} />;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 52, paddingVertical: space.sm },
});
