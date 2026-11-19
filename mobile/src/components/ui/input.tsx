import { Eye, EyeOff, type LucideIcon } from 'lucide-react-native';
import { forwardRef, useState, type ComponentRef, type ReactNode } from 'react';
import { Pressable, StyleSheet, TextInput, View, type TextInputProps } from 'react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme/theme';
import { radius, type as ramp } from '@/theme/tokens';
import { Text } from './text';

export type FieldProps = TextInputProps & {
  label: string;
  error?: string | null;
  hint?: string;
  icon?: LucideIcon;
  secure?: boolean;
  trailing?: ReactNode;
};

export const Field = forwardRef<ComponentRef<typeof TextInput>, FieldProps>(function Field(
  { label, error, hint, icon: Icon, secure, trailing, style, onFocus, onBlur, ...rest },
  ref,
) {
  const { c } = useTheme();
  const [focused, setFocused] = useState(false);
  const [hidden, setHidden] = useState(true);
  const borderColor = error ? c.negative : focused ? c.accent : c.border;
  return (
    <View style={{ gap: 6 }}>
      <Text variant="footnote" tone="muted">
        {label}
      </Text>
      <View style={[styles.box, { backgroundColor: c.surface, borderColor }, focused && { borderWidth: 1.5 }]}>
        {Icon ? <Icon size={18} color={c.textSubtle} /> : null}
        <TextInput
          ref={ref}
          placeholderTextColor={c.textSubtle}
          selectionColor={c.accent}
          secureTextEntry={secure && hidden}
          accessibilityLabel={label}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          style={[styles.input, { color: c.text }, style]}
          {...rest}
        />
        {secure ? (
          <Pressable
            onPress={() => setHidden((v) => !v)}
            hitSlop={12}
            accessibilityRole="button"
            accessibilityLabel={hidden ? t('common.showPassword') : t('common.hidePassword')}>
            {hidden ? <Eye size={19} color={c.textSubtle} /> : <EyeOff size={19} color={c.textSubtle} />}
          </Pressable>
        ) : null}
        {trailing}
      </View>
      {error ? (
        <Text variant="footnote" tone="negative" accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="footnote" tone="subtle">
          {hint}
        </Text>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 54, borderRadius: radius.md, borderWidth: 1, paddingHorizontal: 16 },
  input: { flex: 1, ...ramp.body, paddingVertical: 14 },
});
